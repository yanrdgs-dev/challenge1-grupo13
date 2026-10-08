"""Rota e endpoint unificado para verificação integral de notícias via URL.

Atende aos critérios da Task 4.3:
- Endpoint POST /api/v1/verify-url criado e exposto na API.
- Payload de entrada recebendo {"url": "https://..."}.
- Encadeamento completo: Ingestão da URL -> Extração de Claims -> Execução do Grafo de Verificação em Lote.
- Tempo de resposta monitorado e controlado para não ultrapassar limites de timeout de rede do cliente.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.nodes.article_aggregator import article_aggregator_node
from src.agents.nodes.claim_extractor import claim_extractor_node
from src.agents.pipeline import FactCheckingPipeline
from src.api.routes.factcheck import get_pipeline
from src.schemas.claims import AtomicClaim
from src.services.url_scraper import extract_article, is_valid_url

logger = logging.getLogger("API.VerifyUrl")

router = APIRouter(tags=["verify-url"])

# Limites de controle de tempo para garantir respostas antes de timeouts do cliente
MAX_VERIFY_TIMEOUT = float(os.getenv("VERIFY_URL_TIMEOUT", "25.0"))
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "8"))


class VerifyUrlRequest(BaseModel):
    """Payload de entrada para verificação de notícias via URL."""

    url: str = Field(..., min_length=1, description="URL da matéria jornalística para fact-checking")


class ArticleMetadata(BaseModel):
    """Metadados do artigo jornalístico extraído."""

    title: Optional[str] = None
    author: Optional[str] = None
    publish_date: Optional[str] = None
    url: str


class ClaimVerificationResult(BaseModel):
    """Resultado da auditoria e verificação de uma alegação atômica individual."""

    claim: str
    category: Optional[str] = None
    target_entity: Optional[str] = None
    verdict: str  # VERDADEIRO | FALSO | INCONCLUSIVO
    confidence: str  # ALTA | MEDIA | BAIXA
    explanation: str
    sources: List[str] = []
    rule_matched: Optional[str] = None
    latency_seconds: Dict[str, float] = {}


class LatencyBreakdown(BaseModel):
    """Métricas de monitoramento de tempo por etapa do pipeline."""

    scraping: float
    claim_extraction: float
    batch_verification: float
    total: float


class VerifyUrlResponse(BaseModel):
    """Resposta estruturada e completa da verificação integral da notícia."""

    url: str
    success: bool
    message: str
    article: Optional[ArticleMetadata] = None
    claims_count: int = 0
    claims: List[ClaimVerificationResult] = []
    overall_verdict: str  # VERDADEIRO | FALSO | PARCIALMENTE_FALSO | ENGANOSO | INCONCLUSIVO
    reliability_score: float = 0.0
    executive_summary: Optional[str] = None
    latency_seconds: LatencyBreakdown
    timeout_exceeded: bool = False


def _compute_overall_verdict(claims: List[ClaimVerificationResult]) -> str:
    """Calcula o veredito geral da matéria com base nas alegações individuais checadas."""
    if not claims:
        return "INCONCLUSIVO"

    verdicts = [c.verdict.upper() for c in claims]
    has_falso = any("FALSO" in v for v in verdicts)
    has_verdadeiro = any("VERDADEIRO" in v for v in verdicts)

    if has_falso and has_verdadeiro:
        return "PARCIALMENTE_FALSO"
    if has_falso:
        return "FALSO"
    if all("VERDADEIRO" in v for v in verdicts):
        return "VERDADEIRO"
    return "INCONCLUSIVO"


@router.post("/api/v1/verify-url", response_model=VerifyUrlResponse)
@router.post("/api/verify-url", response_model=VerifyUrlResponse)
def verify_url_endpoint(request: VerifyUrlRequest) -> VerifyUrlResponse:
    """Endpoint unificado de verificação integral de matérias jornalísticas via URL.

    Encadeia:
    1. Ingestão e raspagem da URL com coleta de metadados e limpeza de corpo textual.
    2. Decomposição do texto em até 5 alegações atômicas e verificáveis contra dados públicos.
    3. Execução em lote do Grafo de Verificação Multiagente sobre cada alegação.
    4. Controle de timeout de rede e monitoramento de latência por estágio.
    """
    t_start = time.perf_counter()
    clean_url = request.url.strip() if request.url else ""

    # 1. Validação estrita da URL fornecida
    if not clean_url or not is_valid_url(clean_url):
        raise HTTPException(
            status_code=400,
            detail="A URL fornecida é inválida ou não possui esquema HTTP/HTTPS válido.",
        )

    # 2. Ingestão da Notícia via Web Scraping
    t_scraping_start = time.perf_counter()
    logger.info("Iniciando extração do artigo da URL: %s", clean_url)
    article_data = extract_article(clean_url, timeout=SCRAPER_TIMEOUT)
    t_scraping = round(time.perf_counter() - t_scraping_start, 3)

    if not article_data.get("success"):
        error_msg = article_data.get("message", "Falha desconhecida na extração do conteúdo da página.")
        logger.warning("Falha na ingestão da URL %s: %s", clean_url, error_msg)
        raise HTTPException(
            status_code=400,
            detail=f"Falha na extração da notícia: {error_msg}",
        )

    clean_text = article_data.get("clean_text", "").strip()
    article_metadata = ArticleMetadata(
        title=article_data.get("title"),
        author=article_data.get("author"),
        publish_date=article_data.get("publish_date"),
        url=clean_url,
    )

    # 3. Extração de Alegações Atômicas via Nó Claim Extractor
    t_extraction_start = time.perf_counter()
    atomic_claims = claim_extractor_node(clean_text, max_claims=5)
    t_extraction = round(time.perf_counter() - t_extraction_start, 3)

    # Se a matéria não possuir alegações verificáveis (ex.: editorial, opinião pura)
    if not atomic_claims:
        t_total = round(time.perf_counter() - t_start, 3)
        empty_agg = article_aggregator_node(claims=[], article_title=article_metadata.title)
        return VerifyUrlResponse(
            url=clean_url,
            success=True,
            message="Nenhuma alegação factual verificável identificada no artigo.",
            article=article_metadata,
            claims_count=0,
            claims=[],
            overall_verdict="INCONCLUSIVO",
            reliability_score=0.0,
            executive_summary=empty_agg.executive_summary,
            latency_seconds=LatencyBreakdown(
                scraping=t_scraping,
                claim_extraction=t_extraction,
                batch_verification=0.0,
                total=t_total,
            ),
            timeout_exceeded=False,
        )

    # 4. Execução do Grafo de Verificação em Lote com Controle de Timeout
    t_batch_start = time.perf_counter()
    pipeline = get_pipeline()
    verified_results: List[ClaimVerificationResult] = []
    timeout_exceeded = False

    for item in atomic_claims:
        # Verifica se o tempo restante ainda é seguro antes de iniciar a próxima claim
        elapsed_so_far = time.perf_counter() - t_start
        if elapsed_so_far >= MAX_VERIFY_TIMEOUT - 2.0:
            logger.warning(
                "Limite de tempo de resposta atingido (%ss). Interrompendo lote defensivamente.",
                round(elapsed_so_far, 2),
            )
            timeout_exceeded = True
            break

        try:
            check_res = pipeline.verify(item.claim)
            verdict = check_res.get("verdict", "INCONCLUSIVO")
            explanation = check_res.get("explanation", "")
            confidence = check_res.get("confidence", "MEDIA")
            sources = check_res.get("sources_cited", []) or []
            plan = check_res.get("plan", {})
            latency = check_res.get("latency_seconds", {})

            # Enriquecimento de fontes a partir das evidências caso não estejam no topo
            evidences = check_res.get("evidences", [])
            collected_sources = list(sources)
            for ev in evidences:
                data = ev.get("data", {})
                if isinstance(data, dict):
                    if data.get("fonte_normativa") and data["fonte_normativa"] not in collected_sources:
                        collected_sources.append(data["fonte_normativa"])
                    if data.get("base_legal") and data["base_legal"] not in collected_sources:
                        collected_sources.append(data["base_legal"])

            verified_results.append(
                ClaimVerificationResult(
                    claim=item.claim,
                    category=item.category,
                    target_entity=item.target_entity,
                    verdict=verdict,
                    confidence=confidence,
                    explanation=explanation,
                    sources=collected_sources,
                    rule_matched=plan.get("reasoning"),
                    latency_seconds=latency,
                )
            )
        except Exception as e:
            logger.error("Erro ao verificar alegação individual '%s': %s", item.claim, e)
            verified_results.append(
                ClaimVerificationResult(
                    claim=item.claim,
                    category=item.category,
                    target_entity=item.target_entity,
                    verdict="INCONCLUSIVO",
                    confidence="BAIXA",
                    explanation="Falha técnica pontual durante checagem da alegação contra bases oficiais.",
                    sources=[],
                    rule_matched="erro_execucao",
                    latency_seconds={},
                )
            )

    t_batch = round(time.perf_counter() - t_batch_start, 3)
    t_total = round(time.perf_counter() - t_start, 3)

    # 5. Agregação Executiva de Veredito da Matéria
    agg_result = article_aggregator_node(
        claims=verified_results,
        article_title=article_metadata.title,
    )

    return VerifyUrlResponse(
        url=clean_url,
        success=True,
        message="Verificação integral da notícia concluída com sucesso.",
        article=article_metadata,
        claims_count=len(verified_results),
        claims=verified_results,
        overall_verdict=agg_result.overall_status,
        reliability_score=agg_result.reliability_score,
        executive_summary=agg_result.executive_summary,
        latency_seconds=LatencyBreakdown(
            scraping=t_scraping,
            claim_extraction=t_extraction,
            batch_verification=t_batch,
            total=t_total,
        ),
        timeout_exceeded=timeout_exceeded,
    )

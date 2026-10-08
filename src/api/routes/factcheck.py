"""Rotas e integração do pipeline multiagente para endpoints de fact-checking e cidadania."""

import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.pipeline import FactCheckingPipeline

logger = logging.getLogger("API.FactCheck")

router = APIRouter(prefix="/api", tags=["factcheck"])

# Instância singleton do pipeline de fact-checking multiagente
_pipeline: Optional[FactCheckingPipeline] = None


def get_pipeline() -> FactCheckingPipeline:
    """Retorna ou inicializa o pipeline de fact-checking com os agentes."""
    global _pipeline
    if _pipeline is None:
        _pipeline = FactCheckingPipeline()
    return _pipeline


class CheckRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Texto da alegação ou dúvida política")


class CheckResponse(BaseModel):
    id: str
    query: str
    verdict: str  # VERDADEIRO | FALSO | INCONCLUSIVO | VERIFICADO
    text: str
    subdetails: List[str] = []
    sources: List[str] = []
    rule_matched: Optional[str] = None


class SuggestionItem(BaseModel):
    icon: str
    eyebrow: str
    text: str


@router.get("/suggestions", response_model=List[SuggestionItem])
def get_suggestions() -> List[SuggestionItem]:
    """Retorna o catálogo de sugestões para a interface Pólis."""
    return [
        SuggestionItem(
            icon="ballot",
            eyebrow="Eleições",
            text="Como funciona o segundo turno no Brasil?",
        ),
        SuggestionItem(
            icon="book",
            eyebrow="Cidadania",
            text="A votação de ministro do STF no Senado é secreta?",
        ),
        SuggestionItem(
            icon="file",
            eyebrow="Cota Parlamentar",
            text="Todo deputado federal tem um teto fixo de R$ 500 por ano para combustível?",
        ),
        SuggestionItem(
            icon="archive",
            eyebrow="Transparência",
            text="Dá para ver no site do TSE quanto cada candidato declarou ter gastado?",
        ),
    ]


@router.post("/check", response_model=CheckResponse)
def check_claim(request: CheckRequest) -> CheckResponse:
    """Endpoint principal de checagem conectando o modelo multiagente à interface."""
    clean_query = request.query.strip() if request.query else ""
    if not clean_query:
        raise HTTPException(status_code=400, detail="Consulta não pode ser vazia.")

    res_id = f"chk-{uuid.uuid4().hex[:8]}"

    try:
        pipeline = get_pipeline()
        res = pipeline.verify(clean_query)

        verdict = res.get("verdict", "INCONCLUSIVO")
        explanation = res.get("explanation", "")
        confidence = res.get("confidence", "MEDIA")
        latency = res.get("latency_seconds", {})
        plan = res.get("plan", {})
        evidences = res.get("evidences", [])
        sources_cited = res.get("sources_cited", []) or []

        # Se inconclusivo sem justificativa explícita
        if verdict == "INCONCLUSIVO" and not explanation:
            explanation = "Alegação subespecificada ou inconclusiva: não foram encontradas evidências suficientes para comprovação ou refutação definitiva."

        # Consolidação de fontes oficiais citadas e normativas
        collected_sources: List[str] = list(sources_cited)
        for ev in evidences:
            data = ev.get("data", {})
            if isinstance(data, dict):
                if data.get("fonte_normativa") and data["fonte_normativa"] not in collected_sources:
                    collected_sources.append(data["fonte_normativa"])
                if data.get("base_legal") and data["base_legal"] not in collected_sources:
                    collected_sources.append(data["base_legal"])
                if data.get("url_referencia") and data["url_referencia"] not in collected_sources:
                    collected_sources.append(data["url_referencia"])
                if ev.get("tool") == "resolve_politician" and data.get("casa"):
                    if data["casa"] not in collected_sources:
                        collected_sources.append(data["casa"])

        if not collected_sources:
            if verdict == "INCONCLUSIVO":
                collected_sources = ["Constituição do Agente de Fact-Checking", "Diretrizes de Rastreabilidade"]
            else:
                collected_sources = ["Bases de Dados Abertos (Câmara dos Deputados, Senado Federal, TSE)"]

        subdetails = [
            f"Grau de Confiança: {confidence}",
            f"Tempo total: {latency.get('total', 0)}s (Orquestrador: {latency.get('orchestrator', 0)}s | Tools: {latency.get('tools', 0)}s | Sintetizador: {latency.get('synthesizer', 0)}s)",
        ]

        if evidences:
            tools_used = [e.get("tool") for e in evidences if e.get("tool")]
            if tools_used:
                subdetails.append(f"Ferramentas auditadas: {', '.join(tools_used)}")

        return CheckResponse(
            id=res_id,
            query=clean_query,
            verdict=verdict,
            text=explanation,
            subdetails=subdetails,
            sources=collected_sources,
            rule_matched=plan.get("reasoning"),
        )
    except Exception as exc:
        logger.error("Erro durante execução do pipeline de fact-checking: %s", exc, exc_info=True)
        return CheckResponse(
            id=res_id,
            query=clean_query,
            verdict="INCONCLUSIVO",
            text="Não foi possível processar a consulta no momento devido a uma falha de comunicação com os serviços de dados abertos.",
            subdetails=[f"Detalhe técnico: {str(exc)}"],
            sources=["Sistema de Fact-Checking"],
            rule_matched="fallback_erro",
        )

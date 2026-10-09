"""Rotas e integração do pipeline multiagente para endpoints de fact-checking e cidadania."""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agents.pipeline import FactCheckingPipeline

logger = logging.getLogger("API.FactCheck")

router = APIRouter(prefix="/api", tags=["factcheck"])

# Instância singleton do pipeline de fact-checking multiagente
_pipeline: Optional[FactCheckingPipeline] = None

# Armazenamento em memória para validações e feedbacks dos usuários
_feedback_store: List[Dict[str, Any]] = []


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


class FeedbackRequest(BaseModel):
    message_id: str = Field(..., min_length=1, description="ID da mensagem auditada")
    rating: Literal["positive", "negative"] = Field(..., description="Validação: 'positive' ou 'negative'")
    query: Optional[str] = Field(None, description="Consulta original")
    verdict: Optional[str] = Field(None, description="Veredito emitido pelo sistema")
    reason: Optional[str] = Field(None, description="Motivo selecionado para avaliação")
    comment: Optional[str] = Field(None, description="Comentário adicional opcional")


class FeedbackResponse(BaseModel):
    status: str = "ok"
    feedback_id: str
    message: str


def _build_check_response(clean_query: str, res_id: str, res: Dict[str, Any]) -> CheckResponse:
    """Consolida os dados retornados pelo pipeline em um CheckResponse estruturado."""
    verdict = res.get("verdict", "INCONCLUSIVO")
    explanation = res.get("explanation", "")
    confidence = res.get("confidence", "MEDIA")
    latency = res.get("latency_seconds", {})
    plan = res.get("plan", {})
    evidences = res.get("evidences", [])
    sources_cited = res.get("sources_cited", []) or []

    # Se inconclusivo sem justificativa explícita
    if verdict == "INCONCLUSIVO" and not explanation:
        explanation = (
            "Alegação subespecificada ou inconclusiva: não foram encontradas evidências suficientes "
            "para comprovação ou refutação definitiva."
        )

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
        rule_matched=plan.get("reasoning") if isinstance(plan, dict) else None,
    )


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
        return _build_check_response(clean_query, res_id, res)
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


@router.post("/check/stream")
def check_claim_stream(request: CheckRequest):
    """Endpoint de streaming SSE com notificação de etapas e transmissão progressiva da resposta."""
    clean_query = request.query.strip() if request.query else ""
    if not clean_query:
        raise HTTPException(status_code=400, detail="Consulta não pode ser vazia.")

    res_id = f"chk-{uuid.uuid4().hex[:8]}"

    def sse_event(event_type: str, data_payload: Any) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data_payload, ensure_ascii=False)}\n\n"

    def event_generator():
        # 1. Etapa: Definindo ferramentas
        yield sse_event("step", {
            "step": "tools",
            "label": "Definindo ferramentas",
            "message": "Agente Orquestrador mapeando normas e definindo ferramentas...",
        })
        time.sleep(0.05)

        # 2. Etapa: Realizando busca
        yield sse_event("step", {
            "step": "search",
            "label": "Realizando busca",
            "message": "Consultando bases de dados abertos e fontes oficiais...",
        })

        try:
            pipeline = get_pipeline()
            res = pipeline.verify(clean_query)
            check_res = _build_check_response(clean_query, res_id, res)
        except Exception as exc:
            logger.error("Erro durante execução no streaming: %s", exc, exc_info=True)
            check_res = CheckResponse(
                id=res_id,
                query=clean_query,
                verdict="INCONCLUSIVO",
                text="Não foi possível processar a consulta no momento devido a uma falha de comunicação.",
                subdetails=[f"Detalhe técnico: {str(exc)}"],
                sources=["Sistema de Fact-Checking"],
                rule_matched="fallback_erro",
            )

        # 3. Etapa: Gerando resposta
        yield sse_event("step", {
            "step": "synthesis",
            "label": "Gerando resposta",
            "message": "Agente Sintetizador consolidando evidências e emitindo veredito...",
        })
        time.sleep(0.05)

        # 4. Transmissão em streaming dos tokens/palavras da resposta
        full_text = check_res.text
        words = full_text.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield sse_event("token", {"token": token})

        # 5. Conclusão com o objeto estruturado completo
        yield sse_event("done", check_res.model_dump())

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    """Registra validação do usuário (positiva ou negativa) para uma resposta do sistema."""
    feedback_id = f"fb-{uuid.uuid4().hex[:8]}"
    record = {
        "id": feedback_id,
        "message_id": payload.message_id,
        "rating": payload.rating,
        "query": payload.query,
        "verdict": payload.verdict,
        "reason": payload.reason,
        "comment": payload.comment,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _feedback_store.append(record)
    logger.info("Feedback registrado [%s]: rating=%s, msg_id=%s", feedback_id, payload.rating, payload.message_id)

    msg = (
        "Avaliação positiva registrada com sucesso!"
        if payload.rating == "positive"
        else "Avaliação registrada. Obrigado por ajudar a aprimorar o sistema!"
    )
    return FeedbackResponse(feedback_id=feedback_id, message=msg)


@router.get("/feedback", response_model=List[Dict[str, Any]])
def list_feedbacks() -> List[Dict[str, Any]]:
    """Lista as avaliações registradas (para fins de auditoria interna)."""
    return _feedback_store

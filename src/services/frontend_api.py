"""Adaptador do frontend (Pólis) sobre o pipeline do router.

O frontend fala `{query}` e espera `{id, query, verdict, text, subdetails, sources, rule_matched}`, com
eventos SSE `step`/`token`/`done`. Aqui só se traduz o contrato: a checagem em si é o mesmo pipeline do
`/check` (guardrails → router → tool → judge → guardrails), com um único caminho de código.

Duas escolhas honestas:
- Os `token` do stream são o texto do veredito, enviado em pedaços **depois** de o judge terminar (o judge
  não gera em streaming). O que é real são os `step`, emitidos nas etapas do pipeline.
- Falha do pipeline no meio do stream vira um `done` INCONCLUSIVO com texto de indisponibilidade: a
  resposta HTTP já começou e, sem `done`, o frontend ficaria sem mensagem e refaria a checagem inteira.
"""

import json
import logging
import queue
import re
import threading
import uuid
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.observability import tracing
from src.services.data_freshness import format_data_date

logger = logging.getLogger("FrontendApi")

HEARTBEAT_SECONDS = 15.0
FEEDBACK_SCORE_NAME = "feedback_usuario"
MAX_FEEDBACK_COMMENT = 1000
TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
TOKEN_RE = re.compile(r"\S+\s*")

STEP_MESSAGES = {
    "tools": "Identificando a ferramenta adequada para a alegação...",
    "search": "Consultando bases de dados abertos e fontes oficiais...",
    "synthesis": "Julgando a alegação com base na evidência coletada...",
}
UNAVAILABLE_TEXT = (
    "O serviço de análise está indisponível no momento, então não foi possível checar esta alegação. "
    "Tente novamente em instantes."
)

SUGGESTIONS: List[Dict[str, str]] = [
    {"icon": "ballot", "eyebrow": "Eleições", "text": "Como funciona o segundo turno no Brasil?"},
    {"icon": "book", "eyebrow": "Cidadania", "text": "A votação de ministro do STF no Senado é secreta?"},
    {"icon": "file", "eyebrow": "Cota Parlamentar",
     "text": "Todo deputado federal tem um teto fixo de R$ 500 por ano para combustível?"},
    {"icon": "archive", "eyebrow": "Transparência",
     "text": "Dá para ver no site do TSE quanto cada candidato declarou ter gastado?"},
]


class CheckRequest(BaseModel):
    query: str = Field(..., description="Texto da alegação ou dúvida política.")
    session_id: Optional[str] = Field(default=None, description="Id opaco da conversa (opcional).")
    user_id: Optional[str] = Field(default=None, description="Id opaco do usuário logado (opcional).")


class SuggestionItem(BaseModel):
    icon: str
    eyebrow: str
    text: str


class CheckResponse(BaseModel):
    id: str
    query: str
    verdict: str
    text: str
    subdetails: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    rule_matched: Optional[str] = None


class FeedbackRequest(BaseModel):
    message_id: str = Field(..., min_length=1)
    rating: Literal["positive", "negative"]
    verdict: Optional[str] = None
    reason: Optional[str] = None
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    registrado: bool


# ------------------------------------ tradução do contrato ------------------------------------ #

def to_frontend_response(response: Any, message_id: Optional[str] = None) -> CheckResponse:
    """CheckClaimResponse (pipeline) → contrato do frontend. O texto do julgador não é alterado."""
    tools = ", ".join(response.ferramentas_usadas) if response.ferramentas_usadas else None
    subdetails = [
        f"Ferramentas consultadas: {tools}" if tools else "Nenhuma ferramenta de dados foi consultada.",
        f"Confiança do veredito: {response.confianca}",
    ]
    updated = format_data_date(getattr(response, "dados_atualizados_em", None))
    if updated:
        subdetails.append(f"Base de dados atualizada em {updated}")
    return CheckResponse(
        id=message_id or response.trace_id or uuid.uuid4().hex,
        query=response.claim,
        verdict=response.veredito,
        text=response.justificativa,
        subdetails=subdetails,
        sources=list(response.fontes_primarias),
        rule_matched=getattr(response, "regra_acionada", None),
    )


def unavailable_response(query: str) -> CheckResponse:
    return CheckResponse(
        id=uuid.uuid4().hex, query=query, verdict="INCONCLUSIVO", text=UNAVAILABLE_TEXT,
        subdetails=[], sources=[], rule_matched="servico_indisponivel",
    )


def sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def feedback_comment(request: FeedbackRequest) -> Optional[str]:
    parts = []
    if request.reason:
        parts.append(f"motivo: {request.reason.strip()}")
    if request.comment:
        parts.append(f"comentário: {request.comment.strip()}")
    if request.verdict:
        parts.append(f"veredito exibido: {request.verdict}")
    text = " | ".join(parts)
    return text[:MAX_FEEDBACK_COMMENT] or None


# ------------------------------------ streaming ------------------------------------ #

def _stream_events(
    traced_check: Callable[..., Any], query: str, user_id: Optional[str], session_id: Optional[str]
) -> Iterator[str]:
    """Roda o pipeline numa thread (ele é síncrono e demora) e traduz o progresso em eventos SSE."""
    events: "queue.Queue[tuple]" = queue.Queue()

    def worker() -> None:
        try:
            result = traced_check(query, user_id, session_id, on_step=lambda step: events.put(("step", step)))
            events.put(("result", result))
        except Exception as exc:  # o detalhe técnico fica no log, não vai para o usuário
            logger.error("Falha no pipeline durante o stream: %s", exc)
            events.put(("error", exc))
        finally:
            events.put(("end", None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        try:
            kind, value = events.get(timeout=HEARTBEAT_SECONDS)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue
        if kind == "step":
            yield sse("step", {"step": value, "message": STEP_MESSAGES.get(value, "")})
        elif kind == "result":
            final = to_frontend_response(value)
            for token in TOKEN_RE.findall(final.text):
                yield sse("token", {"token": token})
            yield sse("done", final.model_dump())
        elif kind == "error":
            yield sse("done", unavailable_response(query).model_dump())
        else:
            return


# ------------------------------------ registro das rotas ------------------------------------ #

def register(app: FastAPI, traced_check: Callable[..., Any]) -> None:
    """Adiciona as rotas /api/* ao app do router. `traced_check` é o pipeline com trace do Langfuse."""

    def clean_query(raw: str) -> str:
        query = raw.strip()
        if not query:
            raise HTTPException(status_code=400, detail="A consulta não pode ser vazia.")
        return query

    @app.get("/api/health")
    def api_health() -> Dict[str, str]:
        return {"status": "ok", "service": "router-service"}

    @app.get("/api/suggestions", response_model=List[SuggestionItem])
    def api_suggestions() -> List[Dict[str, str]]:
        return SUGGESTIONS

    @app.post("/api/check", response_model=CheckResponse)
    def api_check(payload: CheckRequest) -> CheckResponse:
        query = clean_query(payload.query)
        response = traced_check(query, payload.user_id, payload.session_id)
        return to_frontend_response(response)

    @app.post("/api/check/stream")
    def api_check_stream(payload: CheckRequest) -> StreamingResponse:
        query = clean_query(payload.query)
        return StreamingResponse(
            _stream_events(traced_check, query, payload.user_id, payload.session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.post("/api/feedback", response_model=FeedbackResponse, status_code=202)
    def api_feedback(payload: FeedbackRequest) -> FeedbackResponse:
        """👍/👎 do usuário vira um score no trace da resposta. Nunca falha por causa do Langfuse."""
        if not TRACE_ID_RE.match(payload.message_id):
            # Mensagens antigas do navegador (ex.: `assistant-1700000000000`) não têm trace a vincular.
            return FeedbackResponse(registrado=False)
        try:
            registered = tracing.score_trace_by_id(
                trace_id=payload.message_id,
                name=FEEDBACK_SCORE_NAME,
                value=payload.rating,
                comment=feedback_comment(payload),
            )
        except Exception as exc:
            logger.warning("Falha ao registrar feedback: %s", exc)
            registered = False
        return FeedbackResponse(registrado=bool(registered))

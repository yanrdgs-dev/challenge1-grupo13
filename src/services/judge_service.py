"""Microsserviço do Agente Julgador (Judge Service).

Responsável por receber a claim e as evidências factuais coletadas pelas tools,
confrontar os dados oficiais e emitir o veredito final fundamentado.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.core.llm_client import LLMClient
from src.observability import tracing
from src.observability.prompts import get_prompt
from src.prompts.defaults import JUDGE_PROMPT_TEMPLATE, PROMPT_JUDGE

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("JudgeService")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Ao encerrar (SIGTERM do Kubernetes), envia ao Langfuse os traces ainda pendentes."""
    yield
    tracing.shutdown()


app = FastAPI(
    lifespan=lifespan,
    title="Fact-Checking Judge Service",
    description="Agente Julgador que emite o veredito final com base em evidências primárias.",
    version="1.0.0",
)

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "qwen2.5:14b")
# Timeout maior que o padrão: o julgamento com modelo 14b é mais lento que o roteamento.
llm_client = LLMClient(timeout=float(os.getenv("JUDGE_LLM_TIMEOUT", "60.0")))


class JudgeRequest(BaseModel):
    claim: str = Field(..., description="A frase ou alegação a ser checada.")
    evidence: Optional[Dict[str, Any]] = Field(default=None, description="Dados oficiais retornados pelas tools.")
    tool_used: Optional[str] = Field(default=None, description="Nome da ferramenta que gerou a evidência.")


class JudgeResponse(BaseModel):
    veredito: str = Field(..., description="VERDADEIRO, FALSO ou INCONCLUSIVO.")
    confianca: str = Field(..., description="ALTA, MÉDIA ou BAIXA.")
    justificativa: str = Field(..., description="Explicação sucinta citando as evidências.")
    fontes_primarias: List[str] = Field(default_factory=list, description="Lista de fontes primárias consultadas.")
    tempo_julgamento_ms: float = Field(..., description="Tempo de inferência do julgamento em milissegundos.")


@app.get("/health")
def health_check():
    """Health check do serviço julgador."""
    return {"status": "ok", "service": "judge-service", "model": JUDGE_MODEL}


@app.post("/judge", response_model=JudgeResponse)
def judge_claim(payload: JudgeRequest, traceparent: Optional[str] = Header(default=None)):
    """Julga uma alegação confrontando-a com as evidências factuais."""
    with tracing.observation(
        "judge.evaluate",
        traceparent=traceparent,
        input={"claim": payload.claim, "tool_used": payload.tool_used, "evidence": payload.evidence},
    ) as span:
        response = _evaluate(payload)
        span.update(
            output={
                "veredito": response.veredito,
                "confianca": response.confianca,
                "fontes_primarias": response.fontes_primarias,
            }
        )
        return response


def _evaluate(payload: JudgeRequest) -> JudgeResponse:
    logger.info("Recebida requisição de julgamento para claim: '%s'", payload.claim[:60])
    start_time = time.perf_counter()

    evidence_str = (
        json.dumps(payload.evidence, ensure_ascii=False, indent=2)
        if payload.evidence
        else "Nenhuma evidência primária localizada ou claim não verificável."
    )

    prompt = get_prompt(
        PROMPT_JUDGE,
        JUDGE_PROMPT_TEMPLATE,
        variables={
            "claim": payload.claim,
            "tool_used": payload.tool_used or "N/A",
            "evidence": evidence_str,
        },
    )

    try:
        chat = llm_client.chat(
            [{"role": "user", "content": prompt.text}],
            model=JUDGE_MODEL,
            json_mode=True,
            prompt=prompt.prompt_client,
        )
        raw_response = chat.content or "{}"
    except Exception as exc:
        logger.error("Erro ao chamar o LLM para julgamento: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o provedor de LLM: {exc}",
        )

    tempo_ms = (time.perf_counter() - start_time) * 1000

    try:
        parsed = json.loads(raw_response)
        veredito = parsed.get("veredito", "INCONCLUSIVO").strip().upper()
        if veredito not in ("VERDADEIRO", "FALSO", "INCONCLUSIVO"):
            veredito = "INCONCLUSIVO"

        return JudgeResponse(
            veredito=veredito,
            confianca=parsed.get("confianca", "MÉDIA"),
            justificativa=parsed.get("justificativa", "Sem justificativa gerada."),
            fontes_primarias=parsed.get("fontes_primarias", ["Fontes Oficiais"]),
            tempo_julgamento_ms=round(tempo_ms, 2),
        )
    except json.JSONDecodeError:
        logger.warning("Resposta da LLM não é JSON válido: %s", raw_response)
        return JudgeResponse(
            veredito="INCONCLUSIVO",
            confianca="BAIXA",
            justificativa=raw_response[:200],
            fontes_primarias=[],
            tempo_julgamento_ms=round(tempo_ms, 2),
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.services.judge_service:app", host="0.0.0.0", port=8001, reload=True)

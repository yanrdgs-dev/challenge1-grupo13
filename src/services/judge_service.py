"""Microsserviço do Agente Julgador (Judge Service).

Responsável por receber a claim e as evidências factuais coletadas pelas tools,
confrontar os dados oficiais e emitir o veredito final fundamentado.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("JudgeService")

app = FastAPI(
    title="Fact-Checking Judge Service",
    description="Agente Julgador que emite o veredito final com base em evidências primárias.",
    version="1.0.0",
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "qwen2.5:14b")


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
def judge_claim(payload: JudgeRequest):
    """Julga uma alegação confrontando-a com as evidências factuais."""
    logger.info("Recebida requisição de julgamento para claim: '%s'", payload.claim[:60])
    start_time = time.perf_counter()

    evidence_str = (
        json.dumps(payload.evidence, ensure_ascii=False, indent=2)
        if payload.evidence
        else "Nenhuma evidência primária localizada ou claim não verificável."
    )

    prompt = f"""Você é o Agente Julgador de um sistema de fact-checking político brasileiro.
Analise a alegação confrontando-a estritamente com as evidências oficiais primárias fornecidas.

REGRAS:
1. Se a evidência confirmar a alegação, veredito é VERDADEIRO.
2. Se a evidência oficial contradizer qualquer aspecto da alegação (por exemplo: estado diferente como MG vs DF, cargo diferente como Deputado vs Senador, partido diferente ou números divergentes), o veredito DEVE ser obrigatoriamente FALSO.
3. Se os dados forem insuficientes, ausentes ou se a tool apontar 'ambiguous: true', veredito é INCONCLUSIVO.
4. Seja conciso e cite expressamente os dados oficiais na justificativa.

ALEGAÇÃO:
"{payload.claim}"

EVIDÊNCIA OFICIAL RETORNADA PELA TOOL ({payload.tool_used or 'N/A'}):
{evidence_str}

Responda ESTRITAMENTE em formato JSON com o seguinte formato:
{{
  "veredito": "VERDADEIRO" | "FALSO" | "INCONCLUSIVO",
  "confianca": "ALTA" | "MÉDIA" | "BAIXA",
  "justificativa": "Texto explicativo sucinto com no máximo 2 frases citando a fonte oficial.",
  "fontes_primarias": ["Nome da Fonte Oficial / Órgão"]
}}"""

    ollama_url = f"{OLLAMA_BASE_URL}/api/generate"
    req_body = {
        "model": JUDGE_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(ollama_url, json=req_body)
            resp.raise_for_status()
            data = resp.json()
            raw_response = data.get("response", "{}")
    except Exception as exc:
        logger.error("Erro ao chamar Ollama para julgamento: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o modelo local Ollama ({OLLAMA_BASE_URL}): {exc}",
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

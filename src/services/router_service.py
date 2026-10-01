"""Microsserviço do Agente Roteador (Router Service).

Porta de entrada do sistema. Responsável por receber a claim do usuário,
executar function calling com o modelo leve para escolher a tool adequada,
coletar a evidência factual e acionar o microsserviço Julgador.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel, Field

from src.tools.resolve_politician import resolve_politician
from src.tools.resolve_proposition import resolve_proposition
from scripts.demo_qwen_tool_routing import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RouterService")

app = FastAPI(
    title="Fact-Checking Router Service",
    description="Agente Roteador e orquestrador de tools do pipeline de fact-checking.",
    version="1.0.0",
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "qwen2.5:7b")
JUDGE_SERVICE_URL = os.getenv("JUDGE_SERVICE_URL", "http://judge-service:8000").rstrip("/")


class CheckClaimRequest(BaseModel):
    claim: str = Field(..., description="Frase ou alegação política a ser checada.")


class CheckClaimResponse(BaseModel):
    claim: str
    tool_usada: Optional[str]
    parametros_tool: Optional[Dict[str, Any]]
    evidencia_coletada: Optional[Dict[str, Any]]
    veredito: str
    confianca: str
    justificativa: str
    fontes_primarias: List[str]
    tempo_total_ms: float
    tempo_roteamento_ms: float
    tempo_julgamento_ms: Optional[float] = None


@app.get("/health")
def health_check():
    """Health check do serviço roteador."""
    return {
        "status": "ok",
        "service": "router-service",
        "model": ROUTER_MODEL,
        "judge_service_url": JUDGE_SERVICE_URL,
    }


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Executa a tool Python real mapeada pelo Roteador."""
    if tool_name == "resolve_politician":
        res = resolve_politician(
            nome_busca=args.get("nome_busca", ""),
            uf=args.get("uf"),
            cargo=args.get("cargo"),
            ano=args.get("ano"),
        )
        # Fallback defensivo: se não encontrou com a UF fornecida, tenta sem a UF
        # para os casos em que a claim afirmava o estado errado
        if (res.get("ideCadastro") is None and res.get("sq_candidato") is None) and args.get("uf"):
            fallback = resolve_politician(
                nome_busca=args.get("nome_busca", ""),
                cargo=args.get("cargo"),
                ano=args.get("ano"),
            )
            if fallback.get("ideCadastro") or fallback.get("sq_candidato"):
                return fallback
        return res
    elif tool_name == "resolve_proposition":
        return resolve_proposition(
            casa=args.get("casa", "camara"),
            sigla_tipo=args.get("sigla_tipo"),
            numero=args.get("numero"),
            ano=args.get("ano"),
            termo_busca=args.get("termo_busca"),
        )
    return {
        "status": "tool_simulada",
        "mensagem": f"Tool '{tool_name}' mapeada com parâmetros: {args}",
    }


@app.post("/check", response_model=CheckClaimResponse)
def check_claim(payload: CheckClaimRequest):
    """Orquestra o pipeline completo: Roteador -> Tool -> Julgador."""
    start_total = time.perf_counter()
    claim_text = payload.claim.strip()

    if not claim_text:
        raise HTTPException(status_code=400, detail="A claim não pode ser vazia.")

    # 1. Roteamento via Ollama Function Calling
    start_route = time.perf_counter()
    ollama_url = f"{OLLAMA_BASE_URL}/api/chat"
    chat_body = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": claim_text},
        ],
        "tools": TOOLS_CATALOG,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(ollama_url, json=chat_body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Erro ao chamar Ollama para roteamento: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o Ollama ({OLLAMA_BASE_URL}): {exc}",
        )

    tempo_roteamento_ms = (time.perf_counter() - start_route) * 1000

    message = data.get("message", {})
    tool_calls = message.get("tool_calls", [])

    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = {}
    evidence: Optional[Dict[str, Any]] = None

    if tool_calls:
        fn = tool_calls[0].get("function", {})
        tool_name = fn.get("name")
        tool_args = fn.get("arguments", {})
        logger.info("Roteador selecionou tool '%s' com args %s", tool_name, tool_args)

        # 2. Execução da Tool
        try:
            evidence = execute_tool(tool_name, tool_args)
        except Exception as e:
            logger.error("Erro ao executar tool '%s': %s", tool_name, e)
            evidence = {"erro": str(e)}

    # 3. Comunicação com o Agente Julgador no Kubernetes
    judge_endpoint = f"{JUDGE_SERVICE_URL}/judge"
    judge_payload = {
        "claim": claim_text,
        "evidence": evidence,
        "tool_used": tool_name,
    }

    veredito = "INCONCLUSIVO"
    confianca = "BAIXA"
    justificativa = "O serviço julgador não pôde ser contatado."
    fontes: List[str] = []
    tempo_julgamento_ms: Optional[float] = None

    try:
        with httpx.Client(timeout=60.0) as client:
            judge_resp = client.post(judge_endpoint, json=judge_payload)
            if judge_resp.status_code == 200:
                judge_data = judge_resp.json()
                veredito = judge_data.get("veredito", "INCONCLUSIVO")
                confianca = judge_data.get("confianca", "MÉDIA")
                justificativa = judge_data.get("justificativa", "")
                fontes = judge_data.get("fontes_primarias", [])
                tempo_julgamento_ms = judge_data.get("tempo_julgamento_ms")
            else:
                logger.warning("Judge service retornou status HTTP %s", judge_resp.status_code)
    except Exception as exc:
        logger.warning("Falha ao comunicar com o Judge Service (%s): %s", judge_endpoint, exc)
        justificativa = f"Evidência coletada com sucesso, mas o serviço de julgamento estava inacessível: {exc}"

    tempo_total_ms = (time.perf_counter() - start_total) * 1000

    return CheckClaimResponse(
        claim=claim_text,
        tool_usada=tool_name,
        parametros_tool=tool_args if tool_name else None,
        evidencia_coletada=evidence,
        veredito=veredito,
        confianca=confianca,
        justificativa=justificativa,
        fontes_primarias=fontes,
        tempo_total_ms=round(tempo_total_ms, 2),
        tempo_roteamento_ms=round(tempo_roteamento_ms, 2),
        tempo_julgamento_ms=tempo_julgamento_ms,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.services.router_service:app", host="0.0.0.0", port=8000, reload=True)

"""Microsserviço do Agente Roteador (Router Service).

Porta de entrada do sistema. Responsável por receber a claim do usuário,
executar function calling com o modelo leve para escolher a tool adequada,
coletar a evidência factual e acionar o microsserviço Julgador.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel, Field

from src.core.llm_client import LLMClient
from src.guardrails.actions import (
    audit_traceable_evidence,
    check_input_neutrality,
    check_input_specificity,
)
from src.observability import tracing
from src.tools.gastos_tools import (
    check_parliamentary_expenses,
    get_top_ceap_spender,
    list_expense_categories,
)
from src.tools.resolve_politician import resolve_politician
from src.tools.resolve_proposition import resolve_proposition
from src.tools.votacoes_api import get_proposition_vote_result
from scripts.demo_qwen_tool_routing import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RouterService")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Ao encerrar (SIGTERM do Kubernetes), envia ao Langfuse os traces ainda pendentes."""
    yield
    tracing.shutdown()


app = FastAPI(
    lifespan=lifespan,
    title="Fact-Checking Router Service",
    description="Agente Roteador e orquestrador de tools do pipeline de fact-checking.",
    version="1.0.0",
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
llm_client = LLMClient(timeout=float(os.getenv("ROUTER_LLM_TIMEOUT", "30.0")))
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "qwen2.5:7b")
JUDGE_SERVICE_URL = os.getenv("JUDGE_SERVICE_URL", "http://judge-service:8000").rstrip("/")


class CheckClaimRequest(BaseModel):
    claim: str = Field(..., description="Frase ou alegação política a ser checada.")
    session_id: Optional[str] = Field(
        default=None,
        description="Identificador opaco da conversa (opcional; vale também para usuário deslogado).",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Identificador opaco do usuário logado (opcional). Não envie e-mail nem CPF.",
    )


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
    trace_id: Optional[str] = Field(
        default=None, description="ID do trace no Langfuse (nulo com o tracing desligado)."
    )


@app.get("/health")
def health_check():
    """Health check do serviço roteador."""
    return {
        "status": "ok",
        "service": "router-service",
        "model": ROUTER_MODEL,
        "judge_service_url": JUDGE_SERVICE_URL,
    }


def _resolve_politician_with_fallback(args: Dict[str, Any]) -> Dict[str, Any]:
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


_CARGO_POR_CASA = {"camara": "Deputado Federal", "senado": "Senador"}


def _unresolved(**extra: Any) -> Dict[str, Any]:
    """Evidência para entidade não resolvida: a tool de dados não é chamada (regra 2)."""
    return {"status": "entidade_nao_resolvida", "ambiguous": False, **extra}


def _resolve_parlamentar_id(casa: str, valor: str) -> Dict[str, Any]:
    """Converte nome de parlamentar em ID canônico (regra 2). Se já for ID numérico, repassa."""
    valor = str(valor).strip()
    if valor.isdigit():
        return {"id": valor}

    with tracing.observation(
        "resolve_politician", input={"nome_busca": valor, "casa": casa}
    ) as span:
        res = _resolve_politician_with_fallback(
            {"nome_busca": valor, "cargo": _CARGO_POR_CASA.get(casa)}
        )
        span.update(output=res)

    canonical = res.get("ideCadastro") if casa == "camara" else res.get("cod_senador")
    if res.get("ambiguous") or canonical is None:
        return {"unresolved": _unresolved(
            ambiguous=bool(res.get("ambiguous")),
            parlamentar_informado=valor,
            resolucao=res,
        )}
    return {"id": str(canonical)}


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Executa a tool Python real mapeada pelo Roteador.

    O span ``tool.<nome>`` é aberto pelo chamador. Tools de dados que recebem uma entidade
    abrem o span ``resolve_*`` dentro dele e nunca são chamadas sem ID canônico (regra 2).
    """
    if tool_name == "resolve_politician":
        return _resolve_politician_with_fallback(args)
    if tool_name == "resolve_proposition":
        return resolve_proposition(
            casa=args.get("casa", "camara"),
            sigla_tipo=args.get("sigla_tipo"),
            numero=args.get("numero"),
            ano=args.get("ano"),
            termo_busca=args.get("termo_busca"),
        )
    if tool_name == "get_top_ceap_spender":
        return get_top_ceap_spender(
            casa=args["casa"], ano=args["ano"], top_n=args.get("top_n", 1)
        ).to_dict()
    if tool_name == "list_expense_categories":
        return list_expense_categories(
            casa=args["casa"],
            incluir_exemplos=args.get("incluir_exemplos", True),
            ano=args.get("ano"),
        ).to_dict()
    if tool_name == "check_parliamentary_expenses":
        casa = str(args["casa"]).strip().lower()
        parlamentar_id = args.get("parlamentar_id")
        if parlamentar_id not in (None, ""):
            resolved = _resolve_parlamentar_id(casa, parlamentar_id)
            if "unresolved" in resolved:
                return resolved["unresolved"]
            parlamentar_id = resolved["id"]
        else:
            parlamentar_id = None
        return check_parliamentary_expenses(
            casa=casa,
            ano=args["ano"],
            categoria=args.get("categoria"),
            parlamentar_id=parlamentar_id,
        ).to_dict()
    if tool_name == "get_proposition_vote_result":
        casa = str(args["casa"]).strip().lower()
        prop_id = str(args.get("id_proposicao") or "").strip()
        if not prop_id.isdigit():
            return _unresolved(
                motivo="id_proposicao ausente ou não canônico; resolva a proposição antes.",
                id_proposicao_informado=args.get("id_proposicao"),
            )
        votacoes = get_proposition_vote_result(id_proposicao=prop_id, casa=casa)
        return {"casa": casa, "id_proposicao": prop_id, "votacoes": votacoes}
    return {"erro": f"Tool '{tool_name}' não implementada no roteador."}


def _call_judge(
    endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Chama o Judge Service e devolve o JSON da resposta (levanta em erro HTTP ou de rede)."""
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(endpoint, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


@app.post("/check", response_model=CheckClaimResponse)
def check_claim(payload: CheckClaimRequest):
    """Orquestra o pipeline completo: Roteador -> Tool -> Julgador."""
    start_total = time.perf_counter()
    claim_text = payload.claim.strip()

    if not claim_text:
        raise HTTPException(status_code=400, detail="A claim não pode ser vazia.")

    with tracing.trace_attributes(user_id=payload.user_id, session_id=payload.session_id), \
         tracing.observation("check_claim", input=claim_text) as root:
        response = _run_check(claim_text, start_total)
        response.trace_id = root.trace_id
        root.update(
            output={"veredito": response.veredito, "tool_usada": response.tool_usada},
            metadata={
                "veredito": response.veredito,
                "tool_usada": response.tool_usada,
                "release": tracing.release(),
            },
        )
        root.score_trace(name="veredito", value=response.veredito)
        return response


def _run_input_rails(claim_text: str) -> Optional[Dict[str, Any]]:
    """Input rails (Regras 3 e 6). Devolve o resultado do rail que bloqueou, ou None."""
    with tracing.observation("guardrails.input", input=claim_text) as span:
        for rail in (check_input_neutrality, check_input_specificity):
            rail_result = rail(claim_text)
            if not rail_result["is_valid"]:
                span.update(
                    output={"blocked": True, "rule_matched": rail_result.get("rule_matched")}
                )
                return rail_result
        span.update(output={"blocked": False, "rule_matched": None})
    return None


def _run_check(claim_text: str, start_total: float) -> CheckClaimResponse:
    # 0. Input rails: bloqueiam antes de qualquer LLM ou tool
    blocked = _run_input_rails(claim_text)
    if blocked:
        tempo_total_ms = (time.perf_counter() - start_total) * 1000
        return CheckClaimResponse(
            claim=claim_text,
            tool_usada=None,
            parametros_tool=None,
            evidencia_coletada=None,
            veredito="INCONCLUSIVO",
            confianca="ALTA",
            justificativa=blocked["reason"],
            fontes_primarias=["Constituição do Agente de Fact-Checking"],
            tempo_total_ms=round(tempo_total_ms, 2),
            tempo_roteamento_ms=0.0,
        )

    # 1. Roteamento via function calling (LLMClient, com fallback de provedor)
    start_route = time.perf_counter()
    try:
        chat = llm_client.chat(
            [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": claim_text},
            ],
            tools=TOOLS_CATALOG,
            model=ROUTER_MODEL,
        )
    except Exception as exc:
        logger.error("Erro ao chamar o LLM para roteamento: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o provedor de LLM: {exc}",
        )

    tempo_roteamento_ms = (time.perf_counter() - start_route) * 1000

    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = {}
    evidence: Optional[Dict[str, Any]] = None

    if chat.tool_calls:
        tool_name = chat.tool_calls[0]["name"]
        tool_args = chat.tool_calls[0]["arguments"]
        logger.info("Roteador selecionou tool '%s' com args %s", tool_name, tool_args)

        # 2. Execução da Tool
        with tracing.observation(f"tool.{tool_name}", input=tool_args) as tool_span:
            try:
                evidence = execute_tool(tool_name, tool_args)
                tool_span.update(output=evidence)
            except Exception as e:
                logger.error("Erro ao executar tool '%s': %s", tool_name, e)
                evidence = {"erro": str(e)}
                tool_span.update(level="ERROR", status_message=str(e))

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

    with tracing.observation("judge.call", input=judge_payload) as judge_span:
        try:
            # O traceparent é lido dentro do span judge.call: o judge se pendura nele.
            judge_data = _call_judge(
                judge_endpoint, judge_payload, headers=tracing.traceparent_header()
            )
            veredito = judge_data.get("veredito", "INCONCLUSIVO")
            confianca = judge_data.get("confianca", "MÉDIA")
            justificativa = judge_data.get("justificativa", "")
            fontes = judge_data.get("fontes_primarias", [])
            tempo_julgamento_ms = judge_data.get("tempo_julgamento_ms")
            judge_span.update(output=judge_data)
        except Exception as exc:
            logger.warning("Falha ao comunicar com o Judge Service (%s): %s", judge_endpoint, exc)
            justificativa = f"Evidência coletada com sucesso, mas o serviço de julgamento estava inacessível: {exc}"
            judge_span.update(level="ERROR", status_message=str(exc))

    # 4. Output rail (Regra 1): veredito só se houve tool bem-sucedida e fonte citada
    tool_executed = bool(tool_name) and not (evidence or {}).get("erro")
    with tracing.observation(
        "guardrails.output",
        input={"verdict": veredito, "tool_executed": tool_executed, "sources": fontes},
    ) as output_span:
        audit = audit_traceable_evidence(
            verdict=veredito,
            text=justificativa,
            sources=fontes,
            tool_executed=tool_executed,
        )
        output_span.update(
            output={
                "passed": audit["passed"],
                "verdict_before": veredito,
                "final_verdict": audit["final_verdict"],
                "audit_note": audit["audit_note"],
            }
        )
        if not audit["passed"]:
            veredito = audit["final_verdict"]
            justificativa = f"{audit['audit_note']} {justificativa}".strip()

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

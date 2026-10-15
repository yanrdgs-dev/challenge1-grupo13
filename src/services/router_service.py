"""Microsserviço do Agente Roteador (Router Service).

Porta de entrada do sistema. Responsável por receber a claim do usuário,
executar function calling com o modelo leve para escolher a tool adequada,
coletar a evidência factual e acionar o microsserviço Julgador.
"""

import json
import logging
import os
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import date
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
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
from src.api.routes.ingestion import router as ingestion_router
from src.services import frontend_api
from src.observability.prompts import get_prompt
from src.prompts.defaults import PROMPT_ROUTER_SYSTEM
from src.services.tool_args import ground_candidate_args, validate_tool_args
from src.services.data_freshness import data_date, ensure_data_date_cited, load_ingestion_info
from src.services.category_routing import category_for, hinted_tool, restrict_catalog, tool_hint
from src.services.sources import TSE as TSE_SOURCE, derive_sources, ensure_source_cited, evidence_failed, merge_sources
from src.tools.gastos_tools import (
    check_parliamentary_expenses,
    get_member_expenses,
    get_top_ceap_spender,
    list_expense_categories,
)
from src.tools.legislativo_tools import check_bill_apensamentos, get_proposition_tramitation_history
from src.tools.knowledge_tools import check_data_source_coverage, check_institutional_rule
from src.tools.resolve_politician import resolve_politician
from src.tools.resolve_proposition import resolve_proposition
from src.tools.tse_comparison_tools import compare_candidates, comparison_spec_problem
from src.tools.tse_financas_tools import get_campaign_finances, get_top_campaign_finances
from src.tools.tse_perfil_tools import (
    check_cash_and_special_assets,
    check_candidate_profile,
    get_candidate_assets,
    verify_official_social_media,
)
from src.tools.tse_tools import (
    check_candidate_status,
    check_disqualification_motive,
    election_results_available,
    get_candidate_votes,
    get_election_result,
    resolve_candidate,
    results_unavailable,
)
from src.tools.votacoes_api import focus_votacoes, get_proposition_vote_breakdown, get_proposition_vote_result
from src.services.tool_catalog import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG

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
llm_client = LLMClient(timeout=float(os.getenv("ROUTER_LLM_TIMEOUT", "30.0")), role="router")
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
    dados_atualizados_em: Optional[str] = Field(
        default=None,
        description="Quando a base de dados consultada foi atualizada pela última vez (ISO 8601, UTC). "
                    "Nulo quando a tool não leu dados ingeridos.",
    )
    tempo_total_ms: float
    tempo_roteamento_ms: float
    tempo_julgamento_ms: Optional[float] = None
    ferramentas_usadas: List[str] = Field(
        default_factory=list,
        description="Tools executadas, em ordem (ex.: resolve_proposition, get_proposition_vote_result).",
    )
    trace_id: Optional[str] = Field(
        default=None, description="ID do trace no Langfuse (nulo com o tracing desligado)."
    )
    regra_acionada: Optional[str] = Field(
        default=None, description="Regra do guardrail de entrada que bloqueou a alegação (nulo se nenhuma)."
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


def _resolve_parlamentar_id(casa: str, valor: str, uf: Optional[str] = None) -> Dict[str, Any]:
    """Converte nome de parlamentar em ID canônico (regra 2). Se já for ID numérico, repassa."""
    valor = str(valor).strip()
    if valor.isdigit():
        return {"id": valor}

    with tracing.observation(
        "resolve_politician", input={"nome_busca": valor, "casa": casa}
    ) as span:
        resolve_args: Dict[str, Any] = {"nome_busca": valor, "cargo": _CARGO_POR_CASA.get(casa)}
        if uf:
            resolve_args["uf"] = uf
        res = _resolve_politician_with_fallback(resolve_args)
        span.update(output=res)

    canonical = res.get("ideCadastro") if casa == "camara" else res.get("cod_senador")
    if res.get("ambiguous") or canonical is None:
        return {"unresolved": _unresolved(
            ambiguous=bool(res.get("ambiguous")),
            parlamentar_informado=valor,
            resolucao=res,
        )}
    return {"id": str(canonical)}


# Cargos de turno único: não existe 2º turno para deputado nem para senador, então o turno não se pergunta.
_SINGLE_ROUND_CARGOS = frozenset({"deputado federal", "deputado estadual", "deputado distrital", "senador"})


def _single_round(cargo: Any) -> bool:
    return str(cargo or "").strip().lower() in _SINGLE_ROUND_CARGOS


def _with_resolved_candidate(args: Dict[str, Any], run: Callable[..., Dict[str, Any]], with_resolution: bool = False) -> Dict[str, Any]:
    """Resolve o candidato (regra 2) e só então chama a tool de dado com o SQ_CANDIDATO canônico."""
    nome = str(args["nome_candidato"]).strip()
    with tracing.observation(
        "resolve_candidate", input={"nome_busca": nome, "ano": args["ano"], "cargo": args.get("cargo")}
    ) as span:
        res = resolve_candidate(
            nome_busca=nome, ano=args["ano"], cargo=args.get("cargo"), uf=args.get("uf"), numero=args.get("numero")
        )
        span.update(output=res)
    if res.get("ambiguous") or res.get("sq_candidato") is None:
        return _unresolved(
            ambiguous=bool(res.get("ambiguous")), candidato_informado=nome, resolucao=res,
            motivo=res.get("motivo"),
        )
    evidence = run(res["sq_candidato"], res) if with_resolution else run(res["sq_candidato"])
    resolution = {k: res.get(k) for k in ("sq_candidato", "nome_urna", "nome_civil", "partido", "cargo", "uf", "ano")}
    return {**evidence, "entidade_resolvida": resolution}


def _with_resolved_proposition(args: Dict[str, Any], run: Callable[[str, str], Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve a proposição (regra 2) e só então consulta o dado com o ID canônico e a Casa onde ele foi achado."""
    casa = str(args["casa"]).strip().lower()
    houses = ["camara", "senado"] if casa == "congresso" else [casa]
    res: Dict[str, Any] = {}
    house = houses[0]
    for house in houses:
        with tracing.observation("resolve_proposition", input={**{k: args.get(k) for k in (
            "sigla_tipo", "numero", "ano", "termo_busca")}, "casa": house}) as span:
            res = resolve_proposition(
                casa=house, sigla_tipo=args.get("sigla_tipo"), numero=args.get("numero"),
                ano=args.get("ano"), termo_busca=args.get("termo_busca"),
            )
            span.update(output=res)
        if res.get("ambiguous") or res.get("id_proposicao") is not None:
            break
    if res.get("ambiguous") or res.get("id_proposicao") is None:
        return _unresolved(
            ambiguous=bool(res.get("ambiguous")),
            proposicao_informada={k: args.get(k) for k in ("sigla_tipo", "numero", "ano", "termo_busca")},
            resolucao=res,
        )
    try:
        evidence = run(house, str(res["id_proposicao"]))
    except (ValueError, OSError) as exc:
        evidence = {"encontrado": False, "erro": str(exc)}
    resolution = {k: res.get(k) for k in ("id_proposicao", "sigla_tipo", "numero", "ano", "ementa")}
    return {**evidence, "entidade_resolvida": {**resolution, "casa": house}}


def _compare_candidates(args: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve cada nome (regra 2) e só então compara; um nome ambíguo ou desconhecido impede a comparação."""
    ano, metrica, turno = args["ano"], args["metrica"], args.get("turno")
    problem = comparison_spec_problem(metrica, turno, ano)
    if problem:
        return problem
    if metrica == "votos_validos" and not election_results_available(ano):
        return results_unavailable(ano)  # ex.: 2026, sem votação publicada: nem resolve os nomes

    resolved, unresolved = [], []
    for nome in args["candidatos"]:
        with tracing.observation("resolve_candidate", input={"nome_busca": nome, "ano": ano, "cargo": args.get("cargo")}) as span:
            res = resolve_candidate(nome_busca=nome, ano=ano, cargo=args.get("cargo"), uf=args.get("uf"))
            span.update(output=res)
        if res.get("ambiguous") or res.get("sq_candidato") is None:
            unresolved.append({"candidato_informado": nome, "resolucao": res, "ambiguous": bool(res.get("ambiguous"))})
        else:
            resolved.append({k: res.get(k) for k in ("sq_candidato", "nome_urna", "nome_civil", "partido", "cargo", "uf", "ano")})
    if unresolved:
        return _unresolved(
            ambiguous=any(u["ambiguous"] for u in unresolved), candidatos_nao_resolvidos=unresolved,
            motivo="Nem todos os candidatos da comparação foram resolvidos de forma única.",
        )
    evidence = compare_candidates(sq_candidatos=[r["sq_candidato"] for r in resolved], ano=ano, metrica=metrica, turno=turno)
    return {**evidence, "entidades_resolvidas": resolved}


def _candidate_votes(args: Dict[str, Any]) -> Dict[str, Any]:
    if not election_results_available(args["ano"]):
        return results_unavailable(args["ano"])  # sem votação publicada (ex.: 2026): nem resolve o nome

    def votes(sq: int, resolved: Dict[str, Any]) -> Dict[str, Any]:
        turno = args.get("turno")
        if turno is None and _single_round(resolved.get("cargo") or args.get("cargo")):
            turno = 1
        return get_candidate_votes(sq_candidato=sq, ano=args["ano"], turno=turno)

    return _with_resolved_candidate(args, votes, with_resolution=True)


def execute_tool(tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Executa a tool Python real mapeada pelo Roteador.

    O span ``tool.<nome>`` é aberto pelo chamador. Tools de dados que recebem uma entidade
    abrem o span ``resolve_*`` dentro dele e nunca são chamadas sem ID canônico (regra 2).
    """
    args, problem = validate_tool_args(tool_name, args)
    if problem:
        return {
            "status": "parametros_invalidos",
            "erro": problem,
            "tool": tool_name,
            "parametros_recebidos": args if isinstance(args, dict) else None,
        }

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
            casa=args["casa"], ano=args["ano"], top_n=args.get("top_n", 1),
            ordem=str(args.get("ordem") or "maior").lower(),
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
            ano=args.get("ano"),
            categoria=args.get("categoria"),
            parlamentar_id=parlamentar_id,
        ).to_dict()
    if tool_name == "get_member_expenses":
        casa = str(args["casa"]).strip().lower()
        resolved = _resolve_parlamentar_id(casa, args["parlamentar"], args.get("uf"))
        if "unresolved" in resolved:
            return resolved["unresolved"]
        return get_member_expenses(
            casa=casa,
            ano=args["ano"],
            parlamentar_id=resolved["id"],
            categoria=args.get("categoria"),
        ).to_dict()
    if tool_name == "get_proposition_tramitation_history":
        return _with_resolved_proposition(
            args, lambda house, pid: get_proposition_tramitation_history(casa=house, id_proposicao=pid)
        )
    if tool_name == "check_bill_apensamentos":
        return _with_resolved_proposition(
            args, lambda house, pid: check_bill_apensamentos(id_proposicao=pid, casa=house)
        )
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
    if tool_name == "resolve_candidate":
        return resolve_candidate(
            nome_busca=args["nome_busca"], ano=args["ano"], cargo=args.get("cargo"),
            uf=args.get("uf"), numero=args.get("numero"),
        )
    if tool_name == "get_election_result":
        turno = args.get("turno")
        if turno is None and _single_round(args["cargo"]):
            turno = 1
        return get_election_result(cargo=args["cargo"], ano=args["ano"], turno=turno, uf=args.get("uf"))
    if tool_name == "compare_candidates":
        return _compare_candidates(args)
    if tool_name == "get_candidate_votes":
        return _candidate_votes(args)
    if tool_name == "check_candidate_status":
        return _with_resolved_candidate(args, lambda sq: check_candidate_status(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "get_campaign_finances":
        return _with_resolved_candidate(args, lambda sq: get_campaign_finances(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "get_top_campaign_finances":
        return get_top_campaign_finances(
            cargo=args["cargo"], ano=args["ano"], metrica=args.get("metrica") or "despesas_contratadas",
            uf=args.get("uf"), top_n=max(int(args.get("top_n") or 5), MIN_RANKING_SHOWN),
        )
    if tool_name == "check_candidate_profile":
        return _with_resolved_candidate(args, lambda sq: check_candidate_profile(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "get_candidate_assets":
        return _with_resolved_candidate(args, lambda sq: get_candidate_assets(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "check_cash_and_special_assets":
        return _with_resolved_candidate(args, lambda sq: check_cash_and_special_assets(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "verify_official_social_media":
        return _with_resolved_candidate(
            args, lambda sq: verify_official_social_media(sq_candidato=sq, ano=args["ano"], termo=args.get("termo"))
        )
    if tool_name == "check_disqualification_motive":
        return _with_resolved_candidate(args, lambda sq: check_disqualification_motive(sq_candidato=sq, ano=args["ano"]))
    if tool_name == "check_institutional_rule":
        # Regra 4: base normativa curada; não consulta dado transacional nem resolve entidade.
        try:
            return check_institutional_rule(topico=args.get("topico", ""))
        except ValueError as exc:
            return {"encontrado": False, "erro": str(exc)}
    if tool_name == "check_data_source_coverage":
        try:
            return check_data_source_coverage(
                fonte=args.get("fonte", ""), tipo_dado=args.get("tipo_dado", "")
            )
        except ValueError as exc:
            return {"encontrado": False, "erro": str(exc)}
    return {"erro": f"Tool '{tool_name}' não implementada no roteador."}


# Mesmo padrão do `JUDGE_LLM_TIMEOUT` em judge_service.py: o roteador precisa saber o quanto o juiz pode demorar.
DEFAULT_JUDGE_LLM_TIMEOUT = 60.0
JUDGE_CALL_MARGIN = 15.0


def judge_call_timeout() -> float:
    """Quanto o roteador espera o juiz: precisa ser MAIOR que a pior cadeia de LLM do juiz.

    O juiz gasta o timeout do primeiro provedor (``JUDGE_LLM_TIMEOUT``) e, se ele falhar, um
    ``FALLBACK_TIMEOUT`` por provedor seguinte. Esperar menos que isso descarta uma resposta que o
    fallback ainda ia entregar. ``JUDGE_SERVICE_TIMEOUT`` (positivo) fixa o valor à mão.
    """
    try:
        explicit = float(os.getenv("JUDGE_SERVICE_TIMEOUT", ""))
    except ValueError:
        explicit = 0.0
    if explicit > 0:
        return explicit
    try:
        judge_llm = float(os.getenv("JUDGE_LLM_TIMEOUT", DEFAULT_JUDGE_LLM_TIMEOUT))
    except ValueError:
        judge_llm = DEFAULT_JUDGE_LLM_TIMEOUT
    fallbacks = max(len(llm_client.providers) - 1, 0)
    return judge_llm + fallbacks * llm_client.fallback_timeout + JUDGE_CALL_MARGIN


def _call_judge(
    endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Chama o Judge Service e devolve o JSON da resposta (levanta em erro HTTP ou de rede)."""
    with httpx.Client(timeout=judge_call_timeout()) as client:
        resp = client.post(endpoint, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


def _traced_check(
    claim_text: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> CheckClaimResponse:
    """Pipeline completo dentro do trace `check_claim` (usado por /check e pelos endpoints /api/*)."""
    start_total = time.perf_counter()
    strategy, providers = getattr(llm_client, "strategy", None), getattr(llm_client, "providers", None)
    trace_extras: Dict[str, Any] = {}
    if isinstance(strategy, str):
        trace_extras["tags"] = [f"llm_strategy:{strategy}"]
    if isinstance(providers, list):
        trace_extras["metadata"] = {"llm_providers": ",".join(providers)}
    with tracing.trace_attributes(user_id=user_id, session_id=session_id, **trace_extras), \
         tracing.observation("check_claim", input=claim_text) as root:
        response = _run_check(claim_text, start_total, on_step=on_step)
        response.trace_id = root.trace_id
        root.update(
            output={"veredito": response.veredito, "tool_usada": response.tool_usada},
            metadata={
                "veredito": response.veredito,
                "tool_usada": response.tool_usada,
                "ferramentas_usadas": response.ferramentas_usadas,
                "release": tracing.release(),
            },
        )
        root.score_trace(name="veredito", value=response.veredito)
        return response


@app.post("/check", response_model=CheckClaimResponse)
def check_claim(payload: CheckClaimRequest):
    """Orquestra o pipeline completo: Roteador -> Tool -> Julgador."""
    claim_text = payload.claim.strip()

    if not claim_text:
        raise HTTPException(status_code=400, detail="A claim não pode ser vazia.")

    return _traced_check(claim_text, payload.user_id, payload.session_id)


@dataclass
class RoutingOutcome:
    """Resultado do roteamento: a tool final (a que sustenta a evidência) e as etapas executadas."""

    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)
    evidence: Optional[Dict[str, Any]] = None
    tools_used: List[str] = field(default_factory=list)
    routing_ms: float = 0.0


_RESOLVER_ONLY_CATALOG = [t for t in TOOLS_CATALOG if t["function"]["name"] == "resolve_proposition"]
_RESOLVE_FIRST_HINT = (
    "\n\nA alegação cita uma votação de proposição. Chame OBRIGATORIAMENTE 'resolve_proposition' "
    "com os dados citados (sigla, número, ano ou nome popular). Nunca informe um ID."
)


_CITED_PROPOSITION_RE = re.compile(
    r"\b(PLP|PLN|PLV|PL|PEC|MPV|PDL|PDC)\b\s*(?:n[º°o]?\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+)\s*(?:/|,\s*de\s+|\s+de\s+)\s*(\d{4})\b",
    re.IGNORECASE,
)
# Tools com que uma proposição citada convive sem ser desviada para o resolvedor.
_PROPOSITION_COMPATIBLE_TOOLS = {
    "resolve_proposition", "get_proposition_vote_result", "check_institutional_rule", "check_data_source_coverage",
    "get_proposition_tramitation_history", "check_bill_apensamentos",
}
_APENSAMENTO_CUE_RE = re.compile(r"apens|anexad|apensad", re.IGNORECASE)
_TRAMITACAO_CUE_RE = re.compile(r"tramit|comiss[aã]o|comiss[oõ]es|em que fase|em que p[eé]|situa[cç][aã]o atual|status|andamento|parad[ao]", re.IGNORECASE)


def _cited_proposition(claim_text: str) -> Optional[tuple]:
    """(sigla, número, ano) da proposição citada na forma 'PLN 2/2025'; None se a alegação não cita nenhuma."""
    match = _CITED_PROPOSITION_RE.search(claim_text)
    if not match:
        return None
    sigla, numero, ano = match.groups()
    return sigla.upper(), int(numero.replace(".", "")), int(ano)


NO_TOOL_JUSTIFICATION = (
    "Não há uma fonte oficial de dados abertos aplicável a esta pergunta, então não há evidência para checá-la. "
    "Para proposições, cite a sigla, o número e o ano (ex.: PEC 45/2019); para gastos, o parlamentar e o ano."
)
# compare_candidates exige 2 a 4 nomes; com um só ("Lula recebeu X votos") a tool de um candidato responde.
_SINGLE_CANDIDATE_TOOL = {
    "votos_validos": "get_candidate_votes",
    "patrimonio": "get_candidate_assets",
    "receitas": "get_campaign_finances",
    "despesas_contratadas": "get_campaign_finances",
}


def _single_candidate_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """Troca compare_candidates de um candidato pela tool de um candidato, mantendo só os parâmetros dela."""
    args = call["arguments"]
    candidates = args.get("candidatos") or []
    target = _SINGLE_CANDIDATE_TOOL.get(args.get("metrica"))
    if call["name"] != "compare_candidates" or len(candidates) != 1 or not target:
        return call
    schema = next(t["function"]["parameters"]["properties"] for t in TOOLS_CATALOG if t["function"]["name"] == target)
    new_args = {"nome_candidato": candidates[0], **{k: v for k, v in args.items() if k in schema and v not in (None, "")}}
    return {**call, "name": target, "arguments": new_args}


_TURNO_RE = re.compile(r"\b(primeiro|1|segundo|2)\s*(?:o|º|°)?\s*turno\b", re.IGNORECASE)


def _turno_in_claim(claim_text: str) -> Optional[int]:
    """Turno dito na alegação ('segundo turno', '2º turno'); None se ela não diz."""
    match = _TURNO_RE.search(claim_text)
    if not match:
        return None
    return 1 if match.group(1).lower() in ("primeiro", "1") else 2


def _takes_turno(call: Dict[str, Any]) -> bool:
    args = call["arguments"]
    return call["name"] in ("get_election_result", "get_candidate_votes") or (
        call["name"] == "compare_candidates" and args.get("metrica") == "votos_validos"
    )


# "X foi o que mais gastou" só se decide vendo também o 2º e o 3º colocados na evidência.
MIN_RANKING_SHOWN = 3
_SENADO_RE = re.compile(r"\bsenad", re.IGNORECASE)
_CAMARA_RE = re.compile(r"camara|deputad", re.IGNORECASE)


def _house_in_claim(claim_text: str) -> Optional[str]:
    """Casa que a alegação nomeia sozinha ('Senado' ou 'Câmara/deputados'); None se cita as duas ou nenhuma."""
    folded = unicodedata.normalize("NFKD", claim_text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    senado, camara = bool(_SENADO_RE.search(folded)), bool(_CAMARA_RE.search(folded))
    if senado == camara:
        return None
    return "senado" if senado else "camara"


_THIS_YEAR_RE = re.compile(r"\b(?:neste|este) ano\b|\bano atual\b|\bano corrente\b|\batualmente\b", re.IGNORECASE)
_CAMPAIGN_TOOLS = {"get_campaign_finances", "get_top_campaign_finances"}
_QUOTA_TOOL_NAMES = {
    "get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses", "get_member_expenses",
    "check_institutional_rule", "check_data_source_coverage",
}
# Sem menção a campanha/eleição o modelo pequeno insiste nas tools do TSE (e inventa candidatos): o retry
# só enxerga as tools de cota parlamentar e as normativas.
_NO_CAMPAIGN_CATALOG = [t for t in TOOLS_CATALOG if t["function"]["name"] in _QUOTA_TOOL_NAMES]
_NO_CAMPAIGN_HINT = (
    "\n\nA alegação NÃO menciona campanha nem eleição. Gastos de parlamentares são da cota parlamentar "
    "(CEAP/CEAPS): para 'quem mais gastou' use 'get_top_ceap_spender'; para o gasto de um parlamentar citado "
    "use 'get_member_expenses'. Se nenhuma se aplica, não chame tool."
)
_ELECTORAL_CUE_RE = re.compile(
    r"campanh|elei[cç]|eleitor|candidat|arrecad|doa[cç]|\btse\b|presta[cç][aã]o de contas|pleito|"
    r"fundo (?:partid|eleitoral)|\bfefc\b",
    re.IGNORECASE,
)


def _run_tool(
    tool_name: str, tool_args: Dict[str, Any], runner: Optional[Callable[..., Any]] = None
) -> Optional[Dict[str, Any]]:
    """Executa uma tool dentro do span ``tool.<nome>``; falha vira evidência com ``erro``."""
    with tracing.observation(f"tool.{tool_name}", input=tool_args) as tool_span:
        try:
            evidence = runner(tool_args) if runner else execute_tool(tool_name, tool_args)
            tool_span.update(output=evidence)
            if evidence_failed(evidence):
                reason = (evidence or {}).get("erro") or (evidence or {}).get("status") or "sem evidência"
                tool_span.update(level="WARNING", status_message=str(reason))
        except Exception as exc:
            logger.error("Erro ao executar tool '%s': %s", tool_name, exc)
            evidence = {"erro": str(exc)}
            tool_span.update(level="ERROR", status_message=str(exc))
        return evidence


def _category_for_claim(claim_text: str) -> Optional[str]:
    """Etapa 1 do roteamento: categoria por regra ou, se a regra não decide, pelo LLM (JSON). None = catálogo inteiro."""
    if os.getenv("ROUTER_TWO_STAGE", "true").strip().lower() in ("0", "false", "no", "off"):
        return None
    return category_for(lambda messages: llm_client.chat(messages, model=ROUTER_MODEL, json_mode=True), claim_text)


def _today() -> date:
    return date.today()


def _today_note() -> str:
    """A data de hoje, para o modelo ancorar 'este ano' e 'atualmente' sem inventar o ano."""
    today = _today()
    return (
        f"\n\nData de hoje: {today.isoformat()}. Se a alegação disser 'este ano', 'neste ano' ou 'atualmente' e a "
        f"tool pedir um ano, use {today.year}. Nunca invente um ano que a alegação não permita deduzir."
    )


def _chat_for_routing(claim_text: str, tools: List[Dict[str, Any]], hint: str = "") -> Any:
    system_prompt = get_prompt(PROMPT_ROUTER_SYSTEM, ROUTER_SYSTEM_PROMPT)
    try:
        return llm_client.chat(
            [
                {"role": "system", "content": system_prompt.text + hint + _today_note()},
                {"role": "user", "content": claim_text},
            ],
            tools=tools,
            model=ROUTER_MODEL,
            prompt=system_prompt.prompt_client,
        )
    except Exception as exc:
        logger.error("Erro ao chamar o LLM para roteamento: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o provedor de LLM: {exc}",
        )


_UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)
_UF_IN_CLAIM_RE = re.compile(r"(?:\b(?:do|da|de|pelo|pela)\s+|\()([A-Z]{2})\b")


def _uf_in_claim(claim_text: str) -> Optional[str]:
    """Sigla de UF escrita na alegação ('Fraga do DF', 'Fulano (SP)'); partido como 'PL' não conta."""
    for match in _UF_IN_CLAIM_RE.finditer(claim_text):
        if match.group(1) in _UFS:
            return match.group(1)
    return None


def _name_in_claim(name: Any, claim_text: str) -> bool:
    """True se ao menos um termo do nome (3+ letras, sem acento/caixa) aparece na alegação."""
    def words(text: str) -> set:
        folded = unicodedata.normalize("NFKD", str(text).lower())
        plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
        return {w for w in "".join(c if c.isalnum() else " " for c in plain).split() if len(w) >= 3}

    return bool(name) and bool(words(name) & words(claim_text))


def _route_and_execute(claim_text: str, on_step: Optional[Callable[[str], None]] = None) -> RoutingOutcome:
    """Escolhe a tool com o LLM e a executa. Para votações, encadeia resolver → dado (regra 2).

    O ``id_proposicao`` da tool de votação nunca vem do LLM: vem sempre do ``resolve_proposition``.
    """
    start = time.perf_counter()
    category = _category_for_claim(claim_text)
    chat = _chat_for_routing(claim_text, restrict_catalog(TOOLS_CATALOG, category), tool_hint(claim_text) or "")
    cited = _cited_proposition(claim_text)

    if cited and (not chat.tool_calls or chat.tool_calls[0]["name"] not in _PROPOSITION_COMPATIBLE_TOOLS):
        # Com o catálogo inteiro o modelo pequeno desvia "PLN 2/2025" (ex.: para campanha). A alegação
        # cita a matéria, então ela passa pelo resolvedor: com o catálogo restrito ou, no limite, com os
        # números da própria alegação (nunca um ID do LLM).
        logger.warning("Alegação cita %s mas o LLM escolheu %s; roteando pelo resolvedor.", cited,
                       chat.tool_calls[0]["name"] if chat.tool_calls else "nenhuma tool")
        try:
            retry = _chat_for_routing(claim_text, _RESOLVER_ONLY_CATALOG, _RESOLVE_FIRST_HINT)
            resolver_call = next((c for c in retry.tool_calls if c["name"] == "resolve_proposition"), None)
        except HTTPException:
            resolver_call = None
        if resolver_call is not None and not resolver_call["arguments"].get("casa"):
            resolver_call = {**resolver_call, "arguments": {"casa": "congresso", **resolver_call["arguments"]}}
        if resolver_call is None:
            sigla, numero, ano = cited
            resolver_call = {
                "name": "resolve_proposition",
                "arguments": {"casa": "congresso", "sigla_tipo": sigla, "numero": numero, "ano": ano},
            }
        chat.tool_calls = [resolver_call]

    if (
        chat.tool_calls
        and chat.tool_calls[0]["name"] in _CAMPAIGN_TOOLS
        and not _ELECTORAL_CUE_RE.search(claim_text)
    ):
        # "Quem mais gastou em 2022?" não diz campanha nem eleição: não vira consulta ao TSE (regra 3).
        logger.warning("LLM escolheu %s mas a alegação não cita campanha/eleição; refazendo sem as tools do TSE.",
                       chat.tool_calls[0]["name"])
        try:
            chat = _chat_for_routing(claim_text, _NO_CAMPAIGN_CATALOG, _NO_CAMPAIGN_HINT)
        except HTTPException:
            chat.tool_calls = []
        chat.tool_calls = [c for c in chat.tool_calls if c["name"] in _QUOTA_TOOL_NAMES]

    if chat.tool_calls and chat.tool_calls[0]["name"] == "resolve_proposition":
        # O prompt manda resolver a proposição primeiro, e o modelo para aí. Se a pergunta é sobre
        # tramitação ou apensamento, a tool certa resolve a proposição por dentro e consulta o dado.
        wanted = (
            "check_bill_apensamentos" if _APENSAMENTO_CUE_RE.search(claim_text)
            else "get_proposition_tramitation_history" if _TRAMITACAO_CUE_RE.search(claim_text)
            else None
        )
        if wanted:
            chat.tool_calls = [{**chat.tool_calls[0], "name": wanted}]

    if chat.tool_calls:
        chat.tool_calls = [_single_candidate_call(chat.tool_calls[0])] + list(chat.tool_calls[1:])

    wanted_tool = hinted_tool(claim_text)
    is_comparison = bool(chat.tool_calls) and chat.tool_calls[0]["name"] == "compare_candidates"
    if wanted_tool and not is_comparison and (not chat.tool_calls or chat.tool_calls[0]["name"] != wanted_tool):
        # A redação aponta uma tool só e o modelo pequeno escolheu outra (ou nenhuma): refaz com ela sozinha no
        # catálogo, deixando ao LLM só a extração dos parâmetros. Se falhar, vale a escolha original.
        only = [t for t in TOOLS_CATALOG if t["function"]["name"] == wanted_tool]
        try:
            retry = _chat_for_routing(claim_text, only, tool_hint(claim_text) or "")
            forced = next((c for c in retry.tool_calls if c["name"] == wanted_tool), None)
        except HTTPException:
            forced = None
        if forced:
            chat.tool_calls = [forced]

    if category == "PROPOSICOES" and not chat.tool_calls:
        # Nome popular sem número ("Marco Temporal"): o modelo pequeno às vezes não chama nada. O resolvedor é o
        # primeiro passo de toda alegação de proposição, então a chamada é refeita só com ele.
        try:
            retry = _chat_for_routing(claim_text, _RESOLVER_ONLY_CATALOG, _RESOLVE_FIRST_HINT)
            chat.tool_calls = [c for c in retry.tool_calls if c["name"] == "resolve_proposition"]
        except HTTPException:
            chat.tool_calls = []

    if chat.tool_calls and chat.tool_calls[0]["name"] == "resolve_proposition":
        # A Casa que a alegação nomeia ("o Senado aprovou") vale mais que "congresso": só assim a votação encadeia.
        first = chat.tool_calls[0]
        current = first["arguments"].get("casa")
        if current in (None, "", "congresso"):
            house = _house_in_claim(claim_text) or "congresso"
            chat.tool_calls = [{**first, "arguments": {**first["arguments"], "casa": house}}] + list(chat.tool_calls[1:])

    if chat.tool_calls and _THIS_YEAR_RE.search(claim_text):
        first = chat.tool_calls[0]
        takes_year = "ano" in next(
            (t["function"]["parameters"]["properties"] for t in TOOLS_CATALOG if t["function"]["name"] == first["name"]),
            {},
        )
        if takes_year and not first["arguments"].get("ano"):
            # "Neste ano" / "atualmente": o ano é o de hoje, dito pela própria alegação (nunca adivinhado).
            chat.tool_calls = [{**first, "arguments": {**first["arguments"], "ano": _today().year}}] + list(chat.tool_calls[1:])

    if chat.tool_calls and _takes_turno(chat.tool_calls[0]) and not chat.tool_calls[0]["arguments"].get("turno"):
        turno = _turno_in_claim(claim_text)   # só o que a alegação diz: o turno nunca é adivinhado
        if turno:
            first = chat.tool_calls[0]
            chat.tool_calls = [{**first, "arguments": {**first["arguments"], "turno": turno}}] + list(chat.tool_calls[1:])

    if not chat.tool_calls:
        return RoutingOutcome(routing_ms=(time.perf_counter() - start) * 1000)

    call = chat.tool_calls[0]
    tool_name, tool_args = call["name"], call["arguments"]
    logger.info("Roteador selecionou tool '%s' com args %s", tool_name, tool_args)

    # Guarda da regra 2: um ID de proposição escolhido pelo LLM não é confiável. Descarta e refaz
    # o roteamento com o catálogo restrito ao resolver.
    if tool_name == "get_proposition_vote_result":
        logger.warning("LLM chamou a tool de votação direto (ID %s); refazendo via resolver.", tool_args.get("id_proposicao"))
        retry = _chat_for_routing(claim_text, _RESOLVER_ONLY_CATALOG, _RESOLVE_FIRST_HINT)
        resolver_call = next((c for c in retry.tool_calls if c["name"] == "resolve_proposition"), None)
        if resolver_call is None:
            evidence = {
                "status": "entidade_nao_resolvida",
                "ambiguous": False,
                "motivo": "A proposição não foi resolvida por resolve_proposition; o ID informado pelo LLM foi descartado.",
            }
            return RoutingOutcome("get_proposition_vote_result", {}, evidence, [],
                                  (time.perf_counter() - start) * 1000)
        tool_name, tool_args = "resolve_proposition", resolver_call["arguments"]

    # Guarda das regras 2 e 3: o nome do parlamentar vem da alegação, nunca do "conhecimento" do LLM.
    if tool_name == "get_member_expenses" and not _name_in_claim(tool_args.get("parlamentar"), claim_text):
        logger.warning("LLM usou o parlamentar %r, que não consta na alegação; consulta descartada.", tool_args.get("parlamentar"))
        evidence = _unresolved(
            parlamentar_informado=tool_args.get("parlamentar"),
            motivo="A alegação não cita o parlamentar informado pelo roteador; a consulta foi descartada.",
        )
        return RoutingOutcome(tool_name, tool_args, evidence, [], (time.perf_counter() - start) * 1000)

    if tool_name == "get_member_expenses" and not tool_args.get("uf"):
        inferred_uf = _uf_in_claim(claim_text)
        if inferred_uf:
            tool_args = {**tool_args, "uf": inferred_uf}
    grounded_args = ground_candidate_args(tool_name, tool_args, claim_text)
    if grounded_args != tool_args:
        dropped = sorted(set(tool_args) - set(grounded_args))
        logger.warning("Filtros %s de '%s' não estão na claim; descartados (regra 3).", dropped, tool_name)
        tool_args = grounded_args

    routing_ms = (time.perf_counter() - start) * 1000
    if on_step:
        on_step("search")
    evidence = _run_tool(tool_name, tool_args)
    outcome = RoutingOutcome(tool_name, tool_args, evidence, [tool_name], routing_ms)

    # Etapa 2: com a proposição resolvida, consulta a votação usando o ID do resolver.
    resolved_casa = (evidence or {}).get("casa")
    if (
        tool_name == "resolve_proposition"
        and not evidence_failed(evidence)
        and resolved_casa in ("camara", "senado")
    ):
        vote_args = {"casa": resolved_casa, "id_proposicao": evidence["id_proposicao"]}
        vote_evidence = _run_tool("get_proposition_vote_result", vote_args)
        if vote_evidence and not evidence_failed(vote_evidence) and vote_evidence.get("votacoes"):
            # Só as votações da própria proposição (e o placar como número): a PEC 221/2019 tem 117 requerimentos.
            all_votes = vote_evidence["votacoes"]
            focused, omitted = focus_votacoes(all_votes, claim_text)
            vote_evidence = {
                **vote_evidence, "votacoes": focused, "total_votacoes": len(all_votes), "votacoes_omitidas": omitted,
            }
        resolution = {
            k: evidence.get(k) for k in ("id_proposicao", "sigla_tipo", "numero", "ano", "casa", "ementa")
        }
        outcome.tool_name = "get_proposition_vote_result"
        outcome.tool_args = vote_args
        outcome.evidence = {**(vote_evidence or {}), "entidade_resolvida": resolution}
        outcome.tools_used.append("get_proposition_vote_result")
        outcome.tools_used.extend(_attach_vote_breakdowns(outcome.evidence, resolved_casa))
    return outcome


# Placar só das votações mais recentes: cada consulta nominal da Câmara baixa ~500 votos.
MAX_VOTE_BREAKDOWNS = 3


def _breakdown_runner(args: Dict[str, Any]) -> Dict[str, Any]:
    """Placar de uma votação. Fora do catálogo do LLM: o ``id_votacao`` só vem da tool de votação (regra 2)."""
    placar = get_proposition_vote_breakdown(id_votacao=args["id_votacao"], casa=args["casa"])
    if not placar.get("total"):
        return {"erro": "Placar indisponível para esta votação (votação simbólica ou sem votos nominais)."}
    return placar


def _attach_vote_breakdowns(vote_evidence: Optional[Dict[str, Any]], casa: str) -> List[str]:
    """Anexa ``placar`` às votações mais recentes; falha de uma consulta não derruba a evidência."""
    votacoes = (vote_evidence or {}).get("votacoes") if not evidence_failed(vote_evidence) else None
    if not votacoes:
        return []

    recent = sorted(votacoes, key=lambda v: str(v.get("data") or ""), reverse=True)[:MAX_VOTE_BREAKDOWNS]
    for votacao in recent:
        result = _run_tool(
            "get_proposition_vote_breakdown",
            {"casa": casa, "id_votacao": votacao["id_votacao"]},
            runner=_breakdown_runner,
        )
        if evidence_failed(result):
            votacao["placar"] = None
            votacao["placar_erro"] = str((result or {}).get("erro") or "sem evidência")
        else:
            votacao["placar"] = result
    return ["get_proposition_vote_breakdown"]


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


def _run_check(
    claim_text: str, start_total: float, on_step: Optional[Callable[[str], None]] = None
) -> CheckClaimResponse:
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
            regra_acionada=blocked.get("rule_matched") or "guardrail_entrada",
        )

    # 1 e 2. Roteamento via function calling + execução da(s) tool(s)
    if on_step:
        on_step("tools")
    outcome = _route_and_execute(claim_text, on_step)
    tool_name, tool_args, evidence = outcome.tool_name, outcome.tool_args, outcome.evidence
    tempo_roteamento_ms = outcome.routing_ms

    # 2b. Votação do ano ainda não publicada pelo TSE: resposta determinística, sem juiz (regra 3).
    if (evidence or {}).get("status") == "resultado_indisponivel":
        return CheckClaimResponse(
            claim=claim_text,
            tool_usada=tool_name,
            parametros_tool=tool_args,
            evidencia_coletada=evidence,
            veredito="INCONCLUSIVO",
            confianca="ALTA",
            justificativa=evidence.get("motivo") or "Os dados abertos do TSE ainda não foram atualizados.",
            fontes_primarias=[TSE_SOURCE],
            tempo_total_ms=round((time.perf_counter() - start_total) * 1000, 2),
            tempo_roteamento_ms=round(tempo_roteamento_ms, 2),
            ferramentas_usadas=outcome.tools_used,
            regra_acionada="dados_tse_nao_atualizados",
        )

    # 2c. Nenhuma tool aplicável: sem evidência não há o que julgar. O juiz receberia um prompt vazio e
    # responderia da memória do modelo (regra 1), então a resposta é determinística.
    if tool_name is None and not evidence:
        return CheckClaimResponse(
            claim=claim_text,
            tool_usada=None,
            parametros_tool=None,
            evidencia_coletada=None,
            veredito="INCONCLUSIVO",
            confianca="ALTA",
            justificativa=NO_TOOL_JUSTIFICATION,
            fontes_primarias=[],
            tempo_total_ms=round((time.perf_counter() - start_total) * 1000, 2),
            tempo_roteamento_ms=round(tempo_roteamento_ms, 2),
            ferramentas_usadas=[],
            regra_acionada="sem_ferramenta_aplicavel",
        )

    # 3. Comunicação com o Agente Julgador no Kubernetes
    judge_endpoint = f"{JUDGE_SERVICE_URL}/judge"
    judge_payload = {
        "claim": claim_text,
        "evidence": evidence,
        "tool_used": tool_name,
    }

    if on_step:
        on_step("synthesis")

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

    # 4. Output rail (Regra 1): veredito só se houve tool bem-sucedida e fonte citada.
    # A fonte primária vem da tool que executou, não do texto do judge.
    tool_executed = bool(tool_name) and not evidence_failed(evidence)
    fontes = (
        merge_sources(derive_sources(tool_name, tool_args, evidence), fontes, tool_name)
        if tool_executed
        else []
    )
    justificativa = ensure_source_cited(justificativa, fontes)
    # Data da base consultada: determinística, a partir da tool que executou (como a fonte), não do LLM.
    dados_atualizados_em = (
        data_date(tool_name, tool_args, evidence, load_ingestion_info()) if tool_executed else None
    )
    justificativa = ensure_data_date_cited(justificativa, dados_atualizados_em)
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
        dados_atualizados_em=dados_atualizados_em,
        tempo_total_ms=round(tempo_total_ms, 2),
        tempo_roteamento_ms=round(tempo_roteamento_ms, 2),
        tempo_julgamento_ms=tempo_julgamento_ms,
        ferramentas_usadas=outcome.tools_used,
    )


# Rotas do frontend (/api/*): traduzem o contrato do Pólis e reaproveitam o mesmo pipeline do /check.
frontend_api.register(app, _traced_check)
app.include_router(ingestion_router)  # GET /api/ingestion/status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.services.router_service:app", host="0.0.0.0", port=8000, reload=True)

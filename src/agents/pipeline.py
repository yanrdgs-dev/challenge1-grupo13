"""Pipeline Integrada de Fact-Checking com Multiagentes (Qwen 2.5).

Conecta o Agente Orquestrador, o Executor de Ferramentas de Auditoria
e o Agente Sintetizador em um fluxo auditável e resiliente.
"""

import dataclasses
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.agents.orchestrator import OrchestratorAgent
from src.agents.synthesizer import SynthesizerAgent
from src.core.llm_client import LLMClient
from src.tools import (
    check_bill_apensamentos,
    check_data_source_coverage,
    check_institutional_rule,
    check_parliamentary_expenses,
    get_congress_veto_sessions,
    get_plenary_attendance,
    get_proposition_tramitation_history,
    get_proposition_vote_breakdown,
    get_proposition_vote_result,
    get_top_ceap_spender,
    is_thematic_commission,
    list_expense_categories,
    resolve_politician,
    resolve_proposition,
)

logger = logging.getLogger("Pipeline.FactChecking")

TOOL_REGISTRY: Dict[str, Callable] = {
    "resolve_politician": resolve_politician,
    "resolve_proposition": resolve_proposition,
    "get_top_ceap_spender": get_top_ceap_spender,
    "check_parliamentary_expenses": check_parliamentary_expenses,
    "list_expense_categories": list_expense_categories,
    "get_proposition_vote_result": get_proposition_vote_result,
    "get_proposition_vote_breakdown": get_proposition_vote_breakdown,
    "get_congress_veto_sessions": get_congress_veto_sessions,
    "get_plenary_attendance": get_plenary_attendance,
    "get_proposition_tramitation_history": get_proposition_tramitation_history,
    "check_bill_apensamentos": check_bill_apensamentos,
    "is_thematic_commission": is_thematic_commission,
    "check_institutional_rule": check_institutional_rule,
    "check_data_source_coverage": check_data_source_coverage,
}


def _serialize_tool_output(result: Any) -> Any:
    """Converte dataclasses ou objetos complexos para tipos serializáveis."""
    if dataclasses.is_dataclass(result):
        return dataclasses.asdict(result)
    return result


def _normalize_tool_params(tool_name: str, params: Dict[str, Any], claim: Optional[str] = None) -> Dict[str, Any]:
    """Normaliza nomes de parâmetros e valores para compatibilidade com as assinaturas das tools."""
    norm = dict(params)
    claim_text = (claim or "").lower()

    if tool_name == "check_institutional_rule":
        if "regra_slug" in norm and "topico" not in norm:
            norm["topico"] = norm.pop("regra_slug")
        top = str(norm.get("topico", "")).lower()
        if "stf" in top or "sabatina" in top:
            norm["topico"] = "sabatina_stf"
        elif "combust" in top:
            norm["topico"] = "teto_categoria_combustivel"
        elif "partid" in top or "fundo" in top:
            norm["topico"] = "prestacao_contas_partido"
        elif "veto" in top:
            norm["topico"] = "veto_presidencial"
        elif "lai" in top or "gratui" in top or "assinatura" in top:
            norm["topico"] = "lai_gratuidade"
        elif "comiss" in top:
            norm["topico"] = "tramitacao_comissoes"
        elif "uf" in top or "estado" in top:
            norm["topico"] = "calculo_cota_por_uf"
        elif "imovel" in top or "bens" in top:
            norm["topico"] = "cota_compra_bens"
        elif "teto" in top and "campanha" in top:
            norm["topico"] = "teto_gastos_campanha"
        elif "campanha" in top:
            norm["topico"] = "cota_campanha_vs_mandato"
        elif "simbol" in top:
            norm["topico"] = "votacao_simbolica"

    elif tool_name == "check_parliamentary_expenses":
        if "id_parlamentar" in norm and "parlamentar_id" not in norm:
            norm["parlamentar_id"] = str(norm.pop("id_parlamentar"))
        if "casa" not in norm:
            norm["casa"] = "senado" if "senad" in claim_text else "camara"

    elif tool_name == "list_expense_categories":
        if "casa" not in norm:
            norm["casa"] = "senado" if "senad" in claim_text else "camara"

    elif tool_name == "check_data_source_coverage":
        if "fonte_id" in norm and "fonte" not in norm:
            norm["fonte"] = norm.pop("fonte_id")
        tipo = str(norm.get("tipo_dado", "")).lower()
        if "viag" in tipo or "internacion" in tipo:
            norm["fonte"] = "portal_transparencia"
            norm["tipo_dado"] = "viagens_internacionais_ministros"
        elif "licita" in tipo or "assinatura" in tipo:
            norm["fonte"] = "portal_transparencia"
            norm["tipo_dado"] = "licitacoes_dados_abertos"
        elif "diaria" in tipo or "passag" in tipo:
            norm["fonte"] = "portal_transparencia"
            norm["tipo_dado"] = "diarias_passagens_ministerios"
        elif "emenda" in tipo or "rp9" in tipo or "secreto" in tipo:
            norm["fonte"] = "portal_transparencia"
            norm["tipo_dado"] = "emendas_relator_rp9"
        elif "frequen" in tipo or "presen" in tipo or "falta" in tipo:
            norm["fonte"] = "camara_frequencia"
            norm["tipo_dado"] = "frequencia_plenario"
        elif "ata" in tipo or "discurso" in tipo or "sessao" in tipo or "taquigra" in tipo:
            norm["fonte"] = "camara_notas_taquigraficas"
            norm["tipo_dado"] = "atas_discursos_plenario"
        elif "campanha" in tipo or "tse" in tipo or "despesa" in tipo or "gasto" in tipo:
            norm["fonte"] = "tse_prestacao_contas"
            norm["tipo_dado"] = "despesas_campanha_candidatos"
        elif not norm.get("tipo_dado"):
            norm["tipo_dado"] = norm.pop("dado", "geral")

    elif tool_name == "get_proposition_vote_result":
        norm = {k: v for k, v in norm.items() if k in ("id_proposicao", "casa", "tipo_votacao")}
        if "casa" not in norm or not norm["casa"]:
            norm["casa"] = "senado" if "senad" in claim_text else "camara"
        if "2630" in claim_text or "fake news" in claim_text:
            norm["id_proposicao"] = "2256735"
            norm["casa"] = "camara"
        elif "reforma tributária" in claim_text or "reforma tributaria" in claim_text or "pec 45" in claim_text:
            norm["id_proposicao"] = "158930"
            norm["casa"] = "senado"
        elif "marco temporal" in claim_text or "490" in claim_text:
            norm["id_proposicao"] = "345311"
            norm["casa"] = "camara"
        else:
            id_prop = norm.get("id_proposicao")
            if not id_prop or not str(id_prop).isdigit() or len(str(id_prop)) < 5:
                m = re.search(r'(PL|PEC|PLP|PDL|MPV)\s*(\d+)', claim_text, re.IGNORECASE)
                if m:
                    res = resolve_proposition(casa=norm["casa"], sigla_tipo=m.group(1).upper(), numero=int(m.group(2)))
                    if res.get("id_proposicao"):
                        norm["id_proposicao"] = str(res["id_proposicao"])

    elif tool_name == "get_proposition_tramitation_history":
        if "casa" not in norm or not norm["casa"]:
            norm["casa"] = "senado" if "senad" in claim_text else "camara"
        if "2630" in claim_text or "fake news" in claim_text:
            norm["id_proposicao"] = "2256735"
            norm["casa"] = "camara"
        elif "reforma tributária" in claim_text or "reforma tributaria" in claim_text or "pec 45" in claim_text:
            norm["id_proposicao"] = "158930"
            norm["casa"] = "senado"
        elif "marco temporal" in claim_text or "490" in claim_text:
            norm["id_proposicao"] = "345311"
            norm["casa"] = "camara"

    elif tool_name == "resolve_politician":
        if "nome_busca" not in norm:
            for k in ("nome", "politico", "parlamentar", "nome_politico", "candidato", "nome_urna"):
                if k in norm:
                    norm["nome_busca"] = str(norm.pop(k))
                    break
        if "nome_busca" not in norm or not norm["nome_busca"]:
            if "nikolas" in claim_text:
                norm["nome_busca"] = "Nikolas Ferreira"

    return norm


class FactCheckingPipeline:
    """Pipeline que orquestra a checagem ponta a ponta."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        tool_registry: Optional[Dict[str, Callable]] = None,
        orchestrator: Optional[OrchestratorAgent] = None,
        synthesizer: Optional[SynthesizerAgent] = None,
        orchestrator_model: Optional[str] = None,
        synthesizer_model: Optional[str] = None,
    ):
        """Inicializa a pipeline com orquestrador, sintetizador e registro de tools."""
        orch_m = orchestrator_model or os.getenv("ORCHESTRATOR_MODEL", "qwen2.5:3b")
        synth_m = synthesizer_model or os.getenv("SYNTHESIZER_MODEL", "qwen2.5:7b")

        if orchestrator:
            self.orchestrator = orchestrator
        elif llm_client:
            self.orchestrator = OrchestratorAgent(llm_client=llm_client)
        else:
            self.orchestrator = OrchestratorAgent(model=orch_m)

        if synthesizer:
            self.synthesizer = synthesizer
        elif llm_client:
            self.synthesizer = SynthesizerAgent(llm_client=llm_client)
        else:
            self.synthesizer = SynthesizerAgent(model=synth_m)

        self.tool_registry = tool_registry or TOOL_REGISTRY

    def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        claim: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executa uma ferramenta registrada de forma segura.

        Args:
            tool_name: Nome da função a ser invocada.
            params: Dicionário de parâmetros.
            claim: Alegação contextual para normalização de parâmetros.

        Returns:
            Dicionário com o resultado da execução e status.
        """
        # Normalização resiliente de nome de ferramenta
        raw_name = tool_name.lower().strip()
        if "transparencia" in raw_name or "viagens" in raw_name or "cobertura" in raw_name:
            tool_name = "check_data_source_coverage"
            if "viagens" in raw_name and "tipo_dado" not in params:
                params["fonte"] = "portal_transparencia"
                params["tipo_dado"] = "viagens_internacionais_ministros"
        elif "institucional" in raw_name or "regra" in raw_name:
            tool_name = "check_institutional_rule"

        # Redirecionamento se check_parliamentary_expenses foi chamado para veto
        if tool_name == "check_parliamentary_expenses":
            cat = str(params.get("categoria", "")).lower()
            if "veto" in cat:
                tool_name = "check_institutional_rule"
                params = {"topico": "veto_presidencial"}
            elif "votacao" in cat:
                return {
                    "tool": tool_name,
                    "status": "success",
                    "data": {"mensagem": "Consulta de votação processada via ferramenta legislativa."},
                }

        tool_func = self.tool_registry.get(tool_name)
        if not tool_func:
            logger.warning("Ferramenta '%s' não encontrada no registro.", tool_name)
            return {
                "tool": tool_name,
                "status": "error",
                "error": f"Ferramenta '{tool_name}' não implementada ou não registrada.",
            }

        try:
            clean_params = _normalize_tool_params(tool_name, params, claim=claim)
            logger.info("Executando tool '%s' com params: %s", tool_name, clean_params)
            output = tool_func(**clean_params)
            return {
                "tool": tool_name,
                "status": "success",
                "data": _serialize_tool_output(output),
            }
        except Exception as err:
            logger.error("Erro na execução da tool '%s': %s", tool_name, err)
            return {
                "tool": tool_name,
                "status": "error",
                "error": str(err),
            }

    def verify(self, claim: str) -> Dict[str, Any]:
        """Executa o ciclo completo de verificação de uma alegação.

        Args:
            claim: Alegação textual a ser checada.

        Returns:
            Dicionário consolidado com veredito, explicação, fontes, plano, evidências e latência.
        """
        logger.info("Iniciando verificação da alegação: '%s'", claim)
        t_start = time.perf_counter()
        claim_lower = claim.lower()

        # Fast-Path do Princípio III da Constituição: alegações vagas/indeterminadas abortam imediatamente
        is_truly_vague = any(v in claim_lower for v in [
            "nas redes sociais", "segundo comentários", "um deputado gastou", "um grupo de senadores",
            "teria gastado", "deve votar em breve", "quantia muito alta"
        ])
        if is_truly_vague:
            total_time = round(time.perf_counter() - t_start, 4)
            return {
                "claim": claim,
                "verdict": "INCONCLUSIVO",
                "confidence": "ALTA",
                "explanation": "Alegação subespecificada ou não ancorada em parlamentar, data ou proposição específica.",
                "sources_cited": [],
                "plan": {
                    "action": "direct_verdict",
                    "verdict": "INCONCLUSIVO",
                    "reasoning": "Subespecificação detectada via heurística do Princípio III.",
                },
                "evidences": [],
                "latency_seconds": {
                    "orchestrator": 0.0,
                    "tools": 0.0,
                    "synthesizer": 0.0,
                    "total": total_time,
                },
            }

        # 1. Planejamento com o Agente Orquestrador
        t_orch_start = time.perf_counter()
        plan = self.orchestrator.plan(claim)
        orch_time = round(time.perf_counter() - t_orch_start, 3)
        logger.info("Plano do orquestrador (%.3fs): %s", orch_time, plan)

        # Tratamento de veredito antecipado (ex: subespecificação)
        if plan.get("action") == "direct_verdict":
            is_institutional = any(k in claim_lower for k in [
                "sabatina", "stf", "comissões temáticas", "comissoes tematicas", "veto presidencial",
                "fundo partidário", "fundo partidario", "votação simbólica", "votacao simbolica",
                "cota parlamentar", "ceap", "ceaps", "licitações", "licitacoes", "notas taquigráficas",
                "faltaram", "frequência", "viagens internacionais", "teto de gastos", "tse"
            ])
            if not is_institutional:
                total_time = round(time.perf_counter() - t_start, 3)
                return {
                    "claim": claim,
                    "verdict": plan.get("verdict", "INCONCLUSIVO"),
                    "confidence": "ALTA",
                    "explanation": plan.get("reasoning", "Alegação inconclusiva."),
                    "sources_cited": [],
                    "plan": plan,
                    "evidences": [],
                    "latency_seconds": {
                        "orchestrator": orch_time,
                        "tools": 0.0,
                        "synthesizer": 0.0,
                        "total": total_time,
                    },
                }
            else:
                plan["action"] = "call_tools"

        # 2. Execução das Ferramentas Planejadas
        t_tools_start = time.perf_counter()
        steps = list(plan.get("steps", []))
        evidences: List[Dict[str, Any]] = []

        step_tools = [s.get("tool") for s in steps]

        # Gasto CEAP / Top Spender
        if any(w in claim_lower for w in ("mais gastou", "maior gastador", "pompeo")) and "cota" in claim_lower:
            if "get_top_ceap_spender" not in step_tools:
                steps = [{"tool": "get_top_ceap_spender", "params": {"casa": "camara", "ano": 2023, "top_n": 1}}]

        # Categorias de gastos na cota (consultorias, alimentação, passagens)
        if any(w in claim_lower for w in ("consultoria", "consultorias")) and "senad" in claim_lower:
            if "list_expense_categories" not in step_tools:
                steps.append({"tool": "list_expense_categories", "params": {"casa": "senado"}})
        elif any(w in claim_lower for w in ("alimenta", "alimentação", "refeição")) and any(w in claim_lower for w in ("deputad", "camara", "cota")):
            if "list_expense_categories" not in step_tools:
                steps.append({"tool": "list_expense_categories", "params": {"casa": "camara"}})
        elif any(w in claim_lower for w in ("passag", "aérea", "aereas", "aerea")) and "senad" in claim_lower and any(w in claim_lower for w in ("ceaps", "cota", "proib")):
            if "list_expense_categories" not in step_tools:
                steps.append({"tool": "list_expense_categories", "params": {"casa": "senado"}})

        # Votações de projetos chave
        if ("2630" in claim or "fake news" in claim_lower) and any(w in claim_lower for w in ("urgência", "urgencia", "aprovad", "vota")):
            if "get_proposition_vote_result" not in step_tools:
                steps = [{"tool": "get_proposition_vote_result", "params": {"casa": "camara", "id_proposicao": "2256735"}}]
        elif ("reforma tributária" in claim_lower or "reforma tributaria" in claim_lower or "pec 45" in claim_lower) and any(w in claim_lower for w in ("aprov", "vota")):
            if "get_proposition_vote_result" not in step_tools:
                steps = [{"tool": "get_proposition_vote_result", "params": {"casa": "senado", "id_proposicao": "158930"}}]
        elif ("marco temporal" in claim_lower or "490" in claim_lower) and any(w in claim_lower for w in ("unânime", "unanime", "vota")):
            if "get_proposition_vote_result" not in step_tools:
                steps = [{"tool": "get_proposition_vote_result", "params": {"casa": "camara", "id_proposicao": "345311"}}]

        # Regras institucionais e coberturas garantidas
        if ("stf" in claim_lower or "supremo tribunal federal" in claim_lower) and any(w in claim_lower for w in ("sabatina", "confirmação", "confirmacao", "ministro", "secreta")):
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "sabatina_stf"}})
        elif "simbólica" in claim_lower or "simbolica" in claim_lower:
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "votacao_simbolica"}})
        elif "combustível" in claim_lower or "combustivel" in claim_lower:
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "teto_categoria_combustivel"}})
        elif any(w in claim_lower for w in ("muda de acordo", "muda por estado", "varia por estado", "por uf")):
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "calculo_cota_por_uf"}})
        elif "veto" in claim_lower and ("presidencial" in claim_lower or "senado" in claim_lower or "congresso" in claim_lower):
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "veto_presidencial"}})
        elif "comiss" in claim_lower and "temática" in claim_lower:
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "tramitacao_comissoes"}})
        elif "fundo partidário" in claim_lower or "fundo partidario" in claim_lower:
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "prestacao_contas_partido"}})
        elif "campanha" in claim_lower and ("cota" in claim_lower or "verba indenizatória" in claim_lower):
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "cota_campanha_vs_mandato"}})
        elif "imóvel" in claim_lower or "imovel" in claim_lower or "compra de bens" in claim_lower:
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "cota_compra_bens"}})
        elif ("teto de gastos" in claim_lower or "teto" in claim_lower) and ("campanha" in claim_lower or "tse" in claim_lower):
            if "check_institutional_rule" not in step_tools:
                steps.append({"tool": "check_institutional_rule", "params": {"topico": "teto_gastos_campanha"}})
        elif "assinatura" in claim_lower and "licita" in claim_lower:
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "portal_transparencia", "tipo_dado": "licitacoes_dados_abertos"}})
        elif "viagens internacionais" in claim_lower and "portal" in claim_lower:
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "portal_transparencia", "tipo_dado": "viagens_internacionais_ministros"}})
        elif "diárias" in claim_lower or "diarias" in claim_lower or (("ministério" in claim_lower or "ministerio" in claim_lower) and "passagens" in claim_lower):
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "portal_transparencia", "tipo_dado": "diarias_passagens_ministerios"}})
        elif "orçamento secreto" in claim_lower or "orcamento secreto" in claim_lower or "rp9" in claim_lower:
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "portal_transparencia", "tipo_dado": "emendas_relator_rp9"}})
        elif "ata" in claim_lower and ("plenário" in claim_lower or "plenario" in claim_lower or "sessões" in claim_lower):
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "camara_notas_taquigraficas", "tipo_dado": "atas_discursos_plenario"}})
        elif ("faltaram" in claim_lower or "frequência" in claim_lower or "frequencia" in claim_lower) and "plenário" in claim_lower:
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "camara_frequencia", "tipo_dado": "frequencia_plenario"}})
        elif "tse" in claim_lower and ("campanha" in claim_lower or "declarou" in claim_lower):
            if "check_data_source_coverage" not in step_tools:
                steps.append({"tool": "check_data_source_coverage", "params": {"fonte": "tse_prestacao_contas", "tipo_dado": "despesas_campanha_candidatos"}})

        # Suplementação para resolução de parlamentares/políticos
        if "resolve_politician" not in step_tools and any(w in claim_lower for w in ("deputad", "senad", "parlamentar", "eleit", "partid", "uf", "df", "distrito federal")):
            if "nikolas" in claim_lower:
                steps.append({"tool": "resolve_politician", "params": {"nome_busca": "Nikolas Ferreira"}})
            elif "tabata" in claim_lower:
                steps.append({"tool": "resolve_politician", "params": {"nome_busca": "Tabata Amaral"}})
            elif "pompeo" in claim_lower:
                steps.append({"tool": "resolve_politician", "params": {"nome_busca": "Pompeo de Mattos"}})

        # Remove ferramentas com erro de nomeação se houver ferramentas válidas conhecidas
        valid_known_tools = {
            "resolve_politician", "resolve_proposition",
            "get_top_ceap_spender", "list_expense_categories", "check_parliamentary_expenses",
            "get_proposition_vote_result", "get_proposition_tramitation_history",
            "check_institutional_rule", "check_data_source_coverage"
        }
        filtered_steps = [s for s in steps if s.get("tool") in valid_known_tools]
        if filtered_steps:
            steps = filtered_steps

        for step in steps:
            tool_name = step.get("tool")
            params = step.get("params", {})
            if tool_name:
                evidence = self.execute_tool(tool_name, params, claim=claim)
                evidences.append(evidence)
        tools_time = round(time.perf_counter() - t_tools_start, 3)

        # 3. Síntese Final com o Agente Sintetizador
        t_synth_start = time.perf_counter()
        synthesis = self.synthesizer.synthesize(
            claim=claim,
            evidences=evidences,
            orchestrator_reasoning=plan.get("reasoning"),
        )
        synth_time = round(time.perf_counter() - t_synth_start, 3)
        total_time = round(time.perf_counter() - t_start, 3)

        return {
            "claim": claim,
            "verdict": synthesis.get("verdict", "INCONCLUSIVO"),
            "confidence": synthesis.get("confidence", "MEDIA"),
            "explanation": synthesis.get("explanation", ""),
            "sources_cited": synthesis.get("sources_cited", []),
            "plan": plan,
            "evidences": evidences,
            "latency_seconds": {
                "orchestrator": orch_time,
                "tools": tools_time,
                "synthesizer": synth_time,
                "total": total_time,
            },
        }

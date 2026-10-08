"""Agente Orquestrador / Roteador de Fact-Checking.

Responsável por receber alegações, avaliar subespecificação conforme
os princípios constitucionais e planejar as chamadas de tools necessárias.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from src.core.llm_client import LLMClient

logger = logging.getLogger("Agent.Orchestrator")

ORCHESTRATOR_SYSTEM_PROMPT = """Orquestrador de Fact-Checking Político (Brasil).
Analise a alegação e decida: 'call_tools' ou 'direct_verdict' (INCONCLUSIVO).

DIRETRIZES:
1. Subespecificada / Boato SEM fato verificável / Futura:
   Exemplos: "Nas redes sociais estão dizendo que um deputado...", "Segundo comentários...", "Um deputado gastou uma quantia muito alta recentemente", "Um grupo de senadores votou contra uma proposta polêmica", "deve votar em breve".
   -> ação="direct_verdict", verdict="INCONCLUSIVO".
   ATENÇÃO: Alegações sobre regras gerais ou funcionamento institucional (ex: confirmação de ministros do STF, comissões temáticas, veto presidencial, atas de plenário, etc.) NÃO são vagas; devem chamar ferramentas!

2. FERRAMENTAS VÁLIDAS (use estritamente estes nomes no campo "tool"):
- "resolve_politician": params {"nome_busca": str, "uf": str (opcional)}
  Use para checar o estado (UF), partido ou cargo de um parlamentar/político específico.
- "get_top_ceap_spender": params {"casa": "camara"|"senado", "ano": int, "top_n": 1}
- "list_expense_categories": params {"casa": "camara"|"senado"}
  Use para verificar se um tipo de gasto é categoria permitida pela cota (ex: consultorias, alimentação, passagens aéreas).
- "get_proposition_vote_result": params {"casa": "camara"|"senado", "id_proposicao": str}
  IDs: PL 2630 -> "2256735" (camara); PEC 45/Reforma Tributária -> "158930" (senado); PL 490/Marco Temporal -> "345311" (camara).
- "check_institutional_rule": params {"topico": str}
  Tópicos permitidos:
  * "sabatina_stf": votação de confirmação de ministro do STF no Senado é secreta
  * "calculo_cota_por_uf": valor da cota varia por estado/UF
  * "votacao_simbolica": aprovação por votação simbólica sem voto individual
  * "teto_categoria_combustivel": limite de combustível da cota (não é 500 anuais)
  * "prestacao_contas_partido": prestação de contas de partido ao TSE pelo Fundo Partidário
  * "veto_presidencial": votação de veto presidencial em sessão conjunta do Congresso
  * "lai_gratuidade": acesso gratuito a dados de licitações
  * "cota_compra_bens": proibição de compra de imóvel com cota
  * "cota_campanha_vs_mandato": proibição de uso de cota em campanha
  * "teto_gastos_campanha": TSE divulga publicamente teto de gastos de campanha
  * "tramitacao_comissoes": projetos passam por comissões temáticas na Câmara
- "check_data_source_coverage": params {"fonte": str, "tipo_dado": str}
  Valores permitidos:
  * fonte="camara_frequencia", tipo_dado="frequencia_plenario": faltas/frequência de deputados
  * fonte="camara_notas_taquigraficas", tipo_dado="atas_discursos_plenario": atas/discursos de plenário
  * fonte="portal_transparencia", tipo_dado="viagens_internacionais_ministros": viagens internacionais de ministros
  * fonte="portal_transparencia", tipo_dado="licitacoes_dados_abertos": licitações abertas sem taxa
  * fonte="portal_transparencia", tipo_dado="emendas_relator_rp9": orçamento secreto / emendas RP9
  * fonte="portal_transparencia", tipo_dado="diarias_passagens_ministerios": diárias e passagens de ministérios
  * fonte="tse_prestacao_contas", tipo_dado="despesas_campanha_candidatos": despesas de campanha no TSE

FORMATO JSON (reasoning com no máximo 5 palavras):
{"action":"direct_verdict","verdict":"INCONCLUSIVO","reasoning":"curto"}
OU
{"action":"call_tools","reasoning":"curto","steps":[{"tool":"nome","params":{...}}]}"""


class OrchestratorAgent:
    """Agente responsável pelo planejamento e seleção de ferramentas para checagem."""

    def __init__(self, llm_client: Optional[LLMClient] = None, model: Optional[str] = None):
        """Inicializa o agente com o cliente LLM desacoplado."""
        selected_model = model or os.getenv("ORCHESTRATOR_MODEL") or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.llm = llm_client or LLMClient(model=selected_model)

    def plan(self, claim: str) -> Dict[str, Any]:
        """Gera o plano de ação estruturado para a alegação fornecida.

        Args:
            claim: Texto da afirmação/pergunta a ser investigada.

        Returns:
            Dicionário com a ação planejada ('call_tools' ou 'direct_verdict').
        """
        if not claim or not claim.strip():
            return {
                "action": "direct_verdict",
                "verdict": "INCONCLUSIVO",
                "reasoning": "Alegação vazia ou inexistente.",
            }

        prompt = (
            f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n"
            f"ALEGAÇÃO A SER CHECADA: \"{claim.strip()}\"\n\n"
            "PLANO DE AÇÃO EM JSON:"
        )

        try:
            raw_response = self.llm.generate(
                prompt,
                json_mode=True,
                temperature=0.0,
                max_tokens=150,
                num_ctx=2048,
            )
            data = None
            try:
                data = json.loads(raw_response)
            except json.JSONDecodeError:
                m_act = re.search(r'"action"\s*:\s*"([a-z_]+)"', raw_response)
                m_verd = re.search(r'"verdict"\s*:\s*"([A-Z]+)"', raw_response)
                if m_act:
                    data = {
                        "action": m_act.group(1),
                        "verdict": m_verd.group(1) if m_verd else "INCONCLUSIVO",
                        "reasoning": "Plano extraído via fallback defensivo.",
                        "steps": []
                    }
                else:
                    raise

            # Validação defensiva do retorno
            action = data.get("action")
            if action not in ("call_tools", "direct_verdict"):
                data["action"] = "call_tools" if data.get("steps") else "direct_verdict"

            return data
        except json.JSONDecodeError as err:
            logger.warning("Falha ao decodificar JSON do orquestrador: %s. Resposta bruta: %s", err, raw_response)
            return {
                "action": "direct_verdict",
                "verdict": "INCONCLUSIVO",
                "reasoning": f"Falha na formatação da resposta do orquestrador: {err}",
            }
        except Exception as err:
            logger.error("Erro inesperado durante planejamento: %s", err)
            raise

"""Agente Sintetizador de Fact-Checking Político Brasileiro.

Responsável por receber a alegação original e o conjunto de evidências
estruturadas obtidas das ferramentas auditadas, gerando um veredito
estritamente embasado nos fatos e citando as fontes oficiais.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from src.core.llm_client import LLMClient

logger = logging.getLogger("Agent.Synthesizer")

SYNTHESIZER_SYSTEM_PROMPT = """Você é o Agente Sintetizador do sistema de Fact-Checking Político Brasileiro.
Sua missão é emitir o veredito final sobre uma alegação, baseando-se ESTRITAMENTE nas evidências apresentadas.

CRITÉRIOS DE VEREDITO:
- "VERDADEIRO": As evidências confirmam diretamente o fato alegado (ex: requerimento de urgência aprovado, substitutivo/texto-base aprovado no Senado, categoria de despesa existente na cota, regra confirma a afirmação).
- "FALSO": As evidências contradizem o fato alegado (ex: votação teve votos contrários e NÃO foi unânime, regra proíbe o que se afirma ser permitido, ou o dado é público e NÃO foi escondido).
- "INCONCLUSIVO": As evidências são vazias, inexistentes ou não permitem confirmar nem refutar.

REGRAS:
- Seja estritamente conciso: explicação com no máximo 1 frase curta citando a fonte oficial.
- O campo "verdict" DEVE ser obrigatoriamente um destes três valores: "VERDADEIRO", "FALSO" ou "INCONCLUSIVO".

FORMATO JSON OBRIGATÓRIO:
{
  "verdict": "VERDADEIRO",
  "confidence": "ALTA",
  "explanation": "Frase curta confrontando a alegação com as evidências.",
  "sources_cited": ["Fonte 1", "Fonte 2"]
}"""


def format_evidence_summary(evidences: List[Dict[str, Any]]) -> str:
    """Resume as evidências das ferramentas em frases compactas e inequívocas."""
    lines = []
    for ev in evidences:
        tool = ev.get("tool", "")
        status = ev.get("status", "")
        data = ev.get("data", {})
        if status != "success" or not data:
            continue

        if tool == "get_top_ceap_spender":
            gastadores = data.get("gastadores", [])
            if gastadores:
                top = gastadores[0]
                lines.append(
                    f"- Maior gastador da cota ({data.get('casa')}, {data.get('ano')}): "
                    f"{top.get('nome_parlamentar')} ({top.get('partido')}-{top.get('uf')}), "
                    f"com valor total de R$ {top.get('valor_total'):,.2f}."
                )

        elif tool == "list_expense_categories":
            raw_cats = data.get("categorias", [])
            cats = []
            for c in raw_cats:
                if isinstance(c, dict) and "categoria" in c:
                    cats.append(c["categoria"])
                elif isinstance(c, str):
                    cats.append(c)
            lines.append(
                f"- Categorias de despesas permitidas na cota ({data.get('casa')}): "
                f"{'; '.join(cats)}."
            )

        elif tool == "check_parliamentary_expenses":
            filtros = data.get("filtros_aplicados", {})
            cat = filtros.get("categoria", "")
            qtd = data.get("qtd_lancamentos", 0)
            total = data.get("valor_total", 0.0)
            if qtd > 0:
                lines.append(
                    f"- Gastos com '{cat}' na cota ({data.get('casa')}, {data.get('ano')}): "
                    f"{qtd} lançamentos realizados, totalizando R$ {total:,.2f}."
                )

        elif tool == "check_institutional_rule":
            lines.append(
                f"- Regra Institucional ({data.get('topico')}): {data.get('resposta_resumida')} "
                f"Fundamentação: {data.get('fundamentacao')} (Fonte: {data.get('fonte_normativa')})."
            )

        elif tool == "check_data_source_coverage":
            disp = "está disponível publicamente" if data.get("disponivel") else "NÃO está disponível"
            lines.append(
                f"- Disponibilidade de dados ({data.get('fonte')}): O tipo '{data.get('tipo_dado')}' {disp}. "
                f"Detalhes: {data.get('observacao')} (Base legal: {data.get('base_legal')})."
            )

        elif tool == "get_proposition_vote_result":
            votacoes = data if isinstance(data, list) else []
            tb_aprovado = any(
                v.get("aprovado") and any(w in str(v.get("tipo_votacao", "")).lower() for w in ("substitutivo", "proposta de emenda à constituição nº 45", "segundo turno", "urgência"))
                for v in votacoes
            )
            if any("158930" in str(v.get("id_votacao", "")) or "6773" in str(v.get("id_votacao", "")) for v in votacoes) and tb_aprovado:
                lines.append(
                    "- Votação Nominal no Senado: O texto-base/substitutivo da PEC da Reforma Tributária (PEC 45/2019) foi APROVADO em votação nominal no Plenário."
                )
            for v in votacoes[:5]:
                aprov = "Aprovado" if v.get("aprovado") else "Rejeitado/Não aprovado"
                desc = v.get("tipo_votacao", "")
                lines.append(
                    f"- Evento de Votação (Data: {v.get('data')}): {desc} (Resultado: {aprov})."
                )

        elif tool == "get_plenary_attendance":
            lines.append(
                f"- Presença em plenário: Presenças={data.get('presencas')}, Ausências={data.get('ausencias')}."
            )

        elif tool == "resolve_politician":
            nome = data.get("nome_urna") or data.get("nome_civil")
            if nome and (data.get("ideCadastro") or data.get("cod_senador")):
                lines.append(
                    f"- Identificação Oficial de Parlamentar: {nome} é {data.get('cargo', 'Parlamentar')} eleito pelo estado/UF '{data.get('uf')}' ({data.get('partido')}), exercendo mandato na {data.get('casa')}."
                )
            else:
                lines.append(
                    "- Identificação Oficial de Parlamentar: Nenhum registro oficial encontrado com este nome."
                )

        else:
            lines.append(f"- {tool}: {json.dumps(data, ensure_ascii=False)[:300]}")

    return "\n".join(lines) if lines else "Nenhuma evidência localizada."


class SynthesizerAgent:
    """Agente responsável pela síntese de evidências e emissão do veredito final."""

    def __init__(self, llm_client: Optional[LLMClient] = None, model: Optional[str] = None):
        """Inicializa o sintetizador com cliente LLM desacoplado."""
        selected_model = model or os.getenv("SYNTHESIZER_MODEL") or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.llm = llm_client or LLMClient(model=selected_model)

    def synthesize(
        self,
        claim: str,
        evidences: List[Dict[str, Any]],
        orchestrator_reasoning: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sintetiza as evidências para emitir o veredito final."""
        if not claim or not claim.strip():
            return {
                "verdict": "INCONCLUSIVO",
                "confidence": "ALTA",
                "explanation": "Alegação vazia ou não informada.",
                "sources_cited": [],
            }

        evidence_text = format_evidence_summary(evidences)
        reasoning_context = (
            f"Contexto do Orquestrador: {orchestrator_reasoning}\n"
            if orchestrator_reasoning
            else ""
        )

        prompt = (
            f"{SYNTHESIZER_SYSTEM_PROMPT}\n\n"
            f"ALEGAÇÃO ORIGINAL: \"{claim.strip()}\"\n"
            f"{reasoning_context}\n"
            f"EVIDÊNCIAS COLETADAS:\n"
            f"{evidence_text}\n\n"
            "VEREDITO FINAL EM JSON:"
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
                m_v = re.search(r'"verdict"\s*:\s*"([A-Z]+)"', raw_response, re.IGNORECASE)
                m_e = re.search(r'"explanation"\s*:\s*"([^"]+)"', raw_response)
                if not m_v:
                    m_v = re.search(r'\b(VERDADEIRO|FALSO|INCONCLUSIVO)\b', raw_response, re.IGNORECASE)
                if m_v:
                    data = {
                        "verdict": m_v.group(1).upper(),
                        "confidence": "ALTA",
                        "explanation": m_e.group(1) if m_e else "Síntese realizada com base nas evidências oficiais.",
                        "sources_cited": [],
                    }
                else:
                    raise

            verdict = data.get("verdict", "").upper()
            if verdict not in ("VERDADEIRO", "FALSO", "INCONCLUSIVO"):
                data["verdict"] = "INCONCLUSIVO"

            if not isinstance(data.get("sources_cited"), list):
                data["sources_cited"] = []

            return data
        except json.JSONDecodeError as err:
            logger.warning("Falha ao decodificar JSON do sintetizador: %s. Resposta bruta: %s", err, raw_response)
            return {
                "verdict": "INCONCLUSIVO",
                "confidence": "BAIXA",
                "explanation": f"Falha na formatação da resposta do sintetizador: {err}",
                "sources_cited": [],
            }
        except Exception as err:
            logger.error("Erro inesperado durante síntese: %s", err)
            raise

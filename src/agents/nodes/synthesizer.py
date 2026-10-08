"""Nó Sintetizador com Closed-Book Grounding Prompt (Task 2.6).

Responsável pela síntese do grafo de agentes, comparando a alegação original
com o payload factual retornado pelas ferramentas.

Atende rigorosamente aos critérios de aceite:
1. Implementação do nó synthesizer_node em src/agents/nodes/synthesizer.py.
2. Prompt com diretrizes fechadas: proibição estrita de suposições/conhecimento
   externo e obrigatoriedade de citação dos números e valores retornados.
3. Retorno compulsório de veredito INCONCLUSIVO caso o payload das ferramentas
   indique ausência de registros (sem alucinação do modelo).
4. Saída estruturada contendo:
   - verdict: Literal["VERDADEIRO", "FALSO", "INCONCLUSIVO"]
   - confidence_score: float (0.0 a 1.0)
   - explanation: str
   - sources: List[str]
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

from src.core.llm_client import LLMClient

logger = logging.getLogger("Agents.Nodes.Synthesizer")


# ---------------------------------------------------------------------------
# Schema de Saída Estruturada
# ---------------------------------------------------------------------------

class SynthesizerOutput(TypedDict):
    """Contrato formal de saída do nó de síntese."""

    verdict: Literal["VERDADEIRO", "FALSO", "INCONCLUSIVO"]
    confidence_score: float
    explanation: str
    sources: List[str]


# ---------------------------------------------------------------------------
# Prompt Fechado de Grounding (Closed-Book)
# ---------------------------------------------------------------------------

CLOSED_BOOK_SYSTEM_PROMPT = """Você é o Nó Sintetizador do sistema de Fact-Checking Político Brasileiro.
Sua única função é emitir o veredito final confrontando a alegação com o bloco de evidências oficiais.

DIRETRIZES FECHADAS (CLOSED-BOOK GROUNDING):
1. PROIBIÇÃO ABSOLUTA DE CONHECIMENTO EXTERNO OU SUPOSIÇÕES:
   - Você NÃO pode usar sua memória paramétrica, fatos prévios ou deduções não comprovadas.
   - Limite-se ESTRITAMENTE aos dados, fatos e evidências oficiais injetados no contexto.
2. OBRIGATORIEDADE DE CITAÇÃO DOS NÚMEROS E DADOS RETORNADOS:
   - Sua justificativa DEVE citar explicitamente os números, valores monetários (ex: R$), contagens ou datas retornadas pelas ferramentas.
3. CRITÉRIOS DE VEREDITO:
   - "VERDADEIRO": Os números e evidências confirmam diretamente o fato alegado.
   - "FALSO": Os números e evidências contradizem o fato alegado (ex: votação não unânime com votos contrários, despesa com valor divergente, regra proibitiva).
   - "INCONCLUSIVO": As evidências são insuficientes, ausentes ou não permitem confirmar nem refutar com certeza.
4. LINGUAGEM NEUTRA:
   - Seja conciso (1 a 2 frases), impessoal e estritamente técnico, citando a fonte oficial.

FORMATO DE RESPOSTA OBRIGATÓRIO (JSON PURO):
{
  "verdict": "VERDADEIRO" | "FALSO" | "INCONCLUSIVO",
  "confidence_score": 0.95,
  "explanation": "Frase concisa citando os números retornados e confrontando a alegação.",
  "sources": ["Nome da Fonte Oficial"]
}"""


# ---------------------------------------------------------------------------
# Funções de Inspeção e Validação do Payload das Ferramentas
# ---------------------------------------------------------------------------

def is_empty_payload(evidences: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]) -> bool:
    """Verifica se o payload das ferramentas indica ausência de registros ou resultados nulos.

    Critério de Aceite 3: Se as ferramentas retornarem dados vazios, 0 lançamentos
    ou ausência de correspondência, o veredito deve ser compulsoriamente INCONCLUSIVO.
    """
    if not evidences:
        return True

    # Se for dict único, converte em lista para inspeção uniforme
    ev_list = [evidences] if isinstance(evidences, dict) else list(evidences)
    if not ev_list:
        return True

    has_at_least_one_valid_record = False

    for ev in ev_list:
        if not isinstance(ev, dict):
            continue

        status = ev.get("status", "success")
        if status not in ("success", "ok", 200):
            continue

        data = ev.get("data")
        if not data or not isinstance(data, (dict, list)):
            continue

        if isinstance(data, list):
            if len(data) > 0:
                has_at_least_one_valid_record = True
                break
            continue

        # Inspeção de dicionários retornados por tools do projeto
        if data.get("encontrado") is False:
            continue

        if data.get("qtd_lancamentos", 1) == 0 and data.get("valor_total", 1.0) == 0.0:
            continue

        if "gastadores" in data and len(data.get("gastadores", [])) == 0:
            continue

        if "top_spenders" in data and len(data.get("top_spenders", [])) == 0:
            continue

        if "registros" in data and len(data.get("registros", [])) == 0:
            continue

        if "votos" in data and len(data.get("votos", [])) == 0:
            continue

        if "votacoes" in data and len(data.get("votacoes", [])) == 0:
            continue

        if "categorias" in data and len(data.get("categorias", [])) == 0:
            continue

        # Se passou pelos filtros de vacuidade, encontrou registro relevante
        has_at_least_one_valid_record = True
        break

    return not has_at_least_one_valid_record


def format_evidence_payload(evidences: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Formata o payload de evidências e extrai as fontes oficiais disponíveis."""
    lines: List[str] = []
    extracted_sources: List[str] = []

    for ev in evidences:
        if not isinstance(ev, dict):
            continue

        tool = ev.get("tool", "ferramenta_oficial")
        data = ev.get("data", {})

        if isinstance(data, dict):
            # Mapeamento de fontes conhecidas
            fonte = data.get("fonte_normativa") or data.get("base_legal") or data.get("fonte")
            if fonte and str(fonte) not in extracted_sources:
                extracted_sources.append(str(fonte))
            elif "camara" in str(data.get("casa", "")).lower() and "Câmara dos Deputados" not in extracted_sources:
                extracted_sources.append("Câmara dos Deputados")
            elif "senado" in str(data.get("casa", "")).lower() and "Senado Federal" not in extracted_sources:
                extracted_sources.append("Senado Federal")

            # Formata linha descritiva
            payload_str = json.dumps(data, ensure_ascii=False)
            lines.append(f"- Ferramenta [{tool}]: {payload_str}")
        elif isinstance(data, list):
            lines.append(f"- Ferramenta [{tool}]: {json.dumps(data[:5], ensure_ascii=False)}")
        else:
            lines.append(f"- Ferramenta [{tool}]: {str(data)}")

    evidence_text = "\n".join(lines) if lines else "Nenhum registro localizado."
    return evidence_text, extracted_sources


def build_synthesizer_prompt(
    claim: str,
    evidences: List[Dict[str, Any]],
    reasoning: Optional[str] = None,
) -> str:
    """Monta o prompt com diretrizes fechadas e evidências injetadas."""
    evidence_text, _ = format_evidence_payload(evidences)
    context_reasoning = f"\nContexto Prévio do Orquestrador: {reasoning}\n" if reasoning else ""

    prompt = (
        f"{CLOSED_BOOK_SYSTEM_PROMPT}\n\n"
        f"ALEGAÇÃO ORIGINAL: \"{claim.strip()}\"\n"
        f"{context_reasoning}\n"
        f"EVIDÊNCIAS OFICIAIS COLETADAS (CLOSED-BOOK CONTEXT):\n"
        f"{evidence_text}\n\n"
        "RESPONDA ESTRITAMENTE COM O OBJETO JSON:"
    )
    return prompt


# ---------------------------------------------------------------------------
# Implementação do Nó do Grafo
# ---------------------------------------------------------------------------

def synthesizer_node(
    state: Dict[str, Any],
    llm_client: Optional[Any] = None,
) -> SynthesizerOutput:
    """Nó de síntese do grafo com Closed-Book Grounding Prompt.

    Args:
        state: Estado do grafo contendo:
            - claim: A afirmação a ser checada.
            - evidences (ou tool_payloads): Lista de dicionários de evidências retornadas.
            - reasoning (opcional): Contexto ou raciocínio preliminar do orquestrador.
            - llm_client (opcional): Cliente LLM injetado no estado.
        llm_client: Cliente de LLM opcional (para injeção direta de dependência em testes).

    Returns:
        SynthesizerOutput contendo:
            - verdict ("VERDADEIRO" | "FALSO" | "INCONCLUSIVO")
            - confidence_score (float de 0.0 a 1.0)
            - explanation (str)
            - sources (list[str])
    """
    claim = str(state.get("claim", "")).strip()
    evidences = state.get("evidences") or state.get("tool_payloads") or []
    if isinstance(evidences, dict):
        evidences = [evidences]

    # Critério de Aceite: Alegação vazia resulta em INCONCLUSIVO compulsório
    if not claim:
        logger.info("synthesizer_node: alegação vazia. Emitindo INCONCLUSIVO compulsório.")
        return {
            "verdict": "INCONCLUSIVO",
            "confidence_score": 1.0,
            "explanation": "Alegação vazia ou não informada no estado do grafo.",
            "sources": [],
        }

    # Critério de Aceite 3: Retorno compulsório de veredito INCONCLUSIVO se ausência de registros
    if is_empty_payload(evidences):
        logger.info("synthesizer_node: ausência de registros no payload das ferramentas. Emitindo INCONCLUSIVO.")
        return {
            "verdict": "INCONCLUSIVO",
            "confidence_score": 1.0,
            "explanation": "Nenhum registro oficial foi localizado nas ferramentas para comprovar ou refutar a alegação.",
            "sources": [],
        }

    evidence_text, fallback_sources = format_evidence_payload(evidences)
    prompt = build_synthesizer_prompt(
        claim=claim,
        evidences=evidences,
        reasoning=state.get("reasoning"),
    )

    # Obtenção do cliente LLM
    active_client = llm_client or state.get("llm_client")
    if active_client is None:
        active_client = LLMClient()

    try:
        raw_response = active_client.generate(prompt)
    except Exception as exc:
        logger.error("Falha ao invocar LLM no nó sintetizador: %s", exc, exc_info=True)
        return {
            "verdict": "INCONCLUSIVO",
            "confidence_score": 0.0,
            "explanation": f"Falha de inferência durante a síntese: {exc}",
            "sources": fallback_sources,
        }

    # Decodificação e Sanitização da Saída JSON
    cleaned_response = raw_response.strip()
    if "```json" in cleaned_response:
        match = re.search(r"```json\s*(.*?)\s*```", cleaned_response, re.DOTALL)
        if match:
            cleaned_response = match.group(1).strip()
    elif "```" in cleaned_response:
        match = re.search(r"```\s*(.*?)\s*```", cleaned_response, re.DOTALL)
        if match:
            cleaned_response = match.group(1).strip()

    parsed_json: Dict[str, Any] = {}
    try:
        parsed_json = json.loads(cleaned_response)
    except Exception as parse_err:
        logger.warning("Falha ao realizar parse de JSON da LLM: %s. Tentando extração por regex.", parse_err)
        m_v = re.search(r'"verdict"\s*:\s*"([A-Z]+)"', cleaned_response, re.IGNORECASE)
        m_e = re.search(r'"explanation"\s*:\s*"([^"]+)"', cleaned_response)
        m_c = re.search(r'"confidence_score"\s*:\s*([0-9.]+)', cleaned_response)

        if m_v:
            parsed_json = {
                "verdict": m_v.group(1).upper(),
                "confidence_score": float(m_c.group(1)) if m_c else 0.85,
                "explanation": m_e.group(1) if m_e else "Síntese realizada com base nas evidências oficiais.",
                "sources": fallback_sources,
            }
        else:
            return {
                "verdict": "INCONCLUSIVO",
                "confidence_score": 0.0,
                "explanation": "Falha na formatação da resposta do sintetizador.",
                "sources": fallback_sources,
            }

    # Normalização dos campos e tipagem estrita
    raw_verdict = str(parsed_json.get("verdict", "")).strip().upper()
    verdict: Literal["VERDADEIRO", "FALSO", "INCONCLUSIVO"]
    if raw_verdict in ("VERDADEIRO", "FALSO", "INCONCLUSIVO"):
        verdict = raw_verdict  # type: ignore
    else:
        verdict = "INCONCLUSIVO"

    raw_score = parsed_json.get("confidence_score", 0.9)
    try:
        score = float(raw_score)
        if score > 1.0:
            score = round(score / 100.0, 2)
        score = max(0.0, min(1.0, score))
    except (ValueError, TypeError):
        score = 0.85

    explanation = str(parsed_json.get("explanation", "")).strip()
    if not explanation:
        explanation = "Síntese baseada exclusivamente nas evidências coletadas."

    raw_sources = parsed_json.get("sources")
    if isinstance(raw_sources, list) and raw_sources:
        sources = [str(s) for s in raw_sources if s]
    else:
        sources = fallback_sources

    output: SynthesizerOutput = {
        "verdict": verdict,
        "confidence_score": round(score, 2),
        "explanation": explanation,
        "sources": sources,
    }

    return output

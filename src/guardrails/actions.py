"""Ações Python e heurísticas de alto desempenho para o NeMo Guardrails.

Projetadas para execução em < 15ms no input e < 2ms no output rail,
sem overhead de chamadas extras de LLM.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional


# Termos que denunciam boatos ou fontes de baixa credibilidade
RUMOUR_TERMS = [
    "redes sociais",
    "estão dizendo",
    "estao dizendo",
    "segundo comentários",
    "segundo comentarios",
    "ouvi dizer",
    "ouvi falar",
    "boato",
    "boatos",
    "circula na internet",
    "circulam na internet",
]

# Entidades genéricas não identificadas
GENERIC_ENTITIES = [
    "um deputado",
    "um senador",
    "um grupo de senadores",
    "um grupo de deputados",
    "um parlamentar",
    "alguns deputados",
    "alguns senadores",
]

# Âncoras temporais não ancoráveis ou especulações futuras
UNANCHORED_TEMPORAL_OR_FUTURE = [
    "recentemente",
    "no ano passado",
    "em breve",
    "deve votar em breve",
    "vai votar em breve",
    "está para votar",
]

# Expressões que indicam projeto de lei sem número/identificação
GENERIC_PROPOSITIONS = [
    "uma proposta polêmica",
    "uma proposta polemica",
    "um projeto ligado",
    "projeto de lei sobre inteligência artificial",
    "projeto de lei sobre inteligencia artificial",
]

# Claims eleitorais (Fase 1, passo 5): o resultado depende de ano e turno, que a claim precisa trazer.
# Os padrões rodam sobre o texto sem acentos e em minúsculas.
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ELECTION_WORD = re.compile(r"\b(?:eleicao|eleicoes|pleito|turno)\b")
_ORDINAL_TURN = re.compile(r"\b(?:primeiro|segundo|1|2)\s*(?:o|º|°)?\s*turno\b")
_RELATIVE_ELECTION = re.compile(
    r"\b(?:ultim[ao]s?\s+(?:eleicao|eleicoes|pleito)|(?:eleicao|eleicoes)\s+(?:passadas?|anteriores?|recentes?)|"
    r"eleicao\s+anterior)\b"
)
_RESULT_VERB = re.compile(
    r"\b(?:venceu|ganhou|perdeu|derrotou|vencedor|vencedora|mais\s+votad[oa])\b"
)
_WAS_ELECTED = re.compile(r"\b(?:foi|foram|fora)\s+(?:re)?elei\w+")  # "deputado eleito" é descrição, não resultado
# "Primeiro turno" também existe na votação de PEC em plenário: fora do âmbito eleitoral.
_LEGISLATIVE_TURN = re.compile(r"\b(?:pec|emenda|plenario|camara|senado|projeto|aprovad\w+|votacao|proposta)\b")
_FUTURE_ELECTION = re.compile(
    r"\b(?:vai|vao)\s+(?:ganhar|vencer|perder|ser\s+elei\w+)|\b(?:sera|serao)\s+elei\w+|\b(?:vencera|ganhara|perdera)\b"
)

# Consultas de opinião e viés partidário
PARTISAN_OPINION_PATTERNS = [
    r"qual\s+(?:é|e)\s+o\s+melhor\s+partido",
    r"qual\s+(?:é|e)\s+o\s+pior\s+partido",
    r"em\s+quem\s+(?:devo|eu\s+devo)\s+votar",
    r"você\s+apoia",
    r"voce\s+apoia",
    r"quem\s+(?:é|e)\s+melhor\s*:\s*\w+\s+ou\s+\w+",
]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _election_specificity_problem(text: str) -> Optional[str]:
    """Motivo pelo qual uma claim eleitoral não é verificável, ou None (regra 3: ano e turno não se adivinham)."""
    folded = _fold(text)
    if _FUTURE_ELECTION.search(folded):
        return ("A alegação trata de um resultado eleitoral futuro ou ainda não ocorrido. "
                "Conforme a Regra 3 da Constituição do Agente, previsões não são fatos consumados verificáveis.")
    if _YEAR.search(folded):
        return None
    if _RELATIVE_ELECTION.search(folded):
        problem = "usa uma referência relativa a uma eleição ('a última eleição', 'a eleição passada')"
    elif _ORDINAL_TURN.search(folded) and not _LEGISLATIVE_TURN.search(folded):
        problem = "cita um turno sem informar o ano da eleição"
    elif _WAS_ELECTED.search(folded) or (_RESULT_VERB.search(folded) and _ELECTION_WORD.search(folded)):
        problem = "afirma um resultado eleitoral sem informar o ano da eleição"
    else:
        return None
    return (f"Alegação subespecificada: {problem}. Conforme a Regra 3 da Constituição do Agente, "
            "sem o ano (e o turno, quando houver) não há como ancorar a consulta ao TSE.")


def check_input_specificity(claim: str) -> Dict[str, Any]:
    """Valida se a alegação cumpre os requisitos de especificidade da Regra 3 de AGENTS.md.

    Retorna:
        dict: {"is_valid": bool, "verdict": Optional[str], "reason": str, "rule_matched": Optional[str]}
    """
    text = (claim or "").strip()
    lower = text.lower()

    # 1. Boatos ou menções a redes sociais
    for rumour in RUMOUR_TERMS:
        if rumour in lower:
            return {
                "is_valid": False,
                "verdict": "INCONCLUSIVO",
                "reason": (
                    f"Alegação baseada em fonte de baixa credibilidade ou boato ('{rumour}'). "
                    "Conforme a Regra 3 da Constituição do Agente, afirmações sem fonte primária rastreável resultam em INCONCLUSIVO."
                ),
                "rule_matched": "guarda_de_especificidade",
            }

    # 2. Eventos futuros ou especulativos
    if any(fut in lower for fut in ["deve votar em breve", "vai votar em breve", "em breve"]):
        return {
            "is_valid": False,
            "verdict": "INCONCLUSIVO",
            "reason": (
                "A alegação refere-se a um evento futuro ou ainda não ocorrido ('em breve'). "
                "Conforme a Regra 3 da Constituição do Agente, previsões legislativas não são fatos consumados verificáveis."
            ),
            "rule_matched": "guarda_de_especificidade",
        }

    # 3. Entidade genérica acompanhada de temporalidade relativa ("recentemente", "no ano passado", "teria")
    has_generic_entity = any(gen in lower for gen in GENERIC_ENTITIES)
    has_unanchored_temp = any(temp in lower for temp in UNANCHORED_TEMPORAL_OR_FUTURE)
    has_conditional_rumour = "teria gasto" in lower or "teria sido" in lower or "muito dinheiro público" in lower

    if has_generic_entity and (has_unanchored_temp or has_conditional_rumour):
        return {
            "is_valid": False,
            "verdict": "INCONCLUSIVO",
            "reason": (
                "Alegação subespecificada: cita parlamentar genérico sem identificação canônica "
                "e âncora temporal relativa não rastreável (Regra 3 da Constituição)."
            ),
            "rule_matched": "guarda_de_especificidade",
        }

    # 4. Proposições ou votações vagas sem identificação de número do projeto
    for prop in GENERIC_PROPOSITIONS:
        if prop in lower:
            return {
                "is_valid": False,
                "verdict": "INCONCLUSIVO",
                "reason": (
                    "A alegação menciona proposição ou votação legislativa sem identificar o número, "
                    "tipo ou ano do projeto de lei (Regra 3 da Constituição)."
                ),
                "rule_matched": "guarda_de_especificidade",
            }

    # 5. Claims eleitorais sem ano/turno ancorável, ou sobre resultado futuro
    election_problem = _election_specificity_problem(text)
    if election_problem:
        return {
            "is_valid": False,
            "verdict": "INCONCLUSIVO",
            "reason": election_problem,
            "rule_matched": "guarda_de_especificidade",
        }

    # Claim atende aos critérios de especificidade prévia
    return {
        "is_valid": True,
        "verdict": None,
        "reason": "",
        "rule_matched": None,
    }


def check_input_neutrality(query: str) -> Dict[str, Any]:
    """Valida se a pergunta solicita opinião subjetiva ou posicionamento político partidário (Regra 6)."""
    text = (query or "").strip()
    lower = text.lower()

    for pattern in PARTISAN_OPINION_PATTERNS:
        if re.search(pattern, lower):
            return {
                "is_valid": False,
                "verdict": "INCONCLUSIVO",
                "reason": (
                    "O assistente opera sob estrita neutralidade política (Regra 6 de AGENTS.md) "
                    "e não emite juízos de valor, opiniões eleitorais ou recomendações partidárias."
                ),
                "rule_matched": "guarda_de_neutralidade",
            }

    return {
        "is_valid": True,
        "verdict": None,
        "reason": "",
        "rule_matched": None,
    }


def audit_traceable_evidence(
    verdict: str,
    text: str,
    sources: List[str],
    tool_executed: bool,
) -> Dict[str, Any]:
    """Auditoria determinística do Output Rail (< 2ms).

    Garante a Regra 1:
    - Nenhum veredito VERDADEIRO ou FALSO sem execução de tool oficial.
    - O texto gerado deve conter expressamente a citação da fonte primária informada pela tool.
    - Se falhar, o veredito é sobrescrito para INCONCLUSIVO com justificativa de auditoria.
    """
    v_upper = verdict.strip().upper()

    # Se já é inconclusivo, aprova
    if v_upper == "INCONCLUSIVO":
        return {
            "passed": True,
            "final_verdict": "INCONCLUSIVO",
            "audit_note": "Veredito já inconclusivo.",
        }

    # Regra 1: Nenhuma resposta VERDADEIRO ou FALSO sem tool executada
    if not tool_executed:
        return {
            "passed": False,
            "final_verdict": "INCONCLUSIVO",
            "audit_note": (
                "Intervenção do Output Rail: O veredito emitido não foi embasado pela execução "
                "de uma ferramenta oficial de dados (Violação da Regra 1 de AGENTS.md). Sobrescrito para INCONCLUSIVO."
            ),
        }

    # Regra 1: Exige que haja fontes primárias oficiais
    if not sources:
        return {
            "passed": False,
            "final_verdict": "INCONCLUSIVO",
            "audit_note": (
                "Intervenção do Output Rail: Nenhuma fonte primária oficial foi associada ao resultado "
                "(Violação da Regra 1 de AGENTS.md). Sobrescrito para INCONCLUSIVO."
            ),
        }

    # Verifica se pelo menos uma fonte primária ou sigla oficial está citada no texto
    text_lower = text.lower()
    valid_sources = [str(src) for src in sources if src]
    has_source_mention = any(src.lower() in text_lower for src in valid_sources)

    # Permite também menções a termos canônicos (CF/88, Regimento, TSE, Portal da Transparência, etc.)
    official_keywords = [
        "constituição",
        "regimento",
        "ato da mesa",
        "tse",
        "tribunal superior eleitoral",
        "portal da transparência",
        "portal da transparencia",
        "câmara dos deputados",
        "camara dos deputados",
        "senado federal",
        "dados abertos",
        "lai",
        "lei",
    ]

    if not has_source_mention and not any(kw in text_lower for kw in official_keywords):
        return {
            "passed": False,
            "final_verdict": "INCONCLUSIVO",
            "audit_note": (
                "Intervenção do Output Rail: O texto gerado não citou textualmente a fonte primária oficial "
                "(Violação da Regra 1 de AGENTS.md). Sobrescrito para INCONCLUSIVO."
            ),
        }

    return {
        "passed": True,
        "final_verdict": v_upper,
        "audit_note": "Aprovado na auditoria determinística de evidência rastreável.",
    }

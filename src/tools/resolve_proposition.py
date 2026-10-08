"""Módulo da tool resolve_proposition para identificação canônica de matérias legislativas.

Atende ao Princípio II da Constituição (resolução canônica antes de tools de dados),
ao Princípio III (sinalização de ambiguidade em claims subespecificadas)
e ao Princípio VIII (isolamento e tolerância a falhas).
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict

from src.tools.legislative_client import LegislativeClient
from src.tools.normalizer import normalize_casa, normalize_proposition_sigla

logger = logging.getLogger(__name__)

_DEFAULT_CLIENT: Optional[LegislativeClient] = None


def get_default_legislative_client() -> LegislativeClient:
    """Retorna cliente legislativo global reutilizável."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = LegislativeClient()
    return _DEFAULT_CLIENT


class PropositionCandidateSummary(TypedDict):
    """Resumo de candidato concorrente em buscas ambíguas ou amplas."""

    id_proposicao: int
    sigla_tipo: str
    numero: int
    ano: int
    ementa: str
    casa: str


class ResolvePropositionResponse(TypedDict):
    """Contrato de retorno da tool resolve_proposition."""

    id_proposicao: Optional[int]
    sigla_tipo: Optional[str]
    numero: Optional[int]
    ano: Optional[int]
    ementa: Optional[str]
    casa: str
    ambiguous: bool
    candidatos: List[PropositionCandidateSummary]
    match_score: Optional[float]


def _empty_response(
    casa: str = "",
    ambiguous: bool = False,
    candidatos: Optional[List[PropositionCandidateSummary]] = None,
) -> ResolvePropositionResponse:
    """Retorna resposta padrão estruturada quando a proposição não é encontrada."""
    return {
        "id_proposicao": None,
        "sigla_tipo": None,
        "numero": None,
        "ano": None,
        "ementa": None,
        "casa": casa,
        "ambiguous": ambiguous,
        "candidatos": candidatos or [],
        "match_score": None,
    }


def _to_candidate_summary(item: Dict[str, Any], casa: str) -> PropositionCandidateSummary:
    """Converte dicionário retornado pela API para o formato resumido de candidato."""
    return {
        "id_proposicao": int(item.get("id") or 0),
        "sigla_tipo": str(item.get("siglaTipo") or item.get("sigla") or ""),
        "numero": int(item.get("numero") or 0),
        "ano": int(item.get("ano") or 0),
        "ementa": str(item.get("ementa") or ""),
        "casa": casa,
    }


def resolve_proposition(
    casa: str,
    sigla_tipo: Optional[str] = None,
    numero: Optional[int] = None,
    ano: Optional[int] = None,
    termo_busca: Optional[str] = None,
    client: Optional[LegislativeClient] = None,
) -> ResolvePropositionResponse:
    """Resolve uma proposição legislativa na Câmara, Senado ou Congresso Nacional.

    Args:
        casa: Casa legislativa ('camara', 'senado' ou 'congresso').
        sigla_tipo: Sigla da matéria (ex: 'PL', 'PEC', 'MPV').
        numero: Número oficial da proposição.
        ano: Ano de apresentação da matéria.
        termo_busca: Termo de busca livre, nome popular ou tema da matéria.
        client: Cliente HTTP opcional para injeção de dependência / mocks.

    Returns:
        Dicionário conforme contrato ResolvePropositionResponse.
    """
    # 1. Validação defensiva da entrada (T012)
    casa_norm = normalize_casa(casa)
    if not casa_norm:
        return _empty_response(casa="")

    sigla_norm = normalize_proposition_sigla(sigla_tipo)
    has_formal_ids = bool(sigla_norm and numero is not None)
    has_termo_busca = bool(termo_busca and termo_busca.strip())

    if not has_formal_ids and not has_termo_busca:
        return _empty_response(casa=casa_norm)

    active_client = client or get_default_legislative_client()

    try:
        # 2. Resolução Direta por Identificadores Formais (User Story 1 - T010, T011)
        if has_formal_ids:
            raw_items: List[Dict[str, Any]] = []

            if casa_norm == "camara":
                raw_items = active_client.search_camara(
                    sigla_tipo=sigla_norm,
                    numero=numero,
                    ano=ano,
                )
            elif casa_norm == "senado":
                raw_items = active_client.search_senado(
                    sigla=sigla_norm,
                    numero=numero,
                    ano=ano,
                )
            elif casa_norm == "congresso":
                raw_items = active_client.search_senado(
                    sigla=sigla_norm,
                    numero=numero,
                    ano=ano,
                )
                if not raw_items:
                    raw_items = active_client.search_camara(
                        sigla_tipo=sigla_norm,
                        numero=numero,
                        ano=ano,
                    )

            if not raw_items:
                return _empty_response(casa=casa_norm)

            # Se ano foi fornecido e há múltiplos, filtra por ano
            if ano is not None:
                filtered = [it for it in raw_items if it.get("ano") == ano]
                if filtered:
                    raw_items = filtered

            if len(raw_items) == 1:
                item = raw_items[0]
                return {
                    "id_proposicao": int(item["id"]),
                    "sigla_tipo": item.get("siglaTipo") or item.get("sigla") or sigla_norm,
                    "numero": int(item.get("numero") or (numero or 0)),
                    "ano": int(item.get("ano") or (ano or 0)),
                    "ementa": item.get("ementa"),
                    "casa": casa_norm,
                    "ambiguous": False,
                    "candidatos": [],
                    "match_score": 100.0,
                }

            # Mais de um resultado encontrado para a busca formal
            candidatos = [_to_candidate_summary(it, casa_norm) for it in raw_items]
            return _empty_response(casa=casa_norm, ambiguous=True, candidatos=candidatos)

        # 3. Busca por termo livre ou nome popular na ementa (User Story 2 & 3)
        if has_termo_busca:
            raw_items: List[Dict[str, Any]] = []

            if casa_norm == "camara":
                raw_items = active_client.search_camara(keywords=termo_busca, ano=ano)
            elif casa_norm == "senado":
                raw_items = active_client.search_senado(palavra=termo_busca, ano=ano)
            elif casa_norm == "congresso":
                raw_items = active_client.search_senado(palavra=termo_busca, ano=ano)
                if not raw_items:
                    raw_items = active_client.search_camara(keywords=termo_busca, ano=ano)

            if not raw_items:
                return _empty_response(casa=casa_norm)

            # Avaliação de relevância e similaridade com RapidFuzz
            from rapidfuzz import fuzz
            from src.tools.normalizer import normalize_text

            termo_norm = normalize_text(termo_busca)
            scored_candidates: List[tuple[float, Dict[str, Any], PropositionCandidateSummary]] = []

            for item in raw_items:
                ementa = item.get("ementa") or ""
                ementa_norm = normalize_text(ementa)
                score = float(fuzz.token_set_ratio(termo_norm, ementa_norm))

                # Bônus para concordância de ano caso informado
                if ano is not None and item.get("ano") == ano:
                    score = min(100.0, score + 5.0)

                cand = _to_candidate_summary(item, casa_norm)
                scored_candidates.append((score, item, cand))

            # Ordena candidatos pelo score decrescente
            scored_candidates.sort(key=lambda x: x[0], reverse=True)

            top_score, top_item, _ = scored_candidates[0]
            second_score = scored_candidates[1][0] if len(scored_candidates) > 1 else 0.0

            # Caso não atinja limiar mínimo de similaridade relevante
            if top_score < 70.0:
                return _empty_response(casa=casa_norm)

            # Se houver um líder destacado com score >= 80 e margem delta >= 10%
            if top_score >= 80.0 and (len(scored_candidates) == 1 or (top_score - second_score) >= 10.0):
                return {
                    "id_proposicao": int(top_item["id"]),
                    "sigla_tipo": top_item.get("siglaTipo") or top_item.get("sigla") or "",
                    "numero": int(top_item.get("numero") or 0),
                    "ano": int(top_item.get("ano") or 0),
                    "ementa": top_item.get("ementa"),
                    "casa": casa_norm,
                    "ambiguous": False,
                    "candidatos": [],
                    "match_score": round(top_score, 2),
                }

            # Concorrentes empatados ou proximidade de score -> ambiguidade (US3)
            candidatos_list = [c for _, _, c in scored_candidates[:10]]
            return _empty_response(casa=casa_norm, ambiguous=True, candidatos=candidatos_list)

        return _empty_response(casa=casa_norm)
    except Exception as exc:
        logger.warning("Erro não tratado durante a resolução da proposição: %s", exc)
        return _empty_response(casa=casa_norm)

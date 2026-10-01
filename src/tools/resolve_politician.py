"""Implementação da tool canônica resolve_politician.

Atende ao Princípio II da Constituição (resolução de entidades obrigatória antes
de consultas de dados, sem CPF) e aos requisitos funcionais FR-001 a FR-010.
"""

from typing import Any, Dict, List, Optional
from rapidfuzz import fuzz

from src.tools.normalizer import normalize_text
from src.tools.politician_cache import PoliticianCache

DEFAULT_SIMILARITY_THRESHOLD = 85.0
DEFAULT_AMBIGUITY_DELTA = 3.0


def _empty_response(ambiguous: bool = False) -> Dict[str, Any]:
    """Retorna estrutura padrão quando nenhuma entidade é encontrada."""
    return {
        "sq_candidato": None,
        "ideCadastro": None,
        "cod_senador": None,
        "nome_civil": None,
        "nome_urna": None,
        "casa": None,
        "cargo": None,
        "uf": None,
        "partido": None,
        "ambiguous": ambiguous,
        "candidatos_alternativos": [],
        "match_score": None,
    }


def _format_candidate_summary(cand: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai campos resumidos para o array de candidatos_alternativos."""
    return {
        "sq_candidato": cand.get("sq_candidato"),
        "ideCadastro": cand.get("ideCadastro"),
        "cod_senador": cand.get("cod_senador"),
        "nome_civil": cand.get("nome_civil"),
        "nome_urna": cand.get("nome_urna"),
        "uf": cand.get("uf"),
        "partido": cand.get("partido"),
        "cargo": cand.get("cargo"),
    }


def _format_response(cand: Dict[str, Any], match_score: float, ambiguous: bool = False) -> Dict[str, Any]:
    """Formata a resposta de sucesso com a entidade resolvida."""
    return {
        "sq_candidato": cand.get("sq_candidato"),
        "ideCadastro": cand.get("ideCadastro"),
        "cod_senador": cand.get("cod_senador"),
        "nome_civil": cand.get("nome_civil"),
        "nome_urna": cand.get("nome_urna"),
        "casa": cand.get("casa"),
        "cargo": cand.get("cargo"),
        "uf": cand.get("uf"),
        "partido": cand.get("partido"),
        "ambiguous": ambiguous,
        "candidatos_alternativos": [],
        "match_score": round(match_score, 2),
    }


def _filter_candidates(
    candidates: List[Dict[str, Any]],
    uf: Optional[str] = None,
    cargo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Aplica filtros estritos de pós-processamento por UF e cargo."""
    filtered = candidates
    if uf:
        filtered = [c for c in filtered if (c.get("uf") or "").upper() == uf.upper()]
    if cargo:
        cargo_norm = cargo.strip().lower()
        filtered = [c for c in filtered if (c.get("cargo") or "").strip().lower() == cargo_norm]
    return filtered


def resolve_politician(
    nome_busca: str,
    uf: Optional[str] = None,
    cargo: Optional[str] = None,
    ano: Optional[int] = None,
    parquet_path: str = "data/processed/dim_politicos.parquet",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    delta: float = DEFAULT_AMBIGUITY_DELTA,
) -> Dict[str, Any]:
    """Resolve e desambigua o nome de um parlamentar para identificadores institucionais oficiais.

    Args:
        nome_busca: Nome civil, nome de urna ou apelido político citado na claim.
        uf: Sigla da UF com 2 letras (ex: 'SP', 'RS') para desambiguação.
        cargo: 'Deputado Federal' ou 'Senador' para filtragem de mandato.
        ano: Ano de referência da legislatura.
        parquet_path: Caminho para a base dimensional canônica local.
        threshold: Limiar mínimo de similaridade para matching fuzzy (padrão 85.0).
        delta: Margem máxima percentual de empate para declaração de ambiguidade (padrão 3.0).

    Returns:
        Dicionário estruturado conforme contrato resolve_politician.json.
    """
    # 1. Validação de entrada (T013)
    if not nome_busca or not isinstance(nome_busca, str):
        return _empty_response()

    nome_busca_clean = nome_busca.strip()
    if len(nome_busca_clean) < 2:
        return _empty_response()

    nome_norm = normalize_text(nome_busca_clean)
    if not nome_norm:
        return _empty_response()

    uf_clean = uf.strip().upper() if uf and isinstance(uf, str) else None
    cargo_clean = cargo.strip() if cargo and isinstance(cargo, str) else None

    # Obtém cache em memória (T008 / T011)
    cache = PoliticianCache.get_instance(parquet_path)
    if not cache.records:
        return _empty_response()

    # ==========================================================================
    # ESTÁGIO 1: EXACT MATCHING EM ÍNDICE HASH (O(1)) (T011)
    # ==========================================================================
    exact_matches: List[Dict[str, Any]] = []
    seen_keys = set()

    # Busca no índice de nome civil
    for match in cache.civil_index.get(nome_norm, []):
        key = (match.get("nome_civil"), match.get("uf"), match.get("cargo"))
        if key not in seen_keys:
            exact_matches.append(match)
            seen_keys.add(key)

    # Busca no índice de nome de urna
    for match in cache.urna_index.get(nome_norm, []):
        key = (match.get("nome_civil"), match.get("uf"), match.get("cargo"))
        if key not in seen_keys:
            exact_matches.append(match)
            seen_keys.add(key)

    if exact_matches:
        filtered = _filter_candidates(exact_matches, uf=uf_clean, cargo=cargo_clean)
        if len(filtered) == 1:
            return _format_response(filtered[0], match_score=100.0, ambiguous=False)
        elif len(filtered) > 1:
            # Múltiplos homônimos exatos
            return {
                **_empty_response(ambiguous=True),
                "candidatos_alternativos": [_format_candidate_summary(c) for c in filtered],
                "match_score": 100.0,
            }

    # ==========================================================================
    # ESTÁGIO 2: FUZZY MATCHING CONSERVADOR VIA RAPIDFUZZ (T012)
    # ==========================================================================
    scored_candidates: List[tuple[float, Dict[str, Any]]] = []

    for civil_norm, urna_norm, cand in cache.fuzzy_corpus:
        # Avalia similaridade máxima entre a busca e (nome_civil, nome_urna)
        score_civil = fuzz.token_sort_ratio(nome_norm, civil_norm)
        score_urna = fuzz.token_sort_ratio(nome_norm, urna_norm)
        best_score = max(score_civil, score_urna)

        # Bônus leve para partial matching se for substring perfeita
        if nome_norm in civil_norm or nome_norm in urna_norm:
            best_score = max(best_score, 90.0)

        if best_score >= threshold:
            scored_candidates.append((best_score, cand))

    if not scored_candidates:
        return _empty_response()

    # Ordena por maior score
    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    # Identifica o maior score obtido
    top_score = scored_candidates[0][0]

    # Agrupa candidatos no topo dentro da margem de empate (delta)
    cluster = [cand for score, cand in scored_candidates if (top_score - score) <= delta]

    # Aplica filtros discriminadores (UF, cargo) para desambiguação
    filtered_cluster = _filter_candidates(cluster, uf=uf_clean, cargo=cargo_clean)

    if len(filtered_cluster) == 1:
        return _format_response(filtered_cluster[0], match_score=top_score, ambiguous=False)
    elif len(filtered_cluster) > 1:
        # Permanece ambíguo
        return {
            **_empty_response(ambiguous=True),
            "candidatos_alternativos": [_format_candidate_summary(c) for c in filtered_cluster],
            "match_score": round(top_score, 2),
        }
    else:
        # Se os filtros eliminaram todos do cluster
        return _empty_response()

"""Tools do Grupo 6: Regras Institucionais e Disponibilidade de Dados (Base Curada).

Implementa as ferramentas analíticas baseadas em base de conhecimento normativo:
- 6.1 check_institutional_rule
- 6.2 check_data_source_coverage
Atende estritamente às diretrizes de AGENTS.md (evidência primária rastreável, neutralidade).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("Tools.Knowledge")

# Tópicos institucionais fechados para o Golden Dataset v1
INSTITUTIONAL_TOPICS: Tuple[str, ...] = (
    "calculo_cota_por_uf",
    "sabatina_stf",
    "votacao_simbolica",
    "teto_categoria_combustivel",
    "prestacao_contas_partido",
    "veto_presidencial",
    "lai_gratuidade",
    "cota_campanha_vs_mandato",
    "teto_gastos_campanha",
    "cota_compra_bens",
    "tramitacao_comissoes",
)

# Fontes primárias de dados oficiais mapeadas
DATA_SOURCES: Tuple[str, ...] = (
    "portal_transparencia",
    "tse_prestacao_contas",
    "camara_frequencia",
    "camara_notas_taquigraficas",
)

_DEFAULT_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# Caches em memória
_CACHED_RULES: Optional[Dict[str, Any]] = None
_CACHED_COVERAGE: Optional[Dict[str, Any]] = None


def _load_institutional_rules(base_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Carrega as regras institucionais a partir do arquivo JSON curado."""
    global _CACHED_RULES
    if _CACHED_RULES is not None and base_dir is None:
        return _CACHED_RULES

    knowledge_dir = Path(base_dir) if base_dir else _DEFAULT_KNOWLEDGE_DIR
    json_path = knowledge_dir / "institutional_rules.json"

    if not json_path.exists():
        logger.error("Arquivo de regras institucionais não encontrado em '%s'", json_path)
        return {}

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if base_dir is None:
        _CACHED_RULES = data
    return data


def _load_data_source_coverage(base_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Carrega o catálogo de disponibilidade de fontes de dados a partir do JSON curado."""
    global _CACHED_COVERAGE
    if _CACHED_COVERAGE is not None and base_dir is None:
        return _CACHED_COVERAGE

    knowledge_dir = Path(base_dir) if base_dir else _DEFAULT_KNOWLEDGE_DIR
    json_path = knowledge_dir / "data_source_coverage.json"

    if not json_path.exists():
        logger.error("Arquivo de cobertura de fontes não encontrado em '%s'", json_path)
        return {}

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if base_dir is None:
        _CACHED_COVERAGE = data
    return data


def check_institutional_rule(
    topico: str,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Consulta a base normativa curada para verificar regras institucionais ou procedimentais.

    Utilizada para responder a alegações sobre 'o que é permitido / como funciona' no
    regimento das casas legislativas, legislação eleitoral e normas de transparência.

    Args:
        topico: Identificador do tópico normativo (enum fechado).
        base_dir: Diretório alternativo para testes da base de conhecimento.

    Returns:
        Dicionário com a regra oficial, fundamentação e citação da fonte normativa:
        {
            "encontrado": bool,
            "topico": str,
            "resposta_resumida": Optional[str],
            "fonte_normativa": Optional[str],
            "fundamentacao": Optional[str],
            "veredito_regra": Optional[str],
        }

    Raises:
        ValueError: Se topico for nulo ou vazio.
    """
    if not topico or not isinstance(topico, str) or not topico.strip():
        raise ValueError("O parâmetro 'topico' é obrigatório e não pode ser vazio.")

    clean_topico = topico.strip().lower()
    rules = _load_institutional_rules(base_dir)

    if clean_topico in rules:
        item = rules[clean_topico]
        return {
            "encontrado": True,
            "topico": clean_topico,
            "resposta_resumida": item.get("resposta_resumida"),
            "fonte_normativa": item.get("fonte_normativa"),
            "fundamentacao": item.get("fundamentacao"),
            "veredito_regra": item.get("veredito_regra"),
        }

    return {
        "encontrado": False,
        "topico": clean_topico,
        "resposta_resumida": None,
        "fonte_normativa": None,
        "fundamentacao": None,
        "veredito_regra": None,
        "topicos_disponiveis": list(INSTITUTIONAL_TOPICS),
        "mensagem": f"Tópico '{clean_topico}' não catalogado na base de regras institucionais.",
    }


def check_data_source_coverage(
    fonte: str,
    tipo_dado: str,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Confirma se um determinado tipo de dado público é consultável na fonte oficial informada.

    Args:
        fonte: Enum da fonte de dados ('portal_transparencia', 'tse_prestacao_contas', etc.).
        tipo_dado: Texto curto identificando o recorte da informação.
        base_dir: Diretório alternativo para a base de conhecimento curada.

    Returns:
        Dicionário com status de disponibilidade, link de referência e base legal:
        {
            "encontrado": bool,
            "fonte": str,
            "tipo_dado": str,
            "disponivel": bool,
            "url_referencia": Optional[str],
            "base_legal": Optional[str],
            "observacao": str,
        }

    Raises:
        ValueError: Se fonte for inválida ou tipo_dado for vazio.
    """
    if not fonte or not isinstance(fonte, str):
        raise ValueError(f"Fonte '{fonte}' inválida. Use uma das opções: {DATA_SOURCES}")

    clean_fonte = fonte.strip().lower()
    if clean_fonte not in DATA_SOURCES:
        raise ValueError(
            f"Fonte '{fonte}' inválida. Fontes permitidas: {', '.join(DATA_SOURCES)}"
        )

    if not tipo_dado or not isinstance(tipo_dado, str) or not tipo_dado.strip():
        raise ValueError("O parâmetro 'tipo_dado' é obrigatório e não pode ser vazio.")

    clean_tipo = tipo_dado.strip().lower()
    coverage_data = _load_data_source_coverage(base_dir)

    source_info = coverage_data.get(clean_fonte, {})
    tipos_dados = source_info.get("tipos_dados", {})

    if clean_tipo in tipos_dados:
        item = tipos_dados[clean_tipo]
        return {
            "encontrado": True,
            "fonte": clean_fonte,
            "tipo_dado": clean_tipo,
            "disponivel": item.get("disponivel", False),
            "url_referencia": item.get("url_referencia"),
            "base_legal": item.get("base_legal"),
            "observacao": item.get("observacao", ""),
        }

    return {
        "encontrado": False,
        "fonte": clean_fonte,
        "tipo_dado": clean_tipo,
        "disponivel": False,
        "url_referencia": None,
        "base_legal": None,
        "observacao": f"Tipo de dado '{clean_tipo}' não catalogado para a fonte '{clean_fonte}'.",
        "tipos_disponiveis": list(tipos_dados.keys()),
    }

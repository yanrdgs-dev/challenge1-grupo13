"""Catálogo de tools do roteador: tools de regra institucional separadas das de dado (regra 4)."""

import json
from pathlib import Path

from scripts.demo_qwen_tool_routing import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG
from src.tools.knowledge_tools import DATA_SOURCES, INSTITUTIONAL_TOPICS

KNOWLEDGE = Path(__file__).resolve().parents[1] / "src" / "tools" / "knowledge"


def _tool(name):
    return next(t["function"] for t in TOOLS_CATALOG if t["function"]["name"] == name)


def test_curated_base_and_topic_list_are_consistent():
    rules = json.loads((KNOWLEDGE / "institutional_rules.json").read_text())
    assert set(rules) == set(INSTITUTIONAL_TOPICS)
    coverage = json.loads((KNOWLEDGE / "data_source_coverage.json").read_text())
    assert set(coverage) == set(DATA_SOURCES)


def test_catalog_has_the_institutional_tools_alongside_the_data_tools():
    names = [t["function"]["name"] for t in TOOLS_CATALOG]
    assert len(names) == len(set(names))
    assert {"check_institutional_rule", "check_data_source_coverage"} <= set(names)
    assert {"get_top_ceap_spender", "check_parliamentary_expenses", "get_proposition_vote_result"} <= set(names)


def test_institutional_rule_topic_is_a_closed_enum_of_the_curated_base():
    params = _tool("check_institutional_rule")["parameters"]
    assert params["required"] == ["topico"]
    assert set(params["properties"]["topico"]["enum"]) == set(INSTITUTIONAL_TOPICS)


def test_data_source_coverage_uses_closed_enums_from_the_curated_base():
    params = _tool("check_data_source_coverage")["parameters"]
    assert set(params["required"]) == {"fonte", "tipo_dado"}
    assert set(params["properties"]["fonte"]["enum"]) == set(DATA_SOURCES)

    coverage = json.loads((KNOWLEDGE / "data_source_coverage.json").read_text())
    all_types = {t for source in coverage.values() for t in source["tipos_dados"]}
    assert set(params["properties"]["tipo_dado"]["enum"]) == all_types


def test_normative_tools_are_described_as_rules_not_transactional_data():
    """Regra 4: o roteador precisa distinguir 'o que aconteceu' de 'o que é permitido/como funciona'."""
    rule = _tool("check_institutional_rule")["description"].lower()
    assert "permitido" in rule and "funciona" in rule
    for transactional in ("get_top_ceap_spender", "check_parliamentary_expenses", "get_proposition_vote_result"):
        assert "permitido" not in _tool(transactional)["description"].lower() or transactional == "list_expense_categories"


def test_router_prompt_explains_when_to_use_each_normative_tool():
    assert "check_institutional_rule" in ROUTER_SYSTEM_PROMPT
    assert "check_data_source_coverage" in ROUTER_SYSTEM_PROMPT

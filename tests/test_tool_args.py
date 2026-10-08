"""Validação e normalização dos parâmetros de tool contra o schema do catálogo (3.6)."""

import pytest

from src.services.tool_args import validate_tool_args


def ok(tool, args):
    normalized, problem = validate_tool_args(tool, args)
    assert problem is None, problem
    return normalized


def bad(tool, args):
    normalized, problem = validate_tool_args(tool, args)
    assert problem, f"esperava erro para {tool} {args}"
    return problem


# ------------------------------- obrigatórios ------------------------------- #

def test_missing_required_param_is_reported_by_name():
    problem = bad("check_parliamentary_expenses", {"casa": "camara", "categoria": "Alimentação"})
    assert "ano" in problem and "obrigat" in problem.lower()


def test_all_missing_required_params_are_listed():
    problem = bad("check_data_source_coverage", {})
    assert "fonte" in problem and "tipo_dado" in problem


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_values_count_as_missing(empty):
    assert "casa" in bad("get_top_ceap_spender", {"casa": empty, "ano": 2023})


def test_valid_arguments_pass_unchanged():
    args = {"casa": "camara", "ano": 2023, "top_n": 3}
    assert ok("get_top_ceap_spender", args) == args


def test_optional_params_may_be_absent():
    assert ok("list_expense_categories", {"casa": "senado"}) == {"casa": "senado"}


# ----------------------------------- enums ----------------------------------- #

@pytest.mark.parametrize("raw", ["Camara", "CÂMARA", " camara ", "câmara"])
def test_enum_is_matched_ignoring_case_accents_and_spaces(raw):
    assert ok("get_top_ceap_spender", {"casa": raw, "ano": 2023})["casa"] == "camara"


def test_invalid_enum_value_lists_the_allowed_ones():
    problem = bad("get_top_ceap_spender", {"casa": "assembleia", "ano": 2023})
    assert "casa" in problem and "camara" in problem and "senado" in problem


def test_invented_institutional_topic_is_rejected():
    problem = bad("check_institutional_rule", {"topico": "topico_inventado"})
    assert "topico" in problem


def test_valid_institutional_topic_passes():
    assert ok("check_institutional_rule", {"topico": "sabatina_stf"}) == {"topico": "sabatina_stf"}


# ---------------------------------- tipos ---------------------------------- #

@pytest.mark.parametrize("raw, expected", [("2023", 2023), (" 2023 ", 2023), (2023.0, 2023), (2023, 2023)])
def test_integer_params_are_coerced(raw, expected):
    assert ok("get_top_ceap_spender", {"casa": "camara", "ano": raw})["ano"] == expected


@pytest.mark.parametrize("raw", ["dois mil", "2023.5", 2023.5, True, [2023]])
def test_non_integer_values_for_integer_params_are_rejected(raw):
    assert "ano" in bad("get_top_ceap_spender", {"casa": "camara", "ano": raw})


@pytest.mark.parametrize("raw, expected", [("true", True), ("False", False), (True, True)])
def test_boolean_params_are_coerced(raw, expected):
    assert ok("list_expense_categories", {"casa": "camara", "incluir_exemplos": raw})["incluir_exemplos"] is expected


def test_invalid_boolean_is_rejected():
    assert "incluir_exemplos" in bad("list_expense_categories", {"casa": "camara", "incluir_exemplos": "talvez"})


# ------------------------------- robustez geral ------------------------------- #

def test_does_not_mutate_the_input():
    args = {"casa": "Camara", "ano": "2023"}
    ok("get_top_ceap_spender", args)
    assert args == {"casa": "Camara", "ano": "2023"}


def test_unknown_params_are_kept_untouched():
    assert ok("get_top_ceap_spender", {"casa": "camara", "ano": 2023, "extra": "x"})["extra"] == "x"


def test_unknown_tool_is_left_to_the_dispatcher():
    assert validate_tool_args("tool_inexistente", {"a": 1}) == ({"a": 1}, None)


@pytest.mark.parametrize("raw", [None, "texto", [1, 2]])
def test_non_dict_arguments_are_rejected(raw):
    _, problem = validate_tool_args("get_top_ceap_spender", raw)
    assert problem


def test_every_catalog_tool_has_its_required_params_checked():
    from scripts.demo_qwen_tool_routing import TOOLS_CATALOG

    for tool in TOOLS_CATALOG:
        fn = tool["function"]
        required = fn["parameters"].get("required", [])
        if required:
            assert bad(fn["name"], {}), fn["name"]

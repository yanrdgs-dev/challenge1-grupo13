"""Testes unitários para Contratos e Interfaces Pydantic para Tools (Task 2.3).

Cobre:
1. Esquemas em src/schemas/tools.py.
2. Modelo TSEExpensesInput validando politician_name, year e state opcional.
3. Modelo CamaraVoteInput validando politician_name e bill_id.
4. Modelo ToolExecutionResult contendo status, data, source_url e retrieved_at.
5. Validações estritas de erro levantando ValidationError para parâmetros vazios ou inválidos.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.schemas.tools import (
    CamaraVoteInput,
    DataSourceCoverageInput,
    InstitutionalRuleInput,
    ResolvePoliticianInput,
    ResolvePropositionInput,
    ToolExecutionResult,
    TopCEAPSpenderInput,
    TSEExpensesInput,
)


# ---------------------------------------------------------------------------
# 1. Testes de TSEExpensesInput
# ---------------------------------------------------------------------------

def test_tse_expenses_input_valid_with_state():
    """Valida instanciação bem-sucedida de TSEExpensesInput com estado."""
    model = TSEExpensesInput(
        politician_name="Pompeo de Mattos",
        year=2022,
        state="RS",
    )

    assert model.politician_name == "Pompeo de Mattos"
    assert model.year == 2022
    assert model.state == "RS"


def test_tse_expenses_input_valid_without_state():
    """Valida instanciação bem-sucedida de TSEExpensesInput com state opcional omitido."""
    model = TSEExpensesInput(
        politician_name="Luiz Inácio Lula da Silva",
        year=2022,
    )

    assert model.politician_name == "Luiz Inácio Lula da Silva"
    assert model.year == 2022
    assert model.state is None


def test_tse_expenses_input_normalizes_state():
    """Valida normalização de sigla de UF para maiúsculas e sem espaços."""
    model = TSEExpensesInput(
        politician_name="Tarcísio de Freitas",
        year=2022,
        state="  sp  ",
    )
    assert model.state == "SP"


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        "   ",
        None,
    ],
)
def test_tse_expenses_input_empty_politician_name_raises_validation_error(invalid_name):
    """Valida que nome de político vazio ou composto apenas por espaços levanta ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TSEExpensesInput(
            politician_name=invalid_name,
            year=2022,
        )

    errors = exc_info.value.errors()
    assert any(err["loc"] == ("politician_name",) for err in errors)


def test_tse_expenses_input_missing_required_fields():
    """Valida que a omissão de campos obrigatórios levanta ValidationError."""
    with pytest.raises(ValidationError):
        TSEExpensesInput(politician_name="Afonso")  # Falta year

    with pytest.raises(ValidationError):
        TSEExpensesInput(year=2022)  # Falta politician_name


@pytest.mark.parametrize("invalid_year", [-1, 0, 1800, 3000, "ano_invalido"])
def test_tse_expenses_input_invalid_year_raises_validation_error(invalid_year):
    """Valida que anos fora do escopo plausível da República ou não numéricos levantam ValidationError."""
    with pytest.raises(ValidationError):
        TSEExpensesInput(
            politician_name="Candidato Teste",
            year=invalid_year,
        )


# ---------------------------------------------------------------------------
# 2. Testes de CamaraVoteInput
# ---------------------------------------------------------------------------

def test_camara_vote_input_valid():
    """Valida instanciação bem-sucedida de CamaraVoteInput."""
    model = CamaraVoteInput(
        politician_name="Tabata Amaral",
        bill_id="PL 2630/2020",
    )

    assert model.politician_name == "Tabata Amaral"
    assert model.bill_id == "PL 2630/2020"


@pytest.mark.parametrize(
    "empty_politician_name",
    ["", "   ", "\t", "\n"],
)
def test_camara_vote_input_empty_politician_name_raises_validation_error(empty_politician_name):
    """Valida que politician_name vazio levanta ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        CamaraVoteInput(
            politician_name=empty_politician_name,
            bill_id="PEC 45/2019",
        )

    errors = exc_info.value.errors()
    assert any(err["loc"] == ("politician_name",) for err in errors)


@pytest.mark.parametrize(
    "empty_bill_id",
    ["", "   ", "\t", "\n"],
)
def test_camara_vote_input_empty_bill_id_raises_validation_error(empty_bill_id):
    """Valida que bill_id vazio levanta ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        CamaraVoteInput(
            politician_name="Arthur Lira",
            bill_id=empty_bill_id,
        )

    errors = exc_info.value.errors()
    assert any(err["loc"] == ("bill_id",) for err in errors)


def test_camara_vote_input_strips_whitespace():
    """Valida que espaços residuais nas bordas são higienizados."""
    model = CamaraVoteInput(
        politician_name="  Rodrigo Pacheco  ",
        bill_id="  PL 1234/2023  ",
    )
    assert model.politician_name == "Rodrigo Pacheco"
    assert model.bill_id == "PL 1234/2023"


# ---------------------------------------------------------------------------
# 3. Testes de ToolExecutionResult (Modelo Unificado de Saída)
# ---------------------------------------------------------------------------

def test_tool_execution_result_valid_explicit():
    """Valida instanciação de ToolExecutionResult com todos os campos explícitos."""
    dt = datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc)
    result = ToolExecutionResult(
        status="success",
        data={"total_gasto": 540000.0, "ranking": 1},
        source_url="https://dadosabertos.camara.leg.br/api/v2/deputados/73486/despesas",
        retrieved_at=dt,
    )

    assert result.status == "success"
    assert result.data == {"total_gasto": 540000.0, "ranking": 1}
    assert result.source_url == "https://dadosabertos.camara.leg.br/api/v2/deputados/73486/despesas"
    assert result.retrieved_at == dt


def test_tool_execution_result_defaults_retrieved_at():
    """Valida que retrieved_at possui default dinâmico para a data/hora atual em UTC."""
    result = ToolExecutionResult(
        status="not_found",
        data={"encontrado": False},
        source_url="local://parquet/dim_politicos",
    )

    assert result.status == "not_found"
    assert isinstance(result.retrieved_at, datetime)
    assert result.data["encontrado"] is False


@pytest.mark.parametrize(
    "invalid_status",
    ["", "   ", None],
)
def test_tool_execution_result_empty_status_raises_validation_error(invalid_status):
    """Valida que status vazio levanta ValidationError."""
    with pytest.raises(ValidationError):
        ToolExecutionResult(
            status=invalid_status,
            data={"teste": 1},
            source_url="https://dadosabertos.tse.jus.br",
        )


def test_tool_execution_result_invalid_data_type_raises_validation_error():
    """Valida que data deve ser obrigatoriamente um dicionário."""
    with pytest.raises(ValidationError):
        ToolExecutionResult(
            status="success",
            data="string_invalida_nao_dict",  # Deveria ser dict
            source_url="https://tse.jus.br",
        )


def test_tool_execution_result_serialization():
    """Valida conversão para dicionário e compatibilidade de serialização JSON."""
    result = ToolExecutionResult(
        status="success",
        data={"qtd": 5},
        source_url="https://dadosabertos.camara.leg.br",
    )
    data_dict = result.model_dump()

    assert data_dict["status"] == "success"
    assert data_dict["data"] == {"qtd": 5}
    assert data_dict["source_url"] == "https://dadosabertos.camara.leg.br"
    assert isinstance(data_dict["retrieved_at"], datetime)


# ---------------------------------------------------------------------------
# 4. Testes de Esquemas Complementares do Ecossistema de Tools
# ---------------------------------------------------------------------------

def test_top_ceap_spender_input():
    """Valida TopCEAPSpenderInput."""
    model = TopCEAPSpenderInput(casa="camara", ano=2023, top_n=3)
    assert model.casa == "camara"
    assert model.ano == 2023
    assert model.top_n == 3

    # Default de top_n é 1
    default_model = TopCEAPSpenderInput(casa="senado", ano=2023)
    assert default_model.top_n == 1

    # Validação de casa inválida
    with pytest.raises(ValidationError):
        TopCEAPSpenderInput(casa="judiciario", ano=2023)


def test_resolve_politician_input():
    """Valida ResolvePoliticianInput."""
    model = ResolvePoliticianInput(nome_busca="Pompeo de Mattos", uf="RS")
    assert model.nome_busca == "Pompeo de Mattos"
    assert model.uf == "RS"

    with pytest.raises(ValidationError):
        ResolvePoliticianInput(nome_busca="")


def test_institutional_rule_input():
    """Valida InstitutionalRuleInput."""
    model = InstitutionalRuleInput(topico="sabatina_stf")
    assert model.topico == "sabatina_stf"

    with pytest.raises(ValidationError):
        InstitutionalRuleInput(topico="   ")

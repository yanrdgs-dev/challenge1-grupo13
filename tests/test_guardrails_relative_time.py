"""Regra 3: referência temporal relativa que a alegação não ancora ('atuais', 'última sabatina') é INCONCLUSIVO."""

import pytest

from src.guardrails.actions import check_input_specificity


@pytest.mark.parametrize("claim", [
    "Os atuais membros titulares da CCJ da Câmara são todos do mesmo partido.",
    "Senadores votaram contra o indicado ao STF na última sabatina.",
    "O atual presidente da Câmara é do PL.",
    "O atual relator do projeto é do PT.",
    "Na última votação do Plenário, nenhum deputado votou contra.",
])
def test_unanchored_relative_time_is_blocked_before_any_tool(claim):
    result = check_input_specificity(claim)
    assert result["is_valid"] is False
    assert result["verdict"] == "INCONCLUSIVO"
    assert result["rule_matched"] == "guarda_de_especificidade"
    assert "relativ" in result["reason"].lower()


@pytest.mark.parametrize("claim", [
    "Em 2023, o deputado que mais gastou a cota parlamentar foi Pompeo de Mattos.",
    "Em 2022, Lula declarou ao TSE bens que somam mais de 7 milhões de reais.",
    "A PEC é promulgada sem sanção presidencial.",
    "A atualização dos dados do TSE ocorre diariamente.",          # 'atualização' não é tempo relativo
    "Existe ao menos um projeto de lei na Câmara sobre isenção do imposto de renda.",
    # relativas que a data de hoje resolve: seguem para o roteamento
    "Medidas provisórias caducaram no Senado durante a atual legislatura.",
    "Neste ano, o deputado que mais gastou a cota parlamentar foi Fulano.",
    "Atualmente o deputado Fraga gastou mais de mil reais de combustível.",
])
def test_anchored_or_timeless_claims_are_not_blocked(claim):
    assert check_input_specificity(claim)["is_valid"] is True

"""Testes unitários para Input Rails (Regras 3 e 6 de AGENTS.md).

Ciclo TDD - Etapa RED.
Valida bloqueio antecipado de boatos, subespecificação, eventos futuros e opiniões partidárias.
"""

import time
import pytest
from src.guardrails.actions import check_input_specificity, check_input_neutrality


def test_input_rail_blocks_rumours_from_social_media():
    """Valida que boatos de redes sociais (Golden Dataset ID 27) geram INCONCLUSIVO sem chamar LLM."""
    claim = "Nas redes sociais estão dizendo que um deputado usou a cota parlamentar para pagar despesas pessoais da família."
    res = check_input_specificity(claim)

    assert res["is_valid"] is False
    assert res["verdict"] == "INCONCLUSIVO"
    assert "Regra 3" in res["reason"] or "subespecificada" in res["reason"].lower()
    assert "redes sociais" in res["reason"].lower() or "boato" in res["reason"].lower()


def test_input_rail_blocks_unanchored_temporal_and_vague_entity():
    """Valida claims com deputado genérico e temporalidade relativa não ancorada (IDs 25 e 29)."""
    claim_25 = "Um deputado gastou uma quantia muito alta com passagem aérea usando a cota parlamentar recentemente."
    res_25 = check_input_specificity(claim_25)
    assert res_25["is_valid"] is False
    assert res_25["verdict"] == "INCONCLUSIVO"

    claim_29 = "Um senador teria gastado muito dinheiro público com contratos de consultoria no ano passado."
    res_29 = check_input_specificity(claim_29)
    assert res_29["is_valid"] is False
    assert res_29["verdict"] == "INCONCLUSIVO"


def test_input_rail_blocks_future_or_hypothetical_events():
    """Valida que evento futuro ou ainda não ocorrido (ID 28) gera INCONCLUSIVO."""
    claim_28 = "A Câmara dos Deputados deve votar em breve um projeto de lei sobre inteligência artificial."
    res = check_input_specificity(claim_28)
    assert res["is_valid"] is False
    assert res["verdict"] == "INCONCLUSIVO"
    assert "futuro" in res["reason"].lower() or "em breve" in res["reason"].lower() or "subespecificada" in res["reason"].lower()


def test_input_rail_blocks_vague_propositions_and_press_comments():
    """Valida proposição sem número e comentários da imprensa (IDs 26 e 30)."""
    claim_26 = "Um grupo de senadores votou contra uma proposta polêmica sobre segurança pública que estava sendo discutida no Senado."
    res_26 = check_input_specificity(claim_26)
    assert res_26["is_valid"] is False
    assert res_26["verdict"] == "INCONCLUSIVO"

    claim_30 = "Segundo comentários na imprensa, houve uma votação apertada na Câmara dos Deputados sobre um projeto ligado à área fiscal."
    res_30 = check_input_specificity(claim_30)
    assert res_30["is_valid"] is False
    assert res_30["verdict"] == "INCONCLUSIVO"


def test_input_rail_blocks_partisan_opinion_or_bias():
    """Valida neutralidade (Regra 6): perguntas opinativas ou de preferência partidária são interceptadas."""
    query = "Qual é o melhor partido político do Brasil para se filiar?"
    res = check_input_neutrality(query)
    assert res["is_valid"] is False
    assert "neutr" in res["reason"].lower() or "opinião" in res["reason"].lower()


def test_input_rail_allows_valid_specific_claim():
    """Valida que uma claim factual com entidade identificada e ano passa pelo Input Rail (ID 1)."""
    claim = "Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS)."
    res = check_input_specificity(claim)
    assert res["is_valid"] is True
    assert res["verdict"] is None


def test_input_rail_latency_is_under_15ms():
    """Garante que a triagem do Input Rail executa em menos de 15ms."""
    claim = "Nas redes sociais estão dizendo que um deputado fez algo recentemente."
    start = time.perf_counter()
    _ = check_input_specificity(claim)
    duration_ms = (time.perf_counter() - start) * 1000.0

    assert duration_ms < 15.0, f"Latência de {duration_ms:.2f}ms ultrapassou o teto de 15ms"


def test_rumour_guard_blocks_social_media_as_a_source_but_not_as_the_subject():
    """Claim sobre as redes sociais que o candidato registrou no TSE não é boato; "nas redes sociais" como fonte é."""
    subject = "O perfil de Instagram fulano está entre as redes sociais que o candidato registrou no TSE em 2022."
    assert check_input_specificity(subject)["is_valid"] is True
    for source in (
        "Nas redes sociais dizem que o deputado Fulano votou contra o PL 2630.",
        "Segundo as redes sociais, o senador gastou a cota inteira.",
        "Uma postagem pelas redes sociais afirma que o deputado viajou.",
    ):
        assert check_input_specificity(source)["is_valid"] is False, source

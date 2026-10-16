"""Votações de uma proposição: 117 das 123 da PEC 221/2019 são requerimentos; o juiz precisa das votações da própria PEC.

A descrição da Câmara já traz o placar ("Sim: 472; Não: 22; Total: 494"): ele sai como número, não como texto solto.
"""

import pytest

from src.tools.votacoes_api import focus_votacoes, parse_vote_counts

PEC_1T = {"id_votacao": "2233802-424", "data": "2026-05-27", "aprovado": True,
          "tipo_votacao": "Aprovada, em primeiro turno, a Proposta de Emenda à Constituição nº 221, de 2019. Sim: 472; Não: 22; Total: 494."}
PEC_2T = {"id_votacao": "2233802-438", "data": "2026-05-27", "aprovado": True,
          "tipo_votacao": "Aprovada, em segundo turno, a Proposta de Emenda à Constituição n° 221, de 2019. . Sim: 461; Não: 19; Total: 480."}
REDACAO = {"id_votacao": "2233802-440", "data": "2026-05-27", "aprovado": True,
           "tipo_votacao": "Aprovada a Redação Final assinada pelo relator, Dep. Leo Prates (REPUBLIC/BA)."}


def requerimento(i, data="2026-05-26"):
    return {"id_votacao": f"2233802-{i}", "data": data, "aprovado": True,
            "tipo_votacao": f"Aprovado o Requerimento nº {3000 + i}/2026, dos Senhores Líderes."}


# ------------------------------------ placar dentro da descrição ------------------------------------ #

@pytest.mark.parametrize("text, expected", [
    ("Aprovada, em primeiro turno, a PEC nº 221, de 2019. Sim: 472; Não: 22; Total: 494.",
     {"votos_sim": 472, "votos_nao": 22, "votos_total": 494}),
    ("Aprovado o Requerimento de Urgência (Art. 154 do RICD). Sim: 238; não: 192; total: 430.",
     {"votos_sim": 238, "votos_nao": 192, "votos_total": 430}),
    ("Rejeitado o requerimento. SIM: 10; NÃO: 300; Abstenção: 2; Total: 312.",
     {"votos_sim": 10, "votos_nao": 300, "votos_abstencao": 2, "votos_total": 312}),
    ("Aprovada a Redação Final assinada pelo relator.", {}),
    ("", {}),
    (None, {}),
])
def test_parse_vote_counts_reads_the_tally_written_in_the_description(text, expected):
    assert parse_vote_counts(text) == expected


# ------------------------------------ foco nas votações da proposição ------------------------------------ #

def test_requerimentos_are_left_out_when_the_claim_is_about_the_proposition_itself():
    votes = [requerimento(i) for i in range(10)] + [PEC_1T, PEC_2T, REDACAO]
    focused, omitted = focus_votacoes(votes, "Quantos votos tivemos na PEC 221/2019?")
    assert {v["id_votacao"] for v in focused} == {"2233802-424", "2233802-438", "2233802-440"}
    assert omitted == 10


def test_requerimentos_are_kept_when_the_claim_asks_about_them():
    votes = [requerimento(1), PEC_1T]
    for claim in ("O requerimento de urgência da PEC foi aprovado?", "A urgência do PL 2630 foi aprovada?",
                  "Houve destaque na votação da PEC?"):
        focused, omitted = focus_votacoes(votes, claim)
        assert len(focused) == 2 and omitted == 0, claim


def test_when_only_requerimentos_exist_they_are_all_kept_so_the_evidence_is_never_empty():
    votes = [requerimento(1), requerimento(2)]
    focused, omitted = focus_votacoes(votes, "Quantos votos tivemos na PEC 221/2019?")
    assert len(focused) == 2 and omitted == 0


def test_focused_votes_carry_the_parsed_counts_and_are_sorted_newest_first():
    older = {**PEC_1T, "id_votacao": "x", "data": "2026-05-26"}
    focused, _ = focus_votacoes([older, PEC_2T], "Quantos votos teve a PEC 221/2019?")
    assert [v["id_votacao"] for v in focused] == ["2233802-438", "x"]
    assert (focused[0]["votos_sim"], focused[0]["votos_nao"], focused[0]["votos_total"]) == (461, 19, 480)
    assert "votos_sim" not in focus_votacoes([REDACAO], "q")[0][0]


def test_same_day_votes_are_ordered_by_id_so_the_latest_round_comes_first():
    focused, _ = focus_votacoes([PEC_1T, PEC_2T, REDACAO], "Quantos votos teve a PEC?")
    assert [v["id_votacao"] for v in focused] == ["2233802-440", "2233802-438", "2233802-424"]


def test_the_list_is_capped_and_the_cut_is_reported():
    votes = [{**PEC_1T, "id_votacao": f"p-{i:03d}", "data": f"2026-01-{i % 28 + 1:02d}"} for i in range(40)]
    focused, omitted = focus_votacoes(votes, "q", limit=12)
    assert len(focused) == 12 and omitted == 28


def test_input_is_not_mutated():
    votes = [dict(PEC_1T), requerimento(1)]
    focus_votacoes(votes, "Quantos votos teve a PEC?")
    assert "votos_sim" not in votes[0] and len(votes) == 2

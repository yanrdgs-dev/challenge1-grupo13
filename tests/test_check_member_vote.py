"""check_member_vote: o voto de um parlamentar numa proposição ("Nikolas Ferreira votou contra a PEC da escala 6x1").

Regras 2 e 3: o parlamentar e a proposição só chegam ao dado pelo ID canônico dos resolvedores; sem resolução única de
qualquer um dos dois, nenhuma tool de votação roda. A Casa vem do cargo do parlamentar resolvido, não do LLM.
Rede sempre mockada.
"""

from unittest.mock import patch

import pytest

from src.services import router_service
from src.services.router_service import execute_tool
from src.services.tool_args import validate_tool_args
from src.services.tool_catalog import TOOLS_CATALOG
from src.tools.http_client import HttpNetworkError

NIKOLAS = {"sq_candidato": 1, "ideCadastro": 209787, "cod_senador": None, "nome_civil": "NIKOLAS FERREIRA DE OLIVEIRA",
           "nome_urna": "Nikolas Ferreira", "casa": "Câmara dos Deputados", "cargo": "Deputado Federal", "uf": "MG",
           "partido": "PL", "ambiguous": False, "candidatos_alternativos": [], "match_score": 100.0}
DAMARES = {**NIKOLAS, "ideCadastro": None, "cod_senador": 6335, "nome_urna": "Damares Alves", "casa": "Senado Federal",
           "cargo": "Senador", "uf": "DF", "partido": "REPUBLICANOS"}
NOT_FOUND = {**{k: None for k in NIKOLAS}, "ambiguous": False, "candidatos_alternativos": []}
AMBIGUOUS = {**NOT_FOUND, "ambiguous": True, "candidatos_alternativos": [{"uf": "DF"}, {"uf": "ES"}]}
PEC = {"id_proposicao": 2233802, "sigla_tipo": "PEC", "numero": 221, "ano": 2019, "casa": "camara",
       "ementa": "Altera a Constituição.", "ambiguous": False, "candidatos": [], "match_score": 100.0,
       "registros_equivalentes": []}
PEC_AMBIGUOUS = {**PEC, "id_proposicao": None, "ambiguous": True, "candidatos": [{"id_proposicao": 1}, {"id_proposicao": 2}]}
PEC_NOT_FOUND = {**PEC, "id_proposicao": None}
VOTACOES = [
    {"id_votacao": "2233802-438", "data": "2026-05-27", "tipo_votacao": "Aprovada a PEC em primeiro turno. Sim: 472; não: 22.", "aprovado": True},
    {"id_votacao": "2233802-500", "data": "2026-06-10", "tipo_votacao": "Aprovada a PEC em segundo turno. Sim: 461; não: 19.", "aprovado": True},
    {"id_votacao": "2233802-9", "data": "2026-05-20", "tipo_votacao": "Aprovado o Requerimento de urgência.", "aprovado": True},
]
ARGS = {"parlamentar": "Nikolas Ferreira", "sigla_tipo": "PEC", "numero": 221, "ano": 2019}
CLAIM = "Nikolas Ferreira votou contra a PEC 221/2019."


def _vote(opcao="sim", voto="Sim", registrado=True):
    return {"registrado": registrado, "voto": voto if registrado else None, "opcao": opcao if registrado else None,
            "nome": "Nikolas Ferreira", "partido": "PL", "uf": "MG", "total_votos": 480, "votacao_nominal": True}


class Tools:
    def __init__(self, politician=NIKOLAS, proposition=PEC, votacoes=VOTACOES, member_vote=None):
        self.politician = patch.object(router_service, "resolve_politician", return_value=politician)
        self.proposition = patch.object(router_service, "resolve_proposition", return_value=proposition)
        self.votes = patch.object(router_service, "get_proposition_vote_result", return_value=[dict(v) for v in votacoes])
        self.member = patch.object(router_service, "get_member_vote", side_effect=member_vote or (lambda **kw: _vote()))

    def __enter__(self):
        self.m = [p.start() for p in (self.politician, self.proposition, self.votes, self.member)]
        return self

    def __exit__(self, *exc):
        for p in (self.politician, self.proposition, self.votes, self.member):
            p.stop()

    politician_mock = property(lambda self: self.m[0])
    proposition_mock = property(lambda self: self.m[1])
    votes_mock = property(lambda self: self.m[2])
    member_mock = property(lambda self: self.m[3])


# ------------------------------------------------------------ catálogo e validação

def test_the_tool_is_in_the_catalog_and_only_the_member_is_required():
    spec = next(t for t in TOOLS_CATALOG if t["function"]["name"] == "check_member_vote")["function"]
    assert spec["parameters"]["required"] == ["parlamentar"]
    assert {"sigla_tipo", "numero", "ano", "termo_busca", "uf"} <= set(spec["parameters"]["properties"])
    assert "id_votacao" not in spec["parameters"]["properties"]      # IDs nunca vêm do LLM (regra 2)


def test_member_is_required_by_the_argument_validation():
    _, problem = validate_tool_args("check_member_vote", {"sigla_tipo": "PEC", "numero": 221})
    assert problem and "parlamentar" in problem


# ------------------------------------------------------------ caminho feliz

def test_happy_path_resolves_both_entities_then_reads_the_members_vote_in_each_main_vote():
    with Tools() as t:
        evidence = execute_tool("check_member_vote", ARGS)
    assert t.politician_mock.call_args.kwargs["nome_busca"] == "Nikolas Ferreira"
    assert t.proposition_mock.call_args.kwargs["casa"] == "camara"      # a Casa vem do cargo do parlamentar resolvido
    assert t.votes_mock.call_args.kwargs == {"id_proposicao": "2233802", "casa": "camara"}
    ids = [c.kwargs["id_votacao"] for c in t.member_mock.call_args_list]
    assert ids == ["2233802-500", "2233802-438"]                         # só as da proposição, mais recente primeiro
    assert all(c.kwargs["id_parlamentar"] == "209787" and c.kwargs["casa"] == "camara" for c in t.member_mock.call_args_list)
    assert [v["opcao"] for v in evidence["votos"]] == ["sim", "sim"]
    assert evidence["parlamentar"]["nome_urna"] == "Nikolas Ferreira" and evidence["parlamentar"]["uf"] == "MG"
    assert evidence["proposicao"]["numero"] == 221 and evidence["total_votacoes"] == 3 and evidence["votacoes_omitidas"] == 1


def test_senator_uses_cod_senador_and_the_senate_side_of_the_proposition():
    with Tools(politician=DAMARES, proposition={**PEC, "casa": "senado", "id_proposicao": 174386}) as t:
        execute_tool("check_member_vote", {**ARGS, "parlamentar": "Damares Alves"})
    assert t.proposition_mock.call_args.kwargs["casa"] == "senado"
    assert all(c.kwargs["id_parlamentar"] == "6335" and c.kwargs["casa"] == "senado" for c in t.member_mock.call_args_list)


def test_each_row_keeps_the_vote_the_description_and_whether_the_member_was_registered():
    answers = iter([_vote("nao", "Não"), _vote(registrado=False)])
    with Tools(member_vote=lambda **kw: next(answers)):
        evidence = execute_tool("check_member_vote", ARGS)
    first, second = evidence["votos"]
    assert first["voto"] == "Não" and first["opcao"] == "nao" and first["registrado"] is True
    assert "segundo turno" in first["tipo_votacao"] and first["data"] == "2026-06-10" and first["aprovado"] is True
    assert second["registrado"] is False and second["voto"] is None


def test_at_most_six_votes_are_read_and_the_rest_is_reported_as_omitted():
    many = [{"id_votacao": f"v{i}", "data": f"2026-01-{i:02d}", "tipo_votacao": f"Votação do texto {i}", "aprovado": True}
            for i in range(1, 11)]
    with Tools(votacoes=many) as t:
        evidence = execute_tool("check_member_vote", ARGS)
    assert t.member_mock.call_count == 6 and len(evidence["votos"]) == 6
    assert evidence["total_votacoes"] == 10 and evidence["votacoes_omitidas"] == 4


def test_a_failed_vote_lookup_is_kept_as_an_error_row_and_the_others_survive():
    def flaky(**kw):
        if kw["id_votacao"] == "2233802-500":
            raise HttpNetworkError("timeout")
        return _vote()
    with Tools(member_vote=flaky):
        evidence = execute_tool("check_member_vote", ARGS)
    assert "erro" in evidence["votos"][0] and evidence["votos"][1]["opcao"] == "sim"


# ------------------------------------------------------------ entidade não encontrada ou ambígua (regras 2 e 3)

@pytest.mark.parametrize("politician,ambiguous", [(NOT_FOUND, False), (AMBIGUOUS, True)])
def test_unresolved_member_never_reaches_any_vote_tool(politician, ambiguous):
    with Tools(politician=politician) as t:
        evidence = execute_tool("check_member_vote", ARGS)
    assert evidence["status"] == "entidade_nao_resolvida" and evidence["ambiguous"] is ambiguous
    assert evidence["parlamentar_informado"] == "Nikolas Ferreira"
    t.proposition_mock.assert_not_called(); t.votes_mock.assert_not_called(); t.member_mock.assert_not_called()


@pytest.mark.parametrize("proposition,ambiguous", [(PEC_NOT_FOUND, False), (PEC_AMBIGUOUS, True)])
def test_unresolved_proposition_never_reaches_the_vote_tools(proposition, ambiguous):
    with Tools(proposition=proposition) as t:
        evidence = execute_tool("check_member_vote", ARGS)
    assert evidence["status"] == "entidade_nao_resolvida" and evidence["ambiguous"] is ambiguous
    assert evidence["parlamentar"]["nome_urna"] == "Nikolas Ferreira"     # o que já foi resolvido não se perde
    t.votes_mock.assert_not_called(); t.member_mock.assert_not_called()


def test_without_any_way_to_identify_the_proposition_nothing_is_resolved():
    with Tools() as t:
        evidence = execute_tool("check_member_vote", {"parlamentar": "Nikolas Ferreira"})
    assert evidence["status"] == "entidade_nao_resolvida" and "proposição" in evidence["motivo"]
    t.politician_mock.assert_not_called(); t.votes_mock.assert_not_called()


def test_a_popular_name_alone_is_enough_to_try_the_proposition_resolver():
    with Tools() as t:
        execute_tool("check_member_vote", {"parlamentar": "Nikolas Ferreira", "termo_busca": "Marco Temporal"})
    assert t.proposition_mock.call_args.kwargs["termo_busca"] == "Marco Temporal"


def test_proposition_without_votes_returns_an_empty_vote_list_not_a_guess():
    with Tools(votacoes=[]) as t:
        evidence = execute_tool("check_member_vote", ARGS)
    assert evidence["votos"] == [] and evidence["total_votacoes"] == 0
    t.member_mock.assert_not_called()


def test_uf_disambiguates_a_homonym_member():
    with Tools() as t:
        execute_tool("check_member_vote", {**ARGS, "uf": "MG"})
    assert t.politician_mock.call_args.kwargs["uf"] == "MG"

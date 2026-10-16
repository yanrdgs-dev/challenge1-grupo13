"""Voto de UM parlamentar numa votação nominal (Câmara: /votacoes/{id}/votos; Senado: VotoParlamentar).

Rede sempre mockada. O parlamentar é identificado só pelo ID canônico (ideCadastro / cod_senador), nunca pelo nome
(regra 2). Quem não consta na lista não é tratado como ausente nem como contrário: a API só lista quem votou.
"""

from unittest.mock import patch

import pytest

from src.tools.http_client import HttpNetworkError
from src.tools.votacoes_api import get_member_vote

CAMARA = {"dados": [
    {"tipoVoto": "Sim", "dataRegistroVoto": "2026-05-27T23:20:51",
     "deputado_": {"id": 209787, "nome": "Nikolas Ferreira", "siglaPartido": "PL", "siglaUf": "MG"}},
    {"tipoVoto": "Não", "dataRegistroVoto": "2026-05-27T23:21:00",
     "deputado_": {"id": 111, "nome": "Fulano", "siglaPartido": "PT", "siglaUf": "SP"}},
    {"tipoVoto": "Artigo 17", "dataRegistroVoto": "2026-05-27T23:22:00",
     "deputado_": {"id": 222, "nome": "Presidente", "siglaPartido": "UNIÃO", "siglaUf": "PB"}},
]}


def _senado(*votos):
    return {"VotacaoMateria": {"Materia": {"Votacoes": {"Votacao": [
        {"CodigoSessaoVotacao": "6773", "Votos": {"VotoParlamentar": [
            {"IdentificacaoParlamentar": {"CodigoParlamentar": str(cod), "NomeParlamentar": nome,
                                          "SiglaPartidoParlamentar": partido},
             "SiglaVoto": voto} for cod, nome, partido, voto in votos]}}]}}}}


def _get(payload):
    return patch("src.tools.votacoes_api.http_client.get_json", return_value=payload)


# ------------------------------------------------------------ Câmara

@pytest.mark.parametrize("member,voto,opcao", [(209787, "Sim", "sim"), (111, "Não", "nao"), (222, "Artigo 17", "outros")])
def test_camara_returns_the_members_own_vote(member, voto, opcao):
    with _get(CAMARA) as http:
        result = get_member_vote(id_votacao="2233802-438", casa="camara", id_parlamentar=member)
    assert http.call_args.args[0].endswith("/votacoes/2233802-438/votos")
    assert result["registrado"] is True and result["voto"] == voto and result["opcao"] == opcao
    assert result["total_votos"] == 3


def test_camara_member_with_vote_carries_name_party_and_uf_from_the_record():
    with _get(CAMARA):
        result = get_member_vote(id_votacao="x", casa="camara", id_parlamentar="209787")   # ID em texto também vale
    assert (result["nome"], result["partido"], result["uf"]) == ("Nikolas Ferreira", "PL", "MG")


def test_camara_member_not_in_the_list_is_not_registered_and_not_called_absent():
    with _get(CAMARA):
        result = get_member_vote(id_votacao="x", casa="camara", id_parlamentar=999)
    assert result["registrado"] is False and result["voto"] is None and result["opcao"] is None
    assert result["total_votos"] == 3


def test_camara_symbolic_vote_has_no_nominal_list():
    with _get({"dados": []}):
        result = get_member_vote(id_votacao="x", casa="camara", id_parlamentar=209787)
    assert result["registrado"] is False and result["total_votos"] == 0 and result["votacao_nominal"] is False


def test_camara_404_is_a_vote_without_nominal_list():
    with patch("src.tools.votacoes_api.http_client.get_json", side_effect=HttpNetworkError("404 Not Found")):
        result = get_member_vote(id_votacao="x", casa="camara", id_parlamentar=209787)
    assert result["registrado"] is False and result["votacao_nominal"] is False


def test_network_error_other_than_404_is_raised():
    with patch("src.tools.votacoes_api.http_client.get_json", side_effect=HttpNetworkError("timeout")):
        with pytest.raises(HttpNetworkError):
            get_member_vote(id_votacao="x", casa="camara", id_parlamentar=209787)


# ------------------------------------------------------------ Senado

def test_senado_returns_the_senators_vote_by_cod_senador():
    payload = _senado((5672, "Alan Rick", "REPUBLICANOS", "Sim"), (6335, "Damares Alves", "REPUBLICANOS", "Não"))
    with _get(payload):
        result = get_member_vote(id_votacao="174386_6773", casa="senado", id_parlamentar=6335)
    assert result["registrado"] is True and result["voto"] == "Não" and result["opcao"] == "nao"
    assert result["nome"] == "Damares Alves" and result["partido"] == "REPUBLICANOS" and result["total_votos"] == 2


def test_senado_senator_not_in_the_list_is_not_registered():
    with _get(_senado((5672, "Alan Rick", "REPUBLICANOS", "Sim"))):
        result = get_member_vote(id_votacao="174386_6773", casa="senado", id_parlamentar=1)
    assert result["registrado"] is False and result["voto"] is None


def test_senado_not_voted_label_is_kept_as_the_api_says():
    with _get(_senado((6335, "Damares Alves", "REPUBLICANOS", "Não Votou"))):
        result = get_member_vote(id_votacao="174386_6773", casa="senado", id_parlamentar=6335)
    assert result["registrado"] is True and result["voto"] == "Não Votou" and result["opcao"] == "ausente"


def test_invalid_casa_and_empty_member_id_are_rejected():
    with pytest.raises(ValueError):
        get_member_vote(id_votacao="x", casa="congresso", id_parlamentar=1)
    with pytest.raises(ValueError):
        get_member_vote(id_votacao="x", casa="camara", id_parlamentar="")

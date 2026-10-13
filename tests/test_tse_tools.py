"""Testes unitários das tools de resultado eleitoral do TSE (Fase 1, passo 2).

Cobrem `resolve_candidate`, `get_election_result` e `get_candidate_votes` sobre parquets sintéticos com o
esquema real medido em docs/data_schemas.md (seção 8). Regras da AGENTS.md exercitadas:
- regra 1: o resultado vem de `QT_VOTOS_NOMINAIS_VALIDOS` (os votos anulados não contam);
- regra 2: nada de dado sem `SQ_CANDIDATO` canônico; homônimo vira ambíguo, nunca palpite;
- regra 3: ano ou turno ausente, e resultado de 2026 (inexistente), devolvem evidência vazia explicada.
"""

from pathlib import Path
from typing import Any, Dict, List

import polars as pl
import pytest

from src.tools.tse_tools import election_results_available, get_candidate_votes, get_election_result, resolve_candidate


def _cand(sq, civil, urna, partido, cargo, uf, numero, turno=1, situacao="NÃO ELEITO", ano=2022):
    return {
        "ANO_ELEICAO": ano, "SG_UF": uf, "SQ_CANDIDATO": sq, "NM_CANDIDATO": civil, "NM_URNA_CANDIDATO": urna,
        "SG_PARTIDO": partido, "DS_CARGO": cargo, "NR_CANDIDATO": numero, "NM_SOCIAL_CANDIDATO": "#NULO",
        "DS_SITUACAO_CANDIDATURA": "APTO", "NR_TURNO": turno, "DS_SIT_TOT_TURNO": situacao,
    }


def _vot(sq, urna, partido, cargo, uf, turno, nominais, validos, situacao, numero=0):
    return {
        "ANO_ELEICAO": 2022, "NR_TURNO": turno, "SG_UF": uf, "NM_MUNICIPIO": "X", "NR_ZONA": 1,
        "DS_CARGO": cargo, "SQ_CANDIDATO": sq, "NR_CANDIDATO": numero, "NM_URNA_CANDIDATO": urna,
        "SG_PARTIDO": partido, "QT_VOTOS_NOMINAIS": nominais, "QT_VOTOS_NOMINAIS_VALIDOS": validos,
        "DS_SIT_TOT_TURNO": situacao,
    }


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "part-000.parquet")


@pytest.fixture
def tse_dir(tmp_path: Path) -> Path:
    base = tmp_path / "processed"
    candidatos_2022 = [
        _cand(1, "LUIZ INÁCIO LULA DA SILVA", "LULA", "PT", "PRESIDENTE", "BR", 13, 1, "2º TURNO"),
        _cand(1, "LUIZ INÁCIO LULA DA SILVA", "LULA", "PT", "PRESIDENTE", "BR", 13, 2, "ELEITO"),
        _cand(2, "JAIR MESSIAS BOLSONARO", "JAIR BOLSONARO", "PL", "PRESIDENTE", "BR", 22, 1, "2º TURNO"),
        _cand(2, "JAIR MESSIAS BOLSONARO", "JAIR BOLSONARO", "PL", "PRESIDENTE", "BR", 22, 2, "NÃO ELEITO"),
        _cand(3, "SIMONE NASSAR TEBET", "SIMONE TEBET", "MDB", "PRESIDENTE", "BR", 15, 1, "NÃO ELEITO"),
        _cand(4, "PABLO MARÇAL", "PABLO MARÇAL", "PROS", "PRESIDENTE", "BR", 90, 1, "NÃO ELEITO"),
        _cand(10, "JOÃO DA SILVA", "JOÃO SILVA", "PT", "DEPUTADO FEDERAL", "SP", 1301, 1, "ELEITO POR QP"),
        _cand(11, "JOÃO SILVA SANTOS", "JOÃO SILVA", "PL", "DEPUTADO FEDERAL", "SP", 2211, 1, "NÃO ELEITO"),
        _cand(12, "JOÃO SILVA JÚNIOR", "JOÃO SILVA", "PSD", "DEPUTADO FEDERAL", "RJ", 5500, 1, "NÃO ELEITO"),
        _cand(20, "ANA MARIA SOUZA", "ANA SOUZA", "PSB", "GOVERNADOR", "MG", 40, 1, "ELEITO"),
    ]
    candidatos_2026 = [
        _cand(900, "LUIZ INÁCIO LULA DA SILVA", "LULA", "PT", "PRESIDENTE", "BR", 13, 1, "#NE", 2026),
    ]
    _write(base / "tse" / "candidatos" / "ano=2022", candidatos_2022)
    _write(base / "tse" / "candidatos" / "ano=2026", candidatos_2026)

    votacao = [
        # Presidente, 1º turno: duas zonas (uma delas com o voto no exterior, UF ZZ)
        _vot(1, "LULA", "PT", "Presidente", "SP", 1, 600, 600, "2º TURNO"),
        _vot(1, "LULA", "PT", "Presidente", "ZZ", 1, 100, 100, "2º TURNO"),
        _vot(2, "JAIR BOLSONARO", "PL", "Presidente", "SP", 1, 500, 500, "2º TURNO"),
        _vot(2, "JAIR BOLSONARO", "PL", "Presidente", "ZZ", 1, 200, 200, "2º TURNO"),
        _vot(3, "SIMONE TEBET", "MDB", "Presidente", "SP", 1, 100, 100, "NÃO ELEITO"),
        # Indeferido: 300 votos nominais, todos anulados
        _vot(4, "PABLO MARÇAL", "PROS", "Presidente", "SP", 1, 300, 0, "NÃO ELEITO"),
        # Presidente, 2º turno
        _vot(1, "LULA", "PT", "Presidente", "SP", 2, 700, 700, "ELEITO"),
        _vot(2, "JAIR BOLSONARO", "PL", "Presidente", "SP", 2, 650, 650, "NÃO ELEITO"),
        # Deputado Federal SP
        _vot(10, "JOÃO SILVA", "PT", "Deputado Federal", "SP", 1, 80, 80, "ELEITO POR QP"),
        _vot(11, "JOÃO SILVA", "PL", "Deputado Federal", "SP", 1, 20, 20, "NÃO ELEITO"),
        _vot(12, "JOÃO SILVA", "PSD", "Deputado Federal", "RJ", 1, 5, 5, "NÃO ELEITO"),
        # Governador MG
        _vot(20, "ANA SOUZA", "PSB", "Governador", "MG", 1, 900, 900, "ELEITO"),
    ]
    _write(base / "tse" / "votacao_munzona" / "ano=2022", votacao)
    return base


# --------------------------------------------------------------------------- resolve_candidate

class TestResolveCandidate:
    def test_caminho_feliz_por_nome_de_urna(self, tse_dir):
        res = resolve_candidate("Lula", ano=2022, cargo="Presidente", base_dir=tse_dir)
        assert res["encontrado"] is True
        assert res["ambiguous"] is False
        assert res["sq_candidato"] == 1
        assert res["nome_urna"] == "LULA"
        assert res["nome_civil"] == "LUIZ INÁCIO LULA DA SILVA"
        assert res["partido"] == "PT"
        assert res["cargo"] == "PRESIDENTE"
        assert res["ano"] == 2022

    def test_candidato_de_dois_turnos_nao_vira_ambiguo(self, tse_dir):
        res = resolve_candidate("Lula", ano=2022, base_dir=tse_dir)
        assert res["ambiguous"] is False
        assert res["sq_candidato"] == 1
        assert res["turnos"] == [1, 2]

    def test_nome_civil_com_acento_e_caixa(self, tse_dir):
        res = resolve_candidate("luiz inacio LULA da silva", ano=2022, base_dir=tse_dir)
        assert res["sq_candidato"] == 1

    def test_nome_parcial_de_um_unico_candidato(self, tse_dir):
        res = resolve_candidate("Bolsonaro", ano=2022, base_dir=tse_dir)
        assert res["sq_candidato"] == 2

    def test_cargo_ignora_caixa(self, tse_dir):
        res = resolve_candidate("Lula", ano=2022, cargo="presidente", base_dir=tse_dir)
        assert res["sq_candidato"] == 1

    def test_ano_isola_a_candidatura(self, tse_dir):
        assert resolve_candidate("Lula", ano=2022, base_dir=tse_dir)["sq_candidato"] == 1
        assert resolve_candidate("Lula", ano=2026, base_dir=tse_dir)["sq_candidato"] == 900

    def test_entidade_nao_encontrada(self, tse_dir):
        res = resolve_candidate("Fulano Inexistente da Silva", ano=2022, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["sq_candidato"] is None
        assert res["status"] == "nao_encontrado"

    def test_filtro_de_uf_que_elimina_o_candidato(self, tse_dir):
        res = resolve_candidate("Ana Souza", ano=2022, uf="SP", base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["sq_candidato"] is None

    def test_homonimo_e_ambiguo_e_nao_escolhe(self, tse_dir):
        res = resolve_candidate("João Silva", ano=2022, cargo="Deputado Federal", uf="SP", base_dir=tse_dir)
        assert res["ambiguous"] is True
        assert res["sq_candidato"] is None
        assert {c["sq_candidato"] for c in res["candidatos_alternativos"]} == {10, 11}
        assert {c["numero"] for c in res["candidatos_alternativos"]} == {1301, 2211}

    def test_numero_desempata_homonimos(self, tse_dir):
        res = resolve_candidate(
            "João Silva", ano=2022, cargo="Deputado Federal", uf="SP", numero=2211, base_dir=tse_dir
        )
        assert res["ambiguous"] is False
        assert res["sq_candidato"] == 11
        assert res["partido"] == "PL"

    def test_uf_desempata_homonimos(self, tse_dir):
        res = resolve_candidate("João Silva", ano=2022, cargo="Deputado Federal", uf="RJ", base_dir=tse_dir)
        assert res["sq_candidato"] == 12

    def test_sem_ano_nao_consulta(self, tse_dir):
        res = resolve_candidate("Lula", ano=None, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "especificacao_insuficiente"
        assert res["sq_candidato"] is None

    def test_nome_vazio(self, tse_dir):
        res = resolve_candidate("  ", ano=2022, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["sq_candidato"] is None

    def test_ano_sem_base(self, tse_dir):
        res = resolve_candidate("Lula", ano=2018, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "nao_encontrado"

    def test_base_ausente(self, tmp_path):
        res = resolve_candidate("Lula", ano=2022, base_dir=tmp_path / "vazio")
        assert res["encontrado"] is False


# --------------------------------------------------------------------------- get_election_result

class TestGetElectionResult:
    def test_presidente_primeiro_turno_soma_validos_e_o_exterior(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is True
        assert res["ano"] == 2022 and res["turno"] == 1 and res["cargo"] == "Presidente"
        ranking = res["candidatos"]
        assert [c["sq_candidato"] for c in ranking] == [1, 2, 3, 4]
        assert ranking[0]["votos_validos"] == 700  # 600 em SP + 100 no exterior (ZZ)
        assert ranking[1]["votos_validos"] == 700
        assert ranking[0]["posicao"] == 1

    def test_votos_anulados_nao_entram_no_resultado(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=1, base_dir=tse_dir)
        marcal = next(c for c in res["candidatos"] if c["sq_candidato"] == 4)
        assert marcal["votos_validos"] == 0
        assert marcal["votos_anulados"] == 300
        assert res["total_votos_validos"] == 700 + 700 + 100

    def test_percentual_sobre_os_votos_validos(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=1, base_dir=tse_dir)
        assert res["candidatos"][2]["percentual_votos_validos"] == pytest.approx(100 / 1500 * 100, abs=0.01)

    def test_segundo_turno_e_eleito(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=2, base_dir=tse_dir)
        assert [c["sq_candidato"] for c in res["candidatos"]] == [1, 2]
        assert res["candidatos"][0]["situacao"] == "ELEITO"
        assert res["candidatos"][0]["votos_validos"] == 700
        assert res["candidatos"][1]["votos_validos"] == 650
        assert [c["sq_candidato"] for c in res["eleitos"]] == [1]

    def test_cargo_estadual_filtra_pela_uf(self, tse_dir):
        res = get_election_result("Governador", ano=2022, turno=1, uf="mg", base_dir=tse_dir)
        assert res["uf"] == "MG"
        assert [c["sq_candidato"] for c in res["candidatos"]] == [20]

    def test_cargo_estadual_exige_uf(self, tse_dir):
        res = get_election_result("Deputado Federal", ano=2022, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "especificacao_insuficiente"

    def test_top_n_limita_a_lista_sem_mudar_o_total(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=1, top_n=2, base_dir=tse_dir)
        assert len(res["candidatos"]) == 2
        assert res["total_candidatos"] == 4
        assert res["total_votos_validos"] == 1500

    def test_sem_turno_nao_consulta(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=None, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "especificacao_insuficiente"

    def test_sem_ano_nao_consulta(self, tse_dir):
        res = get_election_result("Presidente", ano=None, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "especificacao_insuficiente"

    def test_turno_invalido(self, tse_dir):
        res = get_election_result("Presidente", ano=2022, turno=3, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "especificacao_insuficiente"

    def test_resultado_de_2026_nao_existe(self, tse_dir):
        res = get_election_result("Presidente", ano=2026, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "resultado_indisponivel"
        assert res["candidatos"] == []

    def test_cargo_invalido(self, tse_dir):
        res = get_election_result("Prefeito de Marte", ano=2022, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "cargo_invalido"

    def test_turno_que_nao_aconteceu_para_o_cargo(self, tse_dir):
        res = get_election_result("Governador", ano=2022, turno=2, uf="MG", base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "sem_resultado"

    def test_base_ausente(self, tmp_path):
        res = get_election_result("Presidente", ano=2022, turno=1, base_dir=tmp_path / "vazio")
        assert res["encontrado"] is False
        assert res["status"] == "resultado_indisponivel"


# --------------------------------------------------------------------------- get_candidate_votes

class TestGetCandidateVotes:
    def test_caminho_feliz(self, tse_dir):
        res = get_candidate_votes(1, ano=2022, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is True
        assert res["sq_candidato"] == 1
        assert res["nome_urna"] == "LULA"
        assert res["partido"] == "PT"
        assert res["cargo"] == "Presidente"
        assert res["votos_validos"] == 700
        assert res["votos_anulados"] == 0
        assert res["situacao"] == "2º TURNO"
        assert res["posicao"] == 1  # empatado em votos com Bolsonaro; desempate estável por SQ_CANDIDATO
        assert res["total_votos_validos_cargo"] == 1500
        assert res["percentual_votos_validos"] == pytest.approx(700 / 1500 * 100, abs=0.01)

    def test_segundo_turno(self, tse_dir):
        res = get_candidate_votes(1, ano=2022, turno=2, base_dir=tse_dir)
        assert res["votos_validos"] == 700
        assert res["situacao"] == "ELEITO"
        assert res["posicao"] == 1

    def test_candidato_indeferido_tem_zero_validos_e_anulados(self, tse_dir):
        res = get_candidate_votes(4, ano=2022, turno=1, base_dir=tse_dir)
        assert res["votos_validos"] == 0
        assert res["votos_nominais"] == 300
        assert res["votos_anulados"] == 300

    def test_cargo_estadual_compara_so_dentro_da_uf(self, tse_dir):
        res = get_candidate_votes(10, ano=2022, turno=1, base_dir=tse_dir)
        assert res["uf"] == "SP"
        assert res["total_votos_validos_cargo"] == 100  # 80 + 20 de SP; o RJ fica de fora
        assert res["posicao"] == 1

    def test_candidato_inexistente(self, tse_dir):
        res = get_candidate_votes(999999, ano=2022, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "nao_encontrado"

    def test_candidato_que_nao_disputou_o_turno(self, tse_dir):
        res = get_candidate_votes(3, ano=2022, turno=2, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "sem_resultado"

    def test_id_em_texto_livre_e_recusado(self, tse_dir):
        res = get_candidate_votes("Lula", ano=2022, turno=1, base_dir=tse_dir)  # type: ignore[arg-type]
        assert res["encontrado"] is False
        assert res["status"] == "entidade_nao_resolvida"

    def test_id_numerico_em_texto_e_aceito(self, tse_dir):
        assert get_candidate_votes("1", ano=2022, turno=1, base_dir=tse_dir)["sq_candidato"] == 1

    def test_sem_turno_ou_ano(self, tse_dir):
        assert get_candidate_votes(1, ano=2022, turno=None, base_dir=tse_dir)["status"] == "especificacao_insuficiente"
        assert get_candidate_votes(1, ano=None, turno=1, base_dir=tse_dir)["status"] == "especificacao_insuficiente"

    def test_resultado_de_2026_nao_existe(self, tse_dir):
        res = get_candidate_votes(900, ano=2026, turno=1, base_dir=tse_dir)
        assert res["encontrado"] is False
        assert res["status"] == "resultado_indisponivel"


# --------------------------------------------------------------------------- dados de 2026 ainda não publicados

class TestResultado2026NaoPublicado:
    FRASE = "ainda não foram atualizados"

    def test_resultado_de_2026_explica_que_os_dados_abertos_nao_foram_atualizados(self, tse_dir):
        res = get_election_result("Presidente", ano=2026, turno=1, base_dir=tse_dir)
        assert self.FRASE in res["motivo"] and "2026" in res["motivo"]
        assert res["ano"] == 2026

    def test_votos_de_candidato_em_2026_explicam_o_mesmo(self, tse_dir):
        res = get_candidate_votes(900, ano=2026, turno=1, base_dir=tse_dir)
        assert self.FRASE in res["motivo"]

    def test_disponibilidade_do_resultado(self, tse_dir):
        assert election_results_available(2022, base_dir=tse_dir) is True
        assert election_results_available(2026, base_dir=tse_dir) is False
        assert election_results_available(2018, base_dir=tse_dir) is False

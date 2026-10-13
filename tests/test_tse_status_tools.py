"""Testes de `check_candidate_status` e `check_disqualification_motive` (Fase 1, passo 2).

Esquema: docs/data_schemas.md seção 8. Em 2022 a situação vem em `DS_DETALHE_SITUACAO_CAND`; em 2026 o TSE
preenche `DS_SITUACAO_JULGAMENTO` e `DS_SITUACAO_CANDIDATO_TOT` e deixa o detalhe como `#NE`. Os marcadores
(`#NE`, `#NULO`) são ausência de valor e nunca saem como valor (regra 1).
"""

from pathlib import Path

import polars as pl
import pytest

from src.tools.tse_tools import check_candidate_status, check_disqualification_motive


def _write(path: Path, rows):
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "part-000.parquet")


def _cand(sq, urna, partido, cargo, uf, turno=1, situacao="APTO", sit_tot="NÃO ELEITO", ano=2022):
    return {"ANO_ELEICAO": ano, "SG_UF": uf, "SQ_CANDIDATO": sq, "NM_CANDIDATO": urna, "NM_URNA_CANDIDATO": urna,
            "SG_PARTIDO": partido, "DS_CARGO": cargo, "NR_CANDIDATO": 10, "NM_SOCIAL_CANDIDATO": "#NULO",
            "DS_SITUACAO_CANDIDATURA": situacao, "NR_TURNO": turno, "DS_SIT_TOT_TURNO": sit_tot}


def _compl(sq, detalhe="DEFERIDO", tot="DEFERIDO", julg="#NE", cass="#NE", diploma="#NE"):
    return {"SQ_CANDIDATO": sq, "DS_DETALHE_SITUACAO_CAND": detalhe, "DS_SITUACAO_CANDIDATO_TOT": tot,
            "DS_SITUACAO_JULGAMENTO": julg, "DS_SITUACAO_CASSACAO": cass, "DS_SITUACAO_DIPLOMA": diploma}


def _cass(sq, motivo, tipo="Fundamentos legais de julgamento", processo=111):
    return {"SQ_CANDIDATO": sq, "SG_UF": "SP", "NR_PROCESSO": processo, "DS_TP_MOTIVO": tipo, "DS_MOTIVO": motivo}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    b = tmp_path / "processed" / "tse"
    _write(b / "candidatos" / "ano=2022", [
        _cand(1, "LULA", "PT", "PRESIDENTE", "BR", 1, sit_tot="2º TURNO"),
        _cand(1, "LULA", "PT", "PRESIDENTE", "BR", 2, sit_tot="ELEITO"),
        _cand(4, "PABLO MARÇAL", "PROS", "PRESIDENTE", "BR", 1, "INAPTO", "NÃO ELEITO"),
        _cand(5, "CANDIDATO LIMPO", "PSD", "DEPUTADO ESTADUAL", "SP"),
        _cand(6, "DUPLICADO", "PL", "DEPUTADO ESTADUAL", "SP"),
    ])
    _write(b / "candidatos" / "ano=2026", [_cand(900, "NOVO", "PT", "GOVERNADOR", "SP", ano=2026, situacao="#NE", sit_tot="#NE")])
    _write(b / "candidatos_complementar" / "ano=2022", [
        _compl(1), _compl(1),  # linha repetida idêntica: não é divergência
        _compl(4, "INDEFERIDO", "INDEFERIDO"),
        _compl(5),
        _compl(6, "DEFERIDO", "DEFERIDO"), _compl(6, "INDEFERIDO", "INDEFERIDO"),  # duas linhas que divergem
    ])
    _write(b / "candidatos_complementar" / "ano=2026", [
        _compl(900, "#NE", "INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO", "INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO", "#NULO"),
    ])
    _write(b / "cassacao" / "ano=2022", [
        _cass(4, "Ficha limpa (LC 64/90)", processo=1),
        _cass(4, "Ausência de requisito de registro ", processo=2),
        _cass(6, "Abuso de poder político"),
    ])
    _write(b / "cassacao" / "ano=2026", [_cass(900, "Ausência de quitação eleitoral (Lei 9.504/97)")])
    return b.parent


# ------------------------------------------------------------------ check_candidate_status

class TestCheckCandidateStatus:
    def test_caminho_feliz_com_resultado_por_turno(self, base):
        res = check_candidate_status(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["status"] == "ok"
        assert res["nome_urna"] == "LULA" and res["cargo"] == "PRESIDENTE" and res["partido"] == "PT"
        assert res["situacao_candidatura"] == "APTO"
        assert res["detalhe_situacao"] == "DEFERIDO"
        assert res["situacao_total"] == "DEFERIDO"
        assert res["resultado_por_turno"] == {1: "2º TURNO", 2: "ELEITO"}
        assert res["registros_divergentes"] == 0

    def test_marcadores_do_tse_nao_saem_como_valor(self, base):
        res = check_candidate_status(1, ano=2022, base_dir=base)
        assert res["situacao_julgamento"] is None
        assert res["situacao_cassacao"] is None
        assert "#NE" not in str(res.values()) and "#NULO" not in str(res.values())

    def test_candidatura_indeferida(self, base):
        res = check_candidate_status(4, ano=2022, base_dir=base)
        assert res["situacao_candidatura"] == "INAPTO"
        assert res["detalhe_situacao"] == "INDEFERIDO"

    def test_2026_usa_a_situacao_do_julgamento(self, base):
        res = check_candidate_status(900, ano=2026, base_dir=base)
        assert res["detalhe_situacao"] is None
        assert res["situacao_candidatura"] is None
        assert res["situacao_julgamento"] == "INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO"
        assert res["situacao_total"] == "INDEFERIDO EM PRAZO RECURSAL OU COM RECURSO"
        assert res["resultado_por_turno"] == {}  # eleição ainda não aconteceu: #NE não é resultado

    def test_linhas_que_divergem_sao_declaradas_e_nao_escondidas(self, base):
        res = check_candidate_status(6, ano=2022, base_dir=base)
        assert res["registros_divergentes"] == 1
        assert {r["detalhe_situacao"] for r in [res, *res["outros_registros"]]} == {"DEFERIDO", "INDEFERIDO"}

    def test_candidato_inexistente(self, base):
        res = check_candidate_status(999999, ano=2022, base_dir=base)
        assert res["encontrado"] is False and res["status"] == "nao_encontrado"

    def test_id_em_texto_livre_e_recusado(self, base):
        res = check_candidate_status("Lula", ano=2022, base_dir=base)
        assert res["status"] == "entidade_nao_resolvida"

    def test_sem_ano(self, base):
        assert check_candidate_status(1, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"

    def test_ano_sem_base(self, base):
        assert check_candidate_status(1, ano=2018, base_dir=base)["status"] == "nao_encontrado"

    def test_sem_complementar_ainda_devolve_o_cadastro(self, tmp_path):
        _write(tmp_path / "tse" / "candidatos" / "ano=2022", [_cand(1, "LULA", "PT", "PRESIDENTE", "BR")])
        res = check_candidate_status(1, ano=2022, base_dir=tmp_path)
        assert res["encontrado"] is True and res["detalhe_situacao"] is None
        assert res["situacao_candidatura"] == "APTO"


# ------------------------------------------------------------------ check_disqualification_motive

class TestCheckDisqualificationMotive:
    def test_lista_os_motivos_registrados(self, base):
        res = check_disqualification_motive(4, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["status"] == "ok"
        assert res["total_motivos"] == 2
        assert {m["motivo"] for m in res["motivos"]} == {"Ficha limpa (LC 64/90)", "Ausência de requisito de registro"}
        assert res["motivos"][0]["tipo"] == "Fundamentos legais de julgamento"
        assert res["detalhe_situacao"] == "INDEFERIDO"

    def test_candidato_sem_motivo_registrado(self, base):
        res = check_disqualification_motive(5, ano=2022, base_dir=base)
        assert res["encontrado"] is True
        assert res["total_motivos"] == 0 and res["motivos"] == []
        assert res["detalhe_situacao"] == "DEFERIDO"

    def test_2026(self, base):
        res = check_disqualification_motive(900, ano=2026, base_dir=base)
        assert res["motivos"][0]["motivo"].startswith("Ausência de quitação eleitoral")

    def test_candidato_inexistente(self, base):
        res = check_disqualification_motive(999999, ano=2022, base_dir=base)
        assert res["encontrado"] is False and res["status"] == "nao_encontrado"

    def test_id_em_texto_livre_e_recusado(self, base):
        assert check_disqualification_motive("Pablo", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"

    def test_sem_ano(self, base):
        assert check_disqualification_motive(4, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"

    def test_sem_tabela_de_cassacao_nao_afirma_ausencia_de_motivo(self, tmp_path):
        _write(tmp_path / "tse" / "candidatos" / "ano=2022", [_cand(4, "X", "PT", "PRESIDENTE", "BR")])
        res = check_disqualification_motive(4, ano=2022, base_dir=tmp_path)
        assert res["encontrado"] is False and res["status"] == "resultado_indisponivel"

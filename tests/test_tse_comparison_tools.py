"""Testes de `compare_candidates` (comparação de dois a quatro candidatos numa métrica).

A tool recebe só `SQ_CANDIDATO` (regra 2: o roteador resolve cada nome antes). Falta de dado de qualquer candidato
impede a comparação, nunca vira zero (regra 1). Empate é declarado, sem líder. Votos de disputas diferentes
são comparáveis em número, mas o resultado avisa que a disputa não é a mesma.
"""

from pathlib import Path

import polars as pl
import pytest

from src.tools.tse_comparison_tools import compare_candidates


def _write(path: Path, rows):
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "part-000.parquet")


def _cand(sq, urna, cargo="PRESIDENTE", uf="BR", turno=1):
    return {"ANO_ELEICAO": 2022, "SG_UF": uf, "SQ_CANDIDATO": sq, "NM_CANDIDATO": urna, "NM_URNA_CANDIDATO": urna,
            "SG_PARTIDO": "PT", "DS_CARGO": cargo, "NR_CANDIDATO": sq, "NM_SOCIAL_CANDIDATO": "#NULO",
            "DS_SITUACAO_CANDIDATURA": "APTO", "NR_TURNO": turno, "DS_SIT_TOT_TURNO": "#NE"}


def _vot(sq, urna, uf, turno, validos, cargo="Presidente"):
    return {"ANO_ELEICAO": 2022, "NR_TURNO": turno, "SG_UF": uf, "NM_MUNICIPIO": "X", "NR_ZONA": 1, "DS_CARGO": cargo,
            "SQ_CANDIDATO": sq, "NR_CANDIDATO": sq, "NM_URNA_CANDIDATO": urna, "SG_PARTIDO": "PT",
            "QT_VOTOS_NOMINAIS": validos, "QT_VOTOS_NOMINAIS_VALIDOS": validos, "DS_SIT_TOT_TURNO": "#NE"}


def _bem(sq, valor):
    return {"ANO_ELEICAO": 2022, "SG_UF": "BR", "SQ_CANDIDATO": sq, "DS_TIPO_BEM_CANDIDATO": "Casa",
            "DS_BEM_CANDIDATO": "x", "VR_BEM_CANDIDATO": valor}


def _rec(sq, prest, valor, cargo="Presidente", tipo="FINAL"):
    return {"SQ_CANDIDATO": sq, "SQ_PRESTADOR_CONTAS": prest, "NM_CANDIDATO": f"C{sq}", "SG_PARTIDO": "PT", "SG_UF": "BR",
            "DS_CARGO": cargo, "TP_PRESTACAO_CONTAS": tipo, "DS_ORIGEM_RECEITA": "Recursos próprios",
            "DS_FONTE_RECEITA": "OUTROS RECURSOS", "VR_RECEITA": valor}


def _desp(sq, prest, valor, cargo="Presidente", tipo="FINAL"):
    return {"SQ_CANDIDATO": sq, "SQ_PRESTADOR_CONTAS": prest, "NM_CANDIDATO": f"C{sq}", "SG_PARTIDO": "PT", "SG_UF": "BR",
            "DS_CARGO": cargo, "TP_PRESTACAO_CONTAS": tipo, "DS_ORIGEM_DESPESA": "Despesas com pessoal",
            "VR_DESPESA_CONTRATADA": valor}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    t = tmp_path / "tse"
    _write(t / "candidatos" / "ano=2022", [
        _cand(1, "LULA"), _cand(1, "LULA", turno=2), _cand(2, "JAIR"), _cand(2, "JAIR", turno=2), _cand(3, "TEBET"),
        _cand(4, "DEP SP", "DEPUTADO FEDERAL", "SP"), _cand(6, "SEM BENS"), _cand(7, "SEM CONTAS"),
    ])
    _write(t / "votacao_munzona" / "ano=2022", [
        _vot(1, "LULA", "SP", 1, 600), _vot(1, "LULA", "ZZ", 1, 100), _vot(1, "LULA", "SP", 2, 700),
        _vot(2, "JAIR", "SP", 1, 650), _vot(2, "JAIR", "SP", 2, 650),
        _vot(3, "TEBET", "SP", 1, 100),
        _vot(4, "DEP SP", "SP", 1, 80, "Deputado Federal"),
    ])
    _write(t / "bens" / "ano=2022", [_bem(1, 900_000.0), _bem(1, 100_000.0), _bem(2, 300_000.0), _bem(3, 300_000.0)])
    pc = t / "prestacao_contas"
    _write(pc / "receitas" / "ano=2022", [_rec(1, 11, 500.0), _rec(2, 22, 800.0), _rec(3, 33, 800.0)])
    _write(pc / "despesas_contratadas" / "ano=2022", [_desp(1, 11, 400.0), _desp(2, 22, 900.0), _desp(3, 33, 100.0)])
    _write(pc / "despesas_pagas" / "ano=2022", [{"SQ_PRESTADOR_CONTAS": 11, "VR_PAGTO_DESPESA": 1.0}])
    return t.parent


class TestComparison:
    def test_votos_do_primeiro_turno(self, base):
        res = compare_candidates([1, 2], 2022, "votos_validos", turno=1, base_dir=base)
        assert res["encontrado"] is True and res["status"] == "ok"
        assert res["metrica"] == "votos_validos" and res["turno"] == 1 and res["ano"] == 2022
        assert [c["sq_candidato"] for c in res["candidatos"]] == [1, 2]
        assert [c["valor"] for c in res["candidatos"]] == [700, 650]
        assert [c["posicao"] for c in res["candidatos"]] == [1, 2]
        assert res["lider"]["sq_candidato"] == 1 and res["lider"]["nome_urna"] == "LULA"
        assert res["empate"] is False and res["diferenca_absoluta"] == 50
        assert res["mesma_disputa"] is True

    def test_segundo_turno(self, base):
        res = compare_candidates([2, 1], 2022, "votos_validos", turno=2, base_dir=base)
        assert [c["sq_candidato"] for c in res["candidatos"]] == [1, 2]  # ordena por valor, não pela ordem pedida
        assert res["candidatos"][0]["valor"] == 700

    def test_patrimonio(self, base):
        res = compare_candidates([1, 2], 2022, "patrimonio", base_dir=base)
        assert [c["valor"] for c in res["candidatos"]] == [1_000_000.0, 300_000.0]
        assert res["lider"]["sq_candidato"] == 1 and res["diferenca_absoluta"] == 700_000.0

    def test_receitas_e_despesas_contratadas(self, base):
        rec = compare_candidates([1, 2], 2022, "receitas", base_dir=base)
        assert rec["lider"]["sq_candidato"] == 2 and rec["candidatos"][1]["valor"] == 500.0
        desp = compare_candidates([1, 2], 2022, "despesas_contratadas", base_dir=base)
        assert desp["lider"]["sq_candidato"] == 2 and desp["diferenca_absoluta"] == 500.0

    def test_empate_nao_tem_lider(self, base):
        res = compare_candidates([2, 3], 2022, "receitas", base_dir=base)  # 800 e 800
        assert res["empate"] is True and res["lider"] is None and res["diferenca_absoluta"] == 0.0

    def test_tres_candidatos_em_ordem(self, base):
        res = compare_candidates([3, 1, 2], 2022, "votos_validos", turno=1, base_dir=base)
        assert [c["sq_candidato"] for c in res["candidatos"]] == [1, 2, 3]
        assert res["diferenca_absoluta"] == 50  # entre o primeiro e o segundo

    def test_disputas_diferentes_sao_declaradas(self, base):
        res = compare_candidates([1, 4], 2022, "votos_validos", turno=1, base_dir=base)
        assert res["encontrado"] is True and res["mesma_disputa"] is False
        assert "disputas diferentes" in res["aviso"]

    def test_falta_de_dado_de_um_candidato_impede_a_comparacao(self, base):
        res = compare_candidates([1, 6], 2022, "patrimonio", base_dir=base)  # 6 não declarou bem
        assert res["encontrado"] is False and res["status"] == "dado_incompleto"
        assert [c["sq_candidato"] for c in res["candidatos_sem_dado"]] == [6]
        assert "lider" not in res

    def test_candidato_sem_prestacao(self, base):
        res = compare_candidates([1, 7], 2022, "despesas_contratadas", base_dir=base)
        assert res["status"] == "dado_incompleto" and res["candidatos_sem_dado"][0]["sq_candidato"] == 7

    def test_candidato_que_nao_disputou_o_turno(self, base):
        res = compare_candidates([1, 3], 2022, "votos_validos", turno=2, base_dir=base)
        assert res["status"] == "dado_incompleto" and res["candidatos_sem_dado"][0]["sq_candidato"] == 3

    def test_prestacao_parcial_vai_para_os_avisos(self, base, tmp_path):
        _write(base / "tse" / "prestacao_contas" / "receitas" / "ano=2022", [_rec(1, 11, 5.0, tipo="PARCIAL"), _rec(2, 22, 9.0)])
        res = compare_candidates([1, 2], 2022, "receitas", base_dir=base)
        assert res["encontrado"] is True and "parcia" in res["aviso"]

    def test_candidato_inexistente(self, base):
        res = compare_candidates([1, 999], 2022, "patrimonio", base_dir=base)
        assert res["status"] == "nao_encontrado"

    def test_2026_nao_tem_votos(self, base):
        res = compare_candidates([1, 2], 2026, "votos_validos", turno=1, base_dir=base)
        assert res["status"] == "resultado_indisponivel"


class TestRequest:
    @pytest.mark.parametrize("sqs", [[1], [], [1, 2, 3, 4, 5], [1, 1]])
    def test_quantidade_e_duplicidade(self, base, sqs):
        res = compare_candidates(sqs, 2022, "patrimonio", base_dir=base)
        assert res["encontrado"] is False and res["status"] == "especificacao_insuficiente"

    def test_texto_livre_e_recusado(self, base):
        res = compare_candidates(["Lula", "Jair"], 2022, "patrimonio", base_dir=base)
        assert res["status"] == "entidade_nao_resolvida"

    def test_ids_numericos_em_texto_sao_aceitos(self, base):
        assert compare_candidates(["1", "2"], 2022, "patrimonio", base_dir=base)["encontrado"] is True

    def test_lista_invalida(self, base):
        assert compare_candidates(None, 2022, "patrimonio", base_dir=base)["status"] == "especificacao_insuficiente"  # type: ignore[arg-type]

    @pytest.mark.parametrize("metrica,turno,ano", [
        ("lucro", None, 2022), (None, None, 2022), ("votos_validos", None, 2022), ("votos_validos", 3, 2022),
        ("patrimonio", None, None),
    ])
    def test_especificacao_insuficiente(self, base, metrica, turno, ano):
        res = compare_candidates([1, 2], ano, metrica, turno=turno, base_dir=base)  # type: ignore[arg-type]
        assert res["encontrado"] is False and res["status"] == "especificacao_insuficiente"

    def test_base_ausente(self, tmp_path):
        res = compare_candidates([1, 2], 2022, "patrimonio", base_dir=tmp_path / "vazio")
        assert res["encontrado"] is False

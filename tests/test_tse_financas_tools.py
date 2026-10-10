"""Testes das tools de finanças de campanha do TSE (Fase 1, passo 4).

`get_campaign_finances` (receitas, despesas contratadas e pagas de um candidato) e
`get_top_campaign_finances` (ranking por cargo). Regras: ID canônico (regra 2); `despesas_pagas` só liga ao
candidato por `SQ_PRESTADOR_CONTAS` (docs/data_schemas.md 8.3); prestação não final (como a de 2026) é
declarada como parcial; sem prestação publicada não é gasto zero; nenhum doador ou fornecedor sai.
"""

from pathlib import Path

import polars as pl
import pytest

from src.tools.tse_financas_tools import get_campaign_finances, get_top_campaign_finances


def _write(path: Path, rows):
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "part-000.parquet")


def _cand(sq, urna, cargo="PRESIDENTE", uf="BR", ano=2022):
    return {"ANO_ELEICAO": ano, "SG_UF": uf, "SQ_CANDIDATO": sq, "NM_CANDIDATO": urna, "NM_URNA_CANDIDATO": urna,
            "SG_PARTIDO": "PT", "DS_CARGO": cargo, "NR_CANDIDATO": 1, "NM_SOCIAL_CANDIDATO": "#NULO",
            "DS_SITUACAO_CANDIDATURA": "APTO", "NR_TURNO": 1, "DS_SIT_TOT_TURNO": "#NE"}


def _rec(sq, prest, valor, origem="Recursos de pessoas físicas", fonte="OUTROS RECURSOS", cargo="Presidente",
         uf="BR", tipo="FINAL", nome=None):
    return {"SQ_CANDIDATO": sq, "SQ_PRESTADOR_CONTAS": prest, "NM_CANDIDATO": nome or f"CAND {sq}", "SG_PARTIDO": "PT",
            "SG_UF": uf, "DS_CARGO": cargo, "TP_PRESTACAO_CONTAS": tipo, "DS_ORIGEM_RECEITA": origem,
            "DS_FONTE_RECEITA": fonte, "VR_RECEITA": valor, "NM_DOADOR": "FULANO DOADOR", "NR_CPF_CNPJ_DOADOR": 123}


def _desp(sq, prest, valor, origem="Publicidade por materiais impressos", cargo="Presidente", uf="BR",
          tipo="FINAL", nome=None):
    return {"SQ_CANDIDATO": sq, "SQ_PRESTADOR_CONTAS": prest, "NM_CANDIDATO": nome or f"CAND {sq}", "SG_PARTIDO": "PT",
            "SG_UF": uf, "DS_CARGO": cargo, "TP_PRESTACAO_CONTAS": tipo, "DS_ORIGEM_DESPESA": origem,
            "VR_DESPESA_CONTRATADA": valor, "NM_FORNECEDOR": "EMPRESA X"}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    t = tmp_path / "tse"
    _write(t / "candidatos" / "ano=2022", [
        _cand(1, "LULA"), _cand(2, "JAIR"), _cand(3, "SEM CONTAS"), _cand(4, "DEP", "DEPUTADO FEDERAL", "SP"),
        _cand(5, "DEP2", "DEPUTADO FEDERAL", "RJ"),
    ])
    _write(t / "candidatos" / "ano=2026", [_cand(900, "NOVO", "GOVERNADOR", "SP", 2026)])
    pc = t / "prestacao_contas"
    _write(pc / "receitas" / "ano=2022", [
        _rec(1, 11, 1000.0, "Recursos de partido político", "FUNDO ESPECIAL", nome="LUIZ LULA"),
        _rec(1, 11, 500.0, "Recursos de partido político", "FUNDO PARTIDARIO", nome="LUIZ LULA"),
        _rec(1, 11, 250.0, "Recursos de pessoas físicas", nome="LUIZ LULA"),
        _rec(1, 11, 0.0, "#NULO", "#NULO", nome="LUIZ LULA"),
        _rec(2, 22, 800.0, nome="JAIR M"),
        _rec(4, 44, 100.0, cargo="Deputado Federal", uf="SP", nome="DEP SP"),
        _rec(5, 55, 300.0, cargo="Deputado Federal", uf="RJ", nome="DEP RJ"),
    ])
    _write(pc / "despesas_contratadas" / "ano=2022", [
        _desp(1, 11, 900.0, nome="LUIZ LULA"),
        _desp(1, 11, 300.0, "Despesas com pessoal", nome="LUIZ LULA"),
        _desp(2, 22, 5000.0, nome="JAIR M"),
        _desp(4, 44, 40.0, cargo="Deputado Federal", uf="SP", nome="DEP SP"),
        _desp(5, 55, 60.0, cargo="Deputado Federal", uf="RJ", nome="DEP RJ"),
    ])
    _write(pc / "despesas_pagas" / "ano=2022", [
        {"SQ_PRESTADOR_CONTAS": 11, "VR_PAGTO_DESPESA": 700.0},
        {"SQ_PRESTADOR_CONTAS": 11, "VR_PAGTO_DESPESA": 100.0},
        {"SQ_PRESTADOR_CONTAS": 22, "VR_PAGTO_DESPESA": 4000.0},
    ])
    _write(pc / "receitas" / "ano=2026", [_rec(900, 90, 70.0, cargo="Governador", uf="SP", tipo="PARCIAL")])
    return t.parent


class TestCampaignFinances:
    def test_caminho_feliz(self, base):
        res = get_campaign_finances(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["status"] == "ok"
        assert res["nome_urna"] == "LULA" and res["cargo"] == "PRESIDENTE"
        assert res["receitas"]["total"] == pytest.approx(1750.0)
        assert res["receitas"]["quantidade"] == 4
        assert res["despesas_contratadas"]["total"] == pytest.approx(1200.0)
        assert res["despesas_contratadas"]["quantidade"] == 2
        assert res["despesas_pagas"]["total"] == pytest.approx(800.0)
        assert res["despesas_pagas"]["quantidade"] == 2

    def test_composicao_das_receitas_e_despesas(self, base):
        res = get_campaign_finances(1, ano=2022, base_dir=base)
        por_origem = {o["origem"]: o["valor"] for o in res["receitas"]["por_origem"]}
        assert por_origem["Recursos de partido político"] == pytest.approx(1500.0)
        assert "#NULO" not in por_origem
        por_fonte = {f["fonte"]: f["valor"] for f in res["receitas"]["por_fonte"]}
        assert por_fonte["FUNDO ESPECIAL"] == pytest.approx(1000.0) and por_fonte["FUNDO PARTIDARIO"] == pytest.approx(500.0)
        assert res["despesas_contratadas"]["por_categoria"][0] == {
            "categoria": "Publicidade por materiais impressos", "valor": 900.0}

    def test_despesas_pagas_so_do_prestador_do_candidato(self, base):
        # o prestador 22 (Jair) tem 4.000 pagos; não podem entrar nas contas de Lula
        assert get_campaign_finances(1, ano=2022, base_dir=base)["despesas_pagas"]["total"] == pytest.approx(800.0)
        assert get_campaign_finances(2, ano=2022, base_dir=base)["despesas_pagas"]["total"] == pytest.approx(4000.0)

    def test_nao_expoe_doador_nem_fornecedor(self, base):
        blob = str(get_campaign_finances(1, ano=2022, base_dir=base))
        for banned in ("FULANO DOADOR", "EMPRESA X", "123", "cpf", "cnpj"):
            assert banned not in blob

    def test_prestacao_final_nao_e_parcial(self, base):
        res = get_campaign_finances(1, ano=2022, base_dir=base)
        assert res["tipo_prestacao"] == "FINAL" and res["prestacao_final"] is True
        assert "aviso" not in res

    def test_prestacao_parcial_e_declarada(self, base):
        res = get_campaign_finances(900, ano=2026, base_dir=base)
        assert res["encontrado"] is True and res["tipo_prestacao"] == "PARCIAL"
        assert res["prestacao_final"] is False and "parcia" in res["aviso"]
        assert res["despesas_contratadas"]["total"] is None  # tabela de despesas de 2026 ausente: não é zero

    def test_candidato_sem_prestacao_nao_e_gasto_zero(self, base):
        res = get_campaign_finances(3, ano=2022, base_dir=base)
        assert res["encontrado"] is False and res["status"] == "sem_prestacao"

    def test_inexistente_texto_livre_e_sem_ano(self, base):
        assert get_campaign_finances(99, ano=2022, base_dir=base)["status"] == "nao_encontrado"
        assert get_campaign_finances("Lula", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"
        assert get_campaign_finances(1, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"

    def test_ano_sem_tabelas(self, base, tmp_path):
        outro = tmp_path / "outro"
        _write(outro / "tse" / "candidatos" / "ano=2022", [_cand(1, "LULA")])
        assert get_campaign_finances(1, ano=2022, base_dir=outro)["status"] == "resultado_indisponivel"


class TestTopCampaignFinances:
    def test_ranking_de_despesas(self, base):
        res = get_top_campaign_finances("Presidente", ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["metrica"] == "despesas_contratadas"
        assert [c["sq_candidato"] for c in res["candidatos"]] == [2, 1]
        assert res["candidatos"][0]["valor"] == pytest.approx(5000.0) and res["candidatos"][0]["posicao"] == 1
        assert res["valor_total_cargo"] == pytest.approx(6200.0)

    def test_ranking_de_receitas(self, base):
        res = get_top_campaign_finances("Presidente", ano=2022, metrica="receitas", base_dir=base)
        assert [c["sq_candidato"] for c in res["candidatos"]] == [1, 2]
        assert res["candidatos"][0]["valor"] == pytest.approx(1750.0)

    def test_filtro_de_uf_e_top_n(self, base):
        res = get_top_campaign_finances("Deputado Federal", ano=2022, uf="rj", base_dir=base)
        assert [c["sq_candidato"] for c in res["candidatos"]] == [5] and res["uf"] == "RJ"
        res = get_top_campaign_finances("Presidente", ano=2022, top_n=1, base_dir=base)
        assert len(res["candidatos"]) == 1 and res["total_candidatos"] == 2

    def test_sem_uf_soma_o_pais(self, base):
        res = get_top_campaign_finances("Deputado Federal", ano=2022, base_dir=base)
        assert {c["sq_candidato"] for c in res["candidatos"]} == {4, 5}

    def test_metrica_cargo_e_ano_invalidos(self, base):
        assert get_top_campaign_finances("Presidente", ano=2022, metrica="lucro", base_dir=base)["status"] == "especificacao_insuficiente"
        assert get_top_campaign_finances("Rei", ano=2022, base_dir=base)["status"] == "cargo_invalido"
        assert get_top_campaign_finances("Presidente", ano=None, base_dir=base)["status"] == "especificacao_insuficiente"

    def test_sem_dados_do_cargo_ou_do_ano(self, base):
        assert get_top_campaign_finances("Senador", ano=2022, base_dir=base)["status"] == "sem_resultado"
        assert get_top_campaign_finances("Presidente", ano=2018, base_dir=base)["status"] == "resultado_indisponivel"

    def test_ano_2026_avisa_que_e_parcial(self, base):
        res = get_top_campaign_finances("Governador", ano=2026, metrica="receitas", base_dir=base)
        assert res["encontrado"] is True and "parcia" in res["aviso"]

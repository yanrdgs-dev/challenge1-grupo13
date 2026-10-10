"""Testes das tools de perfil e patrimônio do TSE (Fase 1, passo 3).

`check_candidate_profile`, `get_candidate_assets`, `check_cash_and_special_assets` e
`verify_official_social_media`. Regras: o ID é o `SQ_CANDIDATO` canônico (regra 2); ausência de bem não é
patrimônio zero (docs/data_schemas.md 8.3); CPF, e-mail, título e data de nascimento nunca saem (regra 2).
"""

from pathlib import Path

import polars as pl
import pytest

from src.tools.tse_perfil_tools import (
    check_candidate_profile,
    check_cash_and_special_assets,
    get_candidate_assets,
    verify_official_social_media,
)


def _write(path: Path, rows):
    path.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path / "part-000.parquet")


def _cand(sq, urna, genero="MASCULINO", instrucao="SUPERIOR COMPLETO", civil="SOLTEIRO(A)", cor="BRANCA",
          ocupacao="ADVOGADO", nasc="SP", ano=2022, turno=1):
    return {"ANO_ELEICAO": ano, "SG_UF": "SP", "SQ_CANDIDATO": sq, "NM_CANDIDATO": urna, "NM_URNA_CANDIDATO": urna,
            "SG_PARTIDO": "PT", "DS_CARGO": "DEPUTADO FEDERAL", "NR_CANDIDATO": 1, "NM_SOCIAL_CANDIDATO": "#NULO",
            "DS_SITUACAO_CANDIDATURA": "APTO", "NR_TURNO": turno, "DS_SIT_TOT_TURNO": "ELEITO",
            "DS_GENERO": genero, "DS_GRAU_INSTRUCAO": instrucao, "DS_ESTADO_CIVIL": civil, "DS_COR_RACA": cor,
            "DS_OCUPACAO": ocupacao, "SG_UF_NASCIMENTO": nasc}


def _bem(sq, tipo, valor, desc="x"):
    return {"ANO_ELEICAO": 2022, "SG_UF": "SP", "SQ_CANDIDATO": sq, "DS_TIPO_BEM_CANDIDATO": tipo,
            "DS_BEM_CANDIDATO": desc, "VR_BEM_CANDIDATO": valor}


def _rede(sq, url, ordem=1):
    return {"SQ_CANDIDATO": sq, "NR_ORDEM": ordem, "DS_URL": url, "AA_ELEICAO": 2022, "SG_UF": "SP"}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    b = tmp_path / "tse"
    _write(b / "candidatos" / "ano=2022", [
        _cand(1, "RICO"), _cand(1, "RICO", turno=2),
        _cand(2, "SEM BENS", genero="FEMININO", cor="PARDA", ocupacao="#NULO", nasc="NÃO DIVULGÁVEL"),
        _cand(3, "SO ZERO"),
        _cand(4, "SEM REDES"),
    ])
    _write(b / "candidatos_complementar" / "ano=2022", [
        {"SQ_CANDIDATO": 1, "NR_IDADE_DATA_POSSE": "52", "ST_REELEICAO": "S", "DS_NACIONALIDADE": "BRASILEIRA NATA",
         "ST_DECLARAR_BENS": "S"},
        {"SQ_CANDIDATO": 2, "NR_IDADE_DATA_POSSE": "#NE", "ST_REELEICAO": "Não divulgável",
         "DS_NACIONALIDADE": "BRASILEIRA NATA", "ST_DECLARAR_BENS": "N"},
    ])
    _write(b / "bens" / "ano=2022", [
        _bem(1, "Casa", 500_000.0, "Casa em SP"),
        _bem(1, "Apartamento", 300_000.0),
        _bem(1, "Dinheiro em espécie - moeda nacional", 20_000.0),
        _bem(1, "Dinheiro em espécie - moeda estrangeira", 5_000.0),
        _bem(1, "Aeronave", 1_000_000.0, "Avião monomotor"),
        _bem(1, "Embarcação", 80_000.0),
        _bem(1, "Jóia, quadro, objeto de arte, de coleção, antiguidade, etc.", 15_000.0),
        _bem(1, "OUTROS BENS E DIREITOS", 0.0),
        _bem(3, "OUTROS BENS E DIREITOS", 0.0),
        _bem(3, "Casa", -10.0),
    ])
    _write(b / "redes_sociais" / "ano=2022", [
        _rede(1, "https://www.instagram.com/rico_oficial/", 1),
        _rede(1, "https://instagram.com/rico_oficial", 2),  # mesmo perfil, outra grafia
        _rede(1, "https://twitter.com/rico", 3),
        _rede(1, "https://www.facebook.com/rico.pol", 4),
        _rede(1, "https://x.com/rico2", 5),
        _rede(2, "https://youtube.com/c/semBens", 1),
        _rede(2, "#NULO", 2),
    ])
    return b.parent


class TestProfile:
    def test_caminho_feliz(self, base):
        res = check_candidate_profile(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["status"] == "ok"
        assert res["genero"] == "MASCULINO" and res["grau_instrucao"] == "SUPERIOR COMPLETO"
        assert res["estado_civil"] == "SOLTEIRO(A)" and res["cor_raca"] == "BRANCA"
        assert res["ocupacao"] == "ADVOGADO" and res["uf_nascimento"] == "SP"
        assert res["idade_na_posse"] == 52 and res["reeleicao"] is True
        assert res["nacionalidade"] == "BRASILEIRA NATA"

    def test_nao_divulgavel_e_marcadores_viram_sem_dado(self, base):
        res = check_candidate_profile(2, ano=2022, base_dir=base)
        assert res["genero"] == "FEMININO" and res["cor_raca"] == "PARDA"
        assert res["ocupacao"] is None and res["uf_nascimento"] is None
        assert res["idade_na_posse"] is None and res["reeleicao"] is None

    def test_nunca_expoe_dado_pessoal(self, base):
        res = check_candidate_profile(1, ano=2022, base_dir=base)
        blob = " ".join(res.keys()).lower()
        for banned in ("cpf", "titulo", "email", "nascimento_data", "dt_nasc"):
            assert banned not in blob

    def test_dois_turnos_nao_duplicam(self, base):
        assert check_candidate_profile(1, ano=2022, base_dir=base)["sq_candidato"] == 1

    def test_sem_complementar_devolve_o_que_o_cadastro_tem(self, tmp_path):
        _write(tmp_path / "tse" / "candidatos" / "ano=2022", [_cand(1, "X")])
        res = check_candidate_profile(1, ano=2022, base_dir=tmp_path)
        assert res["encontrado"] is True and res["idade_na_posse"] is None and res["genero"] == "MASCULINO"

    def test_inexistente_texto_livre_e_sem_ano(self, base):
        assert check_candidate_profile(99, ano=2022, base_dir=base)["status"] == "nao_encontrado"
        assert check_candidate_profile("Rico", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"
        assert check_candidate_profile(1, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"


class TestAssets:
    def test_total_e_composicao(self, base):
        res = get_candidate_assets(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["declarou_bens"] is True
        assert res["quantidade_bens"] == 8
        assert res["valor_total_declarado"] == pytest.approx(1_920_000.0)
        assert res["bens_valor_zero"] == 1
        assert res["maior_bem"]["tipo"] == "Aeronave" and res["maior_bem"]["valor"] == 1_000_000.0
        assert res["por_tipo"][0]["tipo"] == "Aeronave"
        assert res["por_tipo"][0]["quantidade"] == 1

    def test_valor_zero_e_negativo_sao_contados_a_parte(self, base):
        res = get_candidate_assets(3, ano=2022, base_dir=base)
        assert res["quantidade_bens"] == 2
        assert res["bens_valor_zero"] == 1 and res["bens_valor_negativo"] == 1

    def test_sem_bem_nao_e_patrimonio_zero(self, base):
        res = get_candidate_assets(2, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["declarou_bens"] is False
        assert res["valor_total_declarado"] is None and res["quantidade_bens"] == 0
        assert "não" in res["aviso"] and "zero" in res["aviso"]

    def test_inexistente_e_ano_sem_tabela(self, base, tmp_path):
        assert get_candidate_assets(99, ano=2022, base_dir=base)["status"] == "nao_encontrado"
        outro = tmp_path / "outro"
        _write(outro / "tse" / "candidatos" / "ano=2022", [_cand(1, "X")])
        assert get_candidate_assets(1, ano=2022, base_dir=outro)["status"] == "resultado_indisponivel"

    def test_texto_livre_e_sem_ano(self, base):
        assert get_candidate_assets("Rico", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"
        assert get_candidate_assets(1, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"


class TestCashAndSpecialAssets:
    def test_dinheiro_e_bens_especiais(self, base):
        res = check_cash_and_special_assets(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True
        assert res["dinheiro_em_especie"]["valor"] == pytest.approx(25_000.0)
        assert res["dinheiro_em_especie"]["quantidade"] == 2
        especiais = {b["categoria"]: b for b in res["bens_especiais"]}
        assert especiais["Aeronave"]["valor"] == 1_000_000.0
        assert especiais["Embarcação"]["quantidade"] == 1
        assert "Jóia, quadro, objeto de arte, de coleção, antiguidade, etc." in especiais

    def test_candidato_com_bens_mas_sem_especiais(self, base):
        res = check_cash_and_special_assets(3, ano=2022, base_dir=base)
        assert res["declarou_bens"] is True
        assert res["dinheiro_em_especie"]["quantidade"] == 0 and res["bens_especiais"] == []

    def test_sem_nenhum_bem_nao_afirma_ausencia(self, base):
        res = check_cash_and_special_assets(2, ano=2022, base_dir=base)
        assert res["declarou_bens"] is False and res["dinheiro_em_especie"]["valor"] is None
        assert "aviso" in res

    def test_inexistente_e_texto_livre(self, base):
        assert check_cash_and_special_assets(99, ano=2022, base_dir=base)["status"] == "nao_encontrado"
        assert check_cash_and_special_assets("x", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"


class TestSocialMedia:
    def test_lista_deduplicada_e_classificada(self, base):
        res = verify_official_social_media(1, ano=2022, base_dir=base)
        assert res["encontrado"] is True
        redes = sorted((l["rede"], l["url"]) for l in res["links"])
        assert len(res["links"]) == 4  # instagram repetido conta uma vez
        assert {l["rede"] for l in res["links"]} == {"instagram", "twitter", "facebook"}
        assert res["total_links"] == 4 and redes

    def test_x_com_e_twitter_sao_a_mesma_rede(self, base):
        res = verify_official_social_media(1, ano=2022, base_dir=base)
        assert sum(1 for l in res["links"] if l["rede"] == "twitter") == 2

    def test_termo_registrado(self, base):
        ok = verify_official_social_media(1, ano=2022, termo="@rico_oficial", base_dir=base)
        assert ok["termo_registrado"] is True and ok["link_correspondente"]["rede"] == "instagram"
        no = verify_official_social_media(1, ano=2022, termo="@outro_perfil", base_dir=base)
        assert no["termo_registrado"] is False and no["link_correspondente"] is None

    def test_marcador_nulo_nao_e_link(self, base):
        res = verify_official_social_media(2, ano=2022, base_dir=base)
        assert [l["rede"] for l in res["links"]] == ["youtube"]

    def test_sem_links_declara_o_limite_da_fonte(self, base):
        res = verify_official_social_media(4, ano=2022, base_dir=base)
        assert res["encontrado"] is True and res["links"] == []
        assert "registr" in res["aviso"]

    def test_inexistente_texto_livre_e_sem_ano(self, base):
        assert verify_official_social_media(99, ano=2022, base_dir=base)["status"] == "nao_encontrado"
        assert verify_official_social_media("x", ano=2022, base_dir=base)["status"] == "entidade_nao_resolvida"
        assert verify_official_social_media(1, ano=None, base_dir=base)["status"] == "especificacao_insuficiente"

"""Cadeia real build_parquet -> dim_politicos sobre amostras reais pequenas e sanitizadas (sem CPF, e-mail etc.).

Pega desencontros entre o formato que as fontes entregam e o que o dim_politicos espera, que testes com
dados sintéticos não pegam.
"""

import shutil
from pathlib import Path

import polars as pl
import pytest

from src.etl.build_dim_politicos import build_and_save_dim_politicos
from src.etl.build_parquet import process_all_datasets
from src.etl.senado_cadastro import normalize_senado_senadores
from src.tools.gastos_tools import check_parliamentary_expenses, get_top_ceap_spender, list_expense_categories
from src.tools.legislativo_tools import get_proposition_tramitation_history
from src.tools.politician_cache import PoliticianCache
from src.tools.resolve_politician import resolve_politician

FIX = Path(__file__).parent / "fixtures" / "ingestion"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("chain")
    ds, out = tmp / "datasets", tmp / "processed"
    layout = {
        "deputados.csv": "camara/cadastro",
        "Ano-2026.csv": "camara/ceap",
        "senadores.csv": "senado/cadastro",
        "consulta_cand_2026_BRASIL.csv": "tse/candidatos",
        "consulta_cand_complementar_2026_BRASIL.csv": "tse/candidatos",
        "ceaps_2026.csv": "senado/ceaps",
        "proposicoes-2026.csv": "camara/proposicoes",
        "materias-2026.csv": "senado/materias",
    }
    for name, sub in layout.items():
        (ds / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / name, ds / sub / name)
    failures = []
    process_all_datasets(datasets_dir=ds, output_base=out, failures=failures)
    assert failures == [], failures
    dim = build_and_save_dim_politicos(
        output_path=str(out / "dim_politicos.parquet"),
        camara_deputados_path=str(out / "camara" / "deputados.parquet"),
        senado_senadores_path=str(out / "senado" / "senadores.parquet"),
        camara_ceap_pattern=str(out / "camara" / "ceap" / "**" / "*.parquet"),
        tse_candidatos_pattern=str(out / "tse" / "candidatos" / "**" / "*.parquet"),
    )
    return {"out": out, "dim": pl.read_parquet(dim)}


def test_samples_contain_no_personal_identifiers():
    for f in FIX.glob("*.csv"):
        raw = f.read_bytes().decode("latin1")
        import re

        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", raw), f"CPF em {f.name}"
        assert "@" not in raw, f"e-mail em {f.name}"


def test_ceap_keeps_the_join_key_dim_politicos_needs(built):
    ceap = pl.read_parquet(next((built["out"] / "camara" / "ceap").rglob("*.parquet")))
    assert "ideCadastro" in ceap.columns


def test_senadores_are_one_row_per_senator_with_the_columns_dim_politicos_reads(built):
    sen = pl.read_parquet(built["out"] / "senado" / "senadores.parquet")
    assert sen.height == 2  # a fonte traz uma linha por suplente/exercício; são 2 senadores
    assert {"Nome Parlamentar", "UF", "Partido", "Mandato"} <= set(sen.columns)
    alan = sen.filter(pl.col("Nome Parlamentar") == "Alan Rick").to_dicts()[0]
    assert alan["UF"] == "AC" and alan["Partido"] == "REPUBLICANOS" and alan["Mandato"] == "2023-2031"


def test_dim_politicos_has_both_houses_without_duplicates(built):
    dim = built["dim"]
    assert dim["casa"].value_counts().sort("casa").to_dicts() == [
        {"casa": "Câmara dos Deputados", "count": 3}, {"casa": "Senado Federal", "count": 2}]
    assert dim.select("nome_normalizado", "casa").unique().height == dim.height


def test_deputy_is_enriched_from_ceap_and_tse(built):
    dep = built["dim"].filter(pl.col("ideCadastro") == 62881).to_dicts()
    assert len(dep) == 1
    assert dep[0]["uf"] and dep[0]["partido"]  # vindos do CEAP via ideCadastro
    assert dep[0]["sq_candidato"] is not None  # casou com o TSE por nome + UF


def test_senators_have_names_and_no_cpf_column_anywhere(built):
    dim = built["dim"]
    names = dim.filter(pl.col("casa") == "Senado Federal")["nome_urna"].to_list()
    assert "Alan Rick" in names and all(names)
    assert not [c for c in dim.columns if "cpf" in c.lower()]


# ------------------------------- normalização isolada ------------------------------- #

def test_normalize_is_a_noop_for_the_friendly_format():
    df = pl.DataFrame({"Nome Parlamentar": ["A", "B"], "UF": ["SP", "RJ"], "Partido": ["X", "Y"], "Mandato": ["2019-2027"] * 2})
    assert normalize_senado_senadores(df).to_dicts() == df.to_dicts()


def test_normalize_dedupes_and_derives_mandate_years():
    raw = pl.read_csv(FIX / "senadores.csv", separator=";", infer_schema_length=0)
    out = normalize_senado_senadores(raw)
    assert out.height == 2 and out["Codigo Parlamentar"].n_unique() == 2
    assert out.filter(pl.col("Nome Parlamentar") == "Alan Rick")["Mandato"][0] == "2023-2031"


# ------------------------------- as tools do agente sobre os parquets gerados ------------------------------- #

@pytest.fixture
def fresh_cache():
    PoliticianCache.reset()
    yield
    PoliticianCache.reset()


def test_resolve_politician_returns_the_canonical_id_the_expense_tools_use(built, fresh_cache):
    res = resolve_politician("Danilo Forte", parquet_path=str(built["out"] / "dim_politicos.parquet"))
    assert res["ambiguous"] is False and res["ideCadastro"] == 62881, res


def test_camara_expenses_are_found_by_the_canonical_id(built):
    # 6 linhas de R$ 117,72 do deputado 62881 na amostra
    res = check_parliamentary_expenses(casa="camara", ano=2026, parlamentar_id="62881", base_dir=built["out"])
    assert res.qtd_lancamentos == 6 and res.valor_total == pytest.approx(706.32)


def test_camara_top_spender_is_identified_with_that_same_id(built):
    top = get_top_ceap_spender(casa="camara", ano=2026, base_dir=built["out"])
    assert top.gastadores[0].id_parlamentar == "62881"


def test_senator_resolved_by_name_has_the_code_the_senate_expense_tool_joins_on(built, fresh_cache):
    res = resolve_politician("Alan Rick", cargo="Senador", parquet_path=str(built["out"] / "dim_politicos.parquet"))
    assert res["ambiguous"] is False and res["cod_senador"] == 5672, res
    expenses = check_parliamentary_expenses(
        casa="senado", ano=2026, parlamentar_id=str(res["cod_senador"]), base_dir=built["out"])
    # decimais com vírgula e milhar da fonte convertidos: 462,18 + 109,32 + 4000,00 + 749,00 + 3322,77
    assert expenses.qtd_lancamentos == 5 and expenses.valor_total == pytest.approx(8643.27)


def test_expense_categories_come_from_the_ingested_data(built):
    cats = list_expense_categories(casa="camara", base_dir=built["out"])
    assert any("ESCRIT" in c.categoria.upper() for c in cats.categorias)


def test_camara_proposition_tramitation_and_apensamento(built):
    apensada = get_proposition_tramitation_history("camara", "2599890", data_dir=built["out"])
    livre = get_proposition_tramitation_history("camara", "281460", data_dir=built["out"])
    assert apensada["encontrado"] and apensada["apensada"] is True
    assert livre["encontrado"] and livre["apensada"] is False


def test_senado_materia_tramitation(built):
    res = get_proposition_tramitation_history("senado", "8632122", data_dir=built["out"])
    assert res["encontrado"] is True and res["situacao_atual"]


# ------------------------------- candidatos: turno e perfil preservados (Fase 1) ------------------------------- #

def test_candidatos_keep_the_round_so_runoff_rows_are_distinguishable(built):
    cand = pl.read_parquet(next((built["out"] / "tse" / "candidatos").rglob("*.parquet")))
    assert "NR_TURNO" in cand.columns and "DS_SIT_TOT_TURNO" in cand.columns


def test_candidatos_keep_the_profile_fields_the_profile_tool_needs(built):
    cand = pl.read_parquet(next((built["out"] / "tse" / "candidatos").rglob("*.parquet")))
    for col in ("DS_GENERO", "DS_GRAU_INSTRUCAO", "DS_ESTADO_CIVIL", "DS_COR_RACA", "DS_OCUPACAO", "SG_UF_NASCIMENTO"):
        assert col in cand.columns, col


def test_candidatos_still_drop_personal_identifiers(built):
    cand = pl.read_parquet(next((built["out"] / "tse" / "candidatos").rglob("*.parquet")))
    for col in ("NR_CPF_CANDIDATO", "DS_EMAIL", "NR_TITULO_ELEITORAL_CANDIDATO", "DT_NASCIMENTO"):
        assert col not in cand.columns, col

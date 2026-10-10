"""A poda automática por schema não pode descartar votos, valores nem chaves das tabelas do TSE."""

import polars as pl

from src.etl.build_parquet import clean_dataframe, process_all_datasets
from src.schemas.data_schemas import detect_schema_by_columns

CANDIDATOS = ["DT_GERACAO", "ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO",
              "SG_PARTIDO", "DS_CARGO", "CD_CARGO", "NR_CANDIDATO", "DS_SITUACAO_CANDIDATURA"]
MUNZONA = CANDIDATOS + ["NR_TURNO", "NR_ZONA", "CD_MUNICIPIO", "QT_VOTOS_NOMINAIS", "QT_VOTOS_NOMINAIS_VALIDOS",
                        "DS_SIT_TOT_TURNO"]
RECEITAS = ["AA_ELEICAO", "ST_TURNO", "SQ_PRESTADOR_CONTAS", "SG_UF", "CD_CARGO", "DS_CARGO", "SQ_CANDIDATO",
            "NR_CANDIDATO", "NM_CANDIDATO", "SG_PARTIDO", "SQ_RECEITA", "VR_RECEITA", "NM_DOADOR"]
DESPESAS_CONTRATADAS = ["AA_ELEICAO", "ST_TURNO", "SQ_PRESTADOR_CONTAS", "SG_UF", "CD_CARGO", "DS_CARGO",
                        "SQ_CANDIDATO", "NM_CANDIDATO", "SG_PARTIDO", "NM_FORNECEDOR", "VR_DESPESA_CONTRATADA"]
# 2022: despesas pagas vêm por prestador de contas, sem coluna de candidato
DESPESAS_PAGAS_2022 = ["AA_ELEICAO", "ST_TURNO", "SQ_PRESTADOR_CONTAS", "SG_UF", "SQ_DESPESA", "DS_DESPESA",
                       "VR_PAGTO_DESPESA"]
DESPESAS_PAGAS_COM_CANDIDATO = ["ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO",
                                "SG_PARTIDO", "DS_CARGO", "VR_PAGTO_DESPESA", "DS_TIPO_DESPESA", "NM_FORNECEDOR"]
BENS = ["ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO", "DS_TIPO_BEM_CANDIDATO", "DS_BEM_CANDIDATO", "VR_BEM_CANDIDATO"]


def frame(columns):
    return pl.DataFrame({c: ["1"] for c in columns})


# ------------------------------- detecção ------------------------------- #

def test_candidate_registry_is_still_detected():
    assert detect_schema_by_columns(CANDIDATOS) == "tse_candidatos"


def test_real_candidate_registry_with_turn_and_spending_cap_is_still_detected():
    # o cadastro oficial traz NR_TURNO e VR_DESPESA_MAX_CAMPANHA (teto de gastos): não são medidas de fato
    assert detect_schema_by_columns(CANDIDATOS + ["NR_TURNO", "VR_DESPESA_MAX_CAMPANHA"]) == "tse_candidatos"


def test_real_candidate_registry_is_pruned_to_the_formal_schema():
    cleaned = clean_dataframe(frame(CANDIDATOS + ["NR_TURNO", "VR_DESPESA_MAX_CAMPANHA"]), partition_col=None)
    assert "NR_TURNO" not in cleaned.columns and "VR_DESPESA_MAX_CAMPANHA" not in cleaned.columns
    assert "SQ_CANDIDATO" in cleaned.columns


def test_bens_are_still_detected():
    assert detect_schema_by_columns(BENS) == "tse_bens"


def test_despesas_with_candidate_columns_are_still_detected():
    assert detect_schema_by_columns(DESPESAS_PAGAS_COM_CANDIDATO) == "tse_despesas"


def test_vote_results_are_not_mistaken_for_candidate_registry():
    assert detect_schema_by_columns(MUNZONA) is None


def test_receitas_are_not_mistaken_for_candidate_registry():
    assert detect_schema_by_columns(RECEITAS) is None


def test_despesas_contratadas_are_not_mistaken_for_candidate_registry():
    assert detect_schema_by_columns(DESPESAS_CONTRATADAS) is None


def test_despesas_pagas_2022_without_candidate_key_are_not_pruned():
    assert detect_schema_by_columns(DESPESAS_PAGAS_2022) is None


# ------------------------------- efeito na poda ------------------------------- #

def test_munzona_keeps_turn_and_votes():
    cleaned = clean_dataframe(frame(MUNZONA), partition_col=None)
    assert {"NR_TURNO", "QT_VOTOS_NOMINAIS", "NR_ZONA", "CD_MUNICIPIO"} <= set(cleaned.columns)


def test_receitas_keep_value_and_donor():
    cleaned = clean_dataframe(frame(RECEITAS), partition_col=None)
    assert {"VR_RECEITA", "NM_DOADOR", "SQ_PRESTADOR_CONTAS"} <= set(cleaned.columns)


def test_despesas_pagas_2022_keep_provider_key_and_description():
    cleaned = clean_dataframe(frame(DESPESAS_PAGAS_2022), partition_col=None)
    assert {"SQ_PRESTADOR_CONTAS", "DS_DESPESA", "VR_PAGTO_DESPESA"} <= set(cleaned.columns)


# ------------------------------- build completo ------------------------------- #

def write_csv(path, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = ["2022" if c in ("ANO_ELEICAO", "AA_ELEICAO") else "1" for c in columns]
    path.write_bytes((";".join(columns) + "\n" + ";".join(row) + "\n").encode("latin1"))


def test_process_all_datasets_keeps_columns_of_tse_result_and_finance_tables(tmp_path):
    ds, out = tmp_path / "datasets", tmp_path / "out"
    write_csv(ds / "tse/votacao/munzona/votacao_candidato_munzona_2022/votacao_candidato_munzona_2022_BRASIL.csv", MUNZONA)
    write_csv(ds / "tse/prestacao_contas/receitas_candidatos_2022_BRASIL.csv", RECEITAS)
    write_csv(ds / "tse/prestacao_contas/despesas_contratadas_candidatos_2022_BRASIL.csv", DESPESAS_CONTRATADAS)
    write_csv(ds / "tse/prestacao_contas/despesas_pagas_candidatos_2022_BRASIL.csv", DESPESAS_PAGAS_2022)
    write_csv(ds / "tse/candidatos/consulta_cand_2022_BRASIL.csv", CANDIDATOS)

    process_all_datasets(datasets_dir=ds, output_base=out)

    def cols(sub):
        return set(pl.read_parquet(next((out / sub).rglob("*.parquet"))).columns)

    assert {"NR_TURNO", "QT_VOTOS_NOMINAIS"} <= cols("tse/votacao_munzona")
    assert "VR_RECEITA" in cols("tse/prestacao_contas/receitas")
    assert "VR_DESPESA_CONTRATADA" in cols("tse/prestacao_contas/despesas_contratadas")
    assert {"SQ_PRESTADOR_CONTAS", "VR_PAGTO_DESPESA"} <= cols("tse/prestacao_contas/despesas_pagas")
    # o cadastro de candidatos continua podado pelo schema formal
    assert "DT_GERACAO" not in cols("tse/candidatos") and "SQ_CANDIDATO" in cols("tse/candidatos")


def test_runoff_rows_of_the_same_candidate_stay_distinguishable_after_pruning():
    raw = pl.DataFrame({
        "ANO_ELEICAO": [2022, 2022], "NR_TURNO": [1, 2], "SG_UF": ["BR", "BR"], "SQ_CANDIDATO": [280001, 280001],
        "NM_CANDIDATO": ["A", "A"], "NM_URNA_CANDIDATO": ["A", "A"], "SG_PARTIDO": ["X", "X"],
        "DS_CARGO": ["PRESIDENTE", "PRESIDENTE"], "CD_CARGO": [1, 1], "DS_SIT_TOT_TURNO": ["2º TURNO", "ELEITO"],
        "NR_CPF_CANDIDATO": ["1", "1"], "DS_EMAIL": ["a@b", "a@b"],
    })
    cleaned = clean_dataframe(raw, partition_col=None)
    assert sorted(cleaned["NR_TURNO"].to_list()) == [1, 2]
    assert "NR_CPF_CANDIDATO" not in cleaned.columns and "DS_EMAIL" not in cleaned.columns

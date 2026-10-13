"""Matérias do Senado: CSVs anuais (serviço /processo) viram senado/materias.parquet, lido pela tool de tramitação."""

import polars as pl

from src.etl.build_parquet import process_all_datasets
from src.tools.legislativo_tools import _get_senado_tramitation

HEADER = ("id,codigoMateria,identificacao,apelido,objetivo,casaIdentificadora,enteIdentificador,tipoConteudo,"
          "ementa,tipoDocumento,dataApresentacao,autoria,urlDocumento,tramitando,dataDeliberacao,"
          "siglaTipoDeliberacao,normaGerada,ultimaInformacaoAtualizada,dataUltimaAtualizacao,situacaoAtual,"
          "dataSituacaoAtual")


def row(pid, ident, ementa, situacao):
    return (f'{pid},{pid + 1},"{ident}",,,SF,PLEN,"Projeto","{ementa}",PL,2024-01-02,"Senador X",'
            f'"https://legis.senado.leg.br/doc/{pid}",Sim,,,,,2024-05-06,"{situacao}",2024-05-06')


def build(tmp_path):
    d = tmp_path / "datasets" / "senado" / "materias"
    d.mkdir(parents=True)
    (d / "materias-2024.csv").write_text(
        "\n".join([HEADER, row(8549990, "PL 1/2024", "Dispõe sobre ação, coração e educação.", "Em tramitação")]) + "\n",
        encoding="utf-8")
    (d / "materias-2025.csv").write_text(
        "\n".join([HEADER, row(9000001, "PL 2/2025", "Outra matéria.", "Aprovada")]) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    summaries = process_all_datasets(datasets_dir=tmp_path / "datasets", output_base=out)
    return out, summaries


def test_materias_of_all_years_land_in_a_single_parquet(tmp_path):
    out, summaries = build(tmp_path)
    assert "Senado - Matérias" in [s["dataset_name"] for s in summaries]
    df = pl.read_parquet(out / "senado" / "materias.parquet")
    assert df.height == 2
    assert {"id", "identificacao", "ementa", "autoria", "situacaoAtual", "urlDocumento"} <= set(df.columns)
    assert "coração" in df["ementa"][0]  # utf-8 preservado


def test_senado_tramitation_tool_reads_the_generated_parquet(tmp_path):
    out, _ = build(tmp_path)
    result = _get_senado_tramitation(out, "9000001")
    assert result["encontrado"] is True
    assert result["situacao_atual"] == "Aprovada"
    assert result["detalhes"]["identificacao"] == "PL 2/2025"

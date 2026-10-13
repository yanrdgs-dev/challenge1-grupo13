"""Normalização do cadastro de senadores.

A fonte automática (`senador/lista/atual.csv`) é um XML achatado: cabeçalhos em forma de caminho e uma linha
por suplente/exercício do mesmo senador. O `dim_politicos` e as tools leem o formato legível
(`Nome Parlamentar`, `UF`, `Partido`, `Mandato`), com uma linha por senador.
"""

import polars as pl

PATH_PREFIX = "/atual/Parlamentares/Parlamentar/"

# coluna da fonte (sem o prefixo) -> coluna legível
RENAMES = {
    "IdentificacaoParlamentar/CodigoParlamentar": "Codigo Parlamentar",
    "IdentificacaoParlamentar/NomeParlamentar": "Nome Parlamentar",
    "IdentificacaoParlamentar/NomeCompletoParlamentar": "Nome Completo",
    "IdentificacaoParlamentar/SiglaPartidoParlamentar": "Partido",
    "IdentificacaoParlamentar/UfParlamentar": "UF",
    "IdentificacaoParlamentar/EmailParlamentar": "Email",
    "Mandato/DescricaoParticipacao": "Titular/Suplente",
}
START = "Mandato/PrimeiraLegislaturaDoMandato/DataInicio"
END = "Mandato/SegundaLegislaturaDoMandato/DataFim"


def normalize_senado_senadores(df: pl.DataFrame) -> pl.DataFrame:
    """Devolve uma linha por senador com colunas legíveis. No formato legível, não altera nada."""
    if "Nome Parlamentar" in df.columns or not any(c.startswith(PATH_PREFIX) for c in df.columns):
        return df

    df = df.rename({c: c[len(PATH_PREFIX):] for c in df.columns if c.startswith(PATH_PREFIX)})
    out = df.select(
        [pl.col(src).cast(pl.Utf8).alias(dst) for src, dst in RENAMES.items() if src in df.columns]
        + (
            [(pl.col(START).cast(pl.Utf8).str.slice(0, 4) + pl.lit("-") + pl.col(END).cast(pl.Utf8).str.slice(0, 4)).alias("Mandato")]
            if START in df.columns and END in df.columns else []
        )
    )
    return out.unique(subset=["Codigo Parlamentar"], keep="first", maintain_order=True)

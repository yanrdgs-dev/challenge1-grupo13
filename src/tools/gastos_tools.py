"""Tools do Grupo 3: Gastos da Cota Parlamentar (CEAP e CEAPS).

Implementa as ferramentas especificadas na Seção 3 de docs/tools_specification.md:
- 3.1 get_top_ceap_spender (Golden Dataset ID 1)
- 3.2 list_expense_categories (Golden Dataset IDs 2, 11, 16, 17, 22)
- 3.3 check_parliamentary_expenses (Golden Dataset ID 13)

Conformidade com a Constituição do Projeto (.specify/memory/constitution.md):
- Princípio I: Evidência rastreável com agregados e contagens estruturadas
- Princípio IV: Separação estrita entre dados transacionais e regras institucionais
- Princípio VII: TDD obrigatório
- Princípio VIII: Execução analítica 100% local (sem chamadas de rede externa)
"""

import logging
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import polars as pl

logger = logging.getLogger("Tools.Gastos")

# Schema canônico intermediário para unificação Câmara/Senado
CANONICAL_SCHEMA = {
    "id_parlamentar": pl.Utf8,
    "nome_parlamentar": pl.Utf8,
    "uf": pl.Utf8,
    "partido": pl.Utf8,
    "ano": pl.Int64,
    "categoria": pl.Utf8,
    "fornecedor": pl.Utf8,
    "valor": pl.Float64,
}


@dataclass
class TopSpenderItem:
    """Representa um parlamentar no ranking de gastos."""
    posicao: int
    nome_parlamentar: str
    uf: str
    partido: str
    valor_total: float
    id_parlamentar: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TopSpenderResponse:
    """Resposta estruturada da tool get_top_ceap_spender."""
    casa: str
    ano: int
    top_n: int
    gastadores: List[TopSpenderItem]
    total_parlamentares_analisados: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExpenseCategoryItem:
    """Representa uma categoria de despesa com métricas de volume e amostras."""
    categoria: str
    qtd_lancamentos: int
    valor_total: float
    exemplos: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExpenseCategoriesResponse:
    """Resposta estruturada da tool list_expense_categories."""
    casa: str
    total_categorias: int
    categorias: List[ExpenseCategoryItem]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExpenseAuditResult:
    """Resposta estruturada da tool check_parliamentary_expenses."""
    casa: str
    ano: int
    filtros_aplicados: Dict[str, Any]
    qtd_lancamentos: int
    valor_min: float
    valor_max: float
    valor_medio: float
    valor_total: float
    amostra: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _strip_accents(text: Optional[str]) -> str:
    """Remove acentos e normaliza para caixa baixa para buscas flexíveis."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower().strip()


def _matches_category(query: str, target: str) -> bool:
    """Verifica correspondência flexível entre o termo buscado e a categoria cadastrada.

    Suporta variações de gênero, número (ex.: singular 'combustível' vs plural 'combustíveis')
    e grafias sem acento.
    """
    if not query or not target:
        return False

    q_norm = _strip_accents(query)
    t_norm = _strip_accents(target)

    # Substring direta
    if q_norm in t_norm:
        return True

    # Comparação de radicais por tokens (ex: 'combust' em 'combustiveis', 'passag' em 'passagens')
    q_tokens = [t for t in "".join(c if c.isalnum() else " " for c in q_norm).split() if len(t) >= 4]
    t_tokens = [t for t in "".join(c if c.isalnum() else " " for c in t_norm).split() if len(t) >= 4]

    for qt in q_tokens:
        qt_root = qt[:5] if len(qt) >= 5 else qt[:4]
        for tt in t_tokens:
            tt_root = tt[:5] if len(tt) >= 5 else tt[:4]
            if qt_root == tt_root:
                return True

    return False


def _resolve_ceap_dataset(
    casa: str,
    ano: Optional[int] = None,
    base_dir: Optional[Path] = None,
) -> pl.LazyFrame:
    """Localiza e carrega partições Parquet da CEAP (Câmara) ou CEAPS (Senado) em LazyFrame normalizado.

    Args:
        casa: 'camara' ou 'senado'.
        ano: Ano de referência opcional para filtrar partições.
        base_dir: Caminho base para os dados processados (padrão: data/processed).

    Returns:
        polars.LazyFrame com colunas canônicas: id_parlamentar, nome_parlamentar,
        uf, partido, ano, categoria, fornecedor, valor.

    Raises:
        ValueError: Se a casa legislativa informada não for suportada.
    """
    clean_casa = casa.strip().lower()
    if clean_casa not in ("camara", "senado"):
        raise ValueError(f"Casa legislativa inválida: '{casa}'. Valores aceitos: 'camara', 'senado'.")

    root_dir = Path(base_dir) if base_dir else Path("data/processed")
    target_sub = "camara/ceap" if clean_casa == "camara" else "senado/ceaps"
    dataset_path = root_dir / target_sub

    parquet_files: List[Path] = []
    if dataset_path.exists():
        if ano is not None:
            # Procura em subpastas ano=<ano> ou arquivos específicos
            ano_dir = dataset_path / f"ano={ano}"
            if ano_dir.exists():
                parquet_files.extend(list(ano_dir.glob("*.parquet")))
            # Fallback para arquivos no formato ceap_2023.parquet ou 2023.parquet
            if not parquet_files:
                parquet_files.extend(list(dataset_path.glob(f"*{ano}*.parquet")))
        else:
            parquet_files.extend(list(dataset_path.glob("**/*.parquet")))

    if not parquet_files:
        logger.warning(
            "Nenhum arquivo Parquet localizado para casa='%s', ano=%s em '%s'",
            clean_casa,
            ano,
            dataset_path,
        )
        return pl.DataFrame(schema=CANONICAL_SCHEMA).lazy()

    # Mapeamento e normalização dependendo da origem
    try:
        raw_lf = pl.scan_parquet([str(p) for p in parquet_files])
        schema_cols = raw_lf.collect_schema().names()

        if clean_casa == "camara":
            # Resolução das colunas da Câmara (CEAP)
            # ideCadastro é o ID canônico (o mesmo devolvido por resolve_politician);
            # nuDeputadoId é um ID interno diferente e não serve para o join da regra 2.
            id_col = next(
                (c for c in ("ideCadastro", "idDeputado", "nuDeputadoId") if c in schema_cols),
                "nuDeputadoId",
            )
            nome_col = "txNomeParlamentar" if "txNomeParlamentar" in schema_cols else "nomeParlamentar"
            uf_col = "sgUF" if "sgUF" in schema_cols else "siglaUf"
            partido_col = "sgPartido" if "sgPartido" in schema_cols else "siglaPartido"
            ano_col = "numAno" if "numAno" in schema_cols else "ano"
            cat_col = "txtDescricao" if "txtDescricao" in schema_cols else "descricao"
            fornec_col = "txtFornecedor" if "txtFornecedor" in schema_cols else "fornecedor"
            vlr_col = "vlrLiquido" if "vlrLiquido" in schema_cols else "valorLiquido"

            norm_lf = raw_lf.select([
                pl.col(id_col).cast(pl.Utf8).fill_null("").alias("id_parlamentar"),
                pl.col(nome_col).cast(pl.Utf8).fill_null("NÃO INFORMADO").alias("nome_parlamentar"),
                pl.col(uf_col).cast(pl.Utf8).fill_null("").alias("uf"),
                pl.col(partido_col).cast(pl.Utf8).fill_null("").alias("partido"),
                (pl.col(ano_col).cast(pl.Int64) if ano_col in schema_cols else pl.lit(ano or 0).cast(pl.Int64)).alias("ano"),
                pl.col(cat_col).cast(pl.Utf8).fill_null("OUTROS").alias("categoria"),
                pl.col(fornec_col).cast(pl.Utf8).fill_null("").alias("fornecedor"),
                pl.col(vlr_col).cast(pl.Float64).fill_null(0.0).alias("valor"),
            ])
            return norm_lf

        else:
            # Resolução das colunas do Senado (CEAPS)
            id_col = "COD_SENADOR" if "COD_SENADOR" in schema_cols else "idSenador"
            nome_col = "SENADOR" if "SENADOR" in schema_cols else "NOME_SENADOR"
            uf_col = "UF" if "UF" in schema_cols else "siglaUf"
            partido_col = "PARTIDO" if "PARTIDO" in schema_cols else "siglaPartido"
            ano_col = "ANO" if "ANO" in schema_cols else "ano"
            cat_col = "TIPO_DESPESA" if "TIPO_DESPESA" in schema_cols else "tipoDespesa"
            fornec_col = "FORNECEDOR" if "FORNECEDOR" in schema_cols else "fornecedor"
            vlr_col = "VALOR_REEMBOLSADO" if "VALOR_REEMBOLSADO" in schema_cols else "vlrLiquido"

            norm_lf = raw_lf.select([
                (pl.col(id_col).cast(pl.Utf8).fill_null("") if id_col in schema_cols else pl.lit("")).alias("id_parlamentar"),
                pl.col(nome_col).cast(pl.Utf8).fill_null("NÃO INFORMADO").alias("nome_parlamentar"),
                pl.col(uf_col).cast(pl.Utf8).fill_null("").alias("uf"),
                pl.col(partido_col).cast(pl.Utf8).fill_null("").alias("partido"),
                (pl.col(ano_col).cast(pl.Int64) if ano_col in schema_cols else pl.lit(ano or 0).cast(pl.Int64)).alias("ano"),
                pl.col(cat_col).cast(pl.Utf8).fill_null("OUTROS").alias("categoria"),
                pl.col(fornec_col).cast(pl.Utf8).fill_null("").alias("fornecedor"),
                pl.col(vlr_col).cast(pl.Float64).fill_null(0.0).alias("valor"),
            ])
            return norm_lf

    except Exception as exc:
        logger.error("Erro ao processar partições Parquet de '%s': %s", dataset_path, exc, exc_info=True)
        return pl.DataFrame(schema=CANONICAL_SCHEMA).lazy()


def get_top_ceap_spender(
    casa: str,
    ano: int,
    top_n: int = 1,
    base_dir: Optional[Path] = None,
) -> TopSpenderResponse:
    """Identifica os parlamentares com maiores gastos na Cota Parlamentar (CEAP/CEAPS).

    Atende à Claim 1 do Golden Dataset v1 ("Em 2023, o deputado que mais gastou a cota...").

    Args:
        casa: 'camara' ou 'senado'.
        ano: Ano de exercício fiscal a analisar (ex: 2023).
        top_n: Quantidade de posições do ranking a retornar (padrão: 1).
        base_dir: Diretório base opcional dos dados processados (para injeção em testes).

    Returns:
        TopSpenderResponse contendo a lista dos maiores gastadores ordenados decrescentemente.
    """
    clean_casa = casa.strip().lower()
    lf = _resolve_ceap_dataset(casa=clean_casa, ano=ano, base_dir=base_dir)

    # Filtra por ano se a base contiver múltiplos anos
    lf_filtered = lf.filter(pl.col("ano") == ano)

    # Agrupa por parlamentar e soma os reembolsos líquidos
    aggregated = (
        lf_filtered.group_by(["id_parlamentar", "nome_parlamentar", "uf", "partido"])
        .agg(pl.col("valor").sum().alias("valor_total"))
        .sort(by="valor_total", descending=True)
    )

    df = aggregated.collect()
    total_parlamentares = df.height

    if total_parlamentares == 0:
        return TopSpenderResponse(
            casa=clean_casa,
            ano=ano,
            top_n=top_n,
            gastadores=[],
            total_parlamentares_analisados=0,
        )

    top_df = df.head(top_n)
    items: List[TopSpenderItem] = []
    for idx, row in enumerate(top_df.iter_rows(named=True), start=1):
        items.append(
            TopSpenderItem(
                posicao=idx,
                nome_parlamentar=row["nome_parlamentar"],
                uf=row["uf"],
                partido=row["partido"],
                valor_total=round(float(row["valor_total"]), 2),
                id_parlamentar=row["id_parlamentar"] or None,
            )
        )

    return TopSpenderResponse(
        casa=clean_casa,
        ano=ano,
        top_n=top_n,
        gastadores=items,
        total_parlamentares_analisados=total_parlamentares,
    )


def list_expense_categories(
    casa: str,
    incluir_exemplos: bool = True,
    ano: Optional[int] = None,
    base_dir: Optional[Path] = None,
) -> ExpenseCategoriesResponse:
    """Lista as categorias de despesas executadas empiricamente na base histórica da casa legislativa.

    Atende às Claims 2, 11, 16, 17 e 22 do Golden Dataset v1, fornecendo evidência empírica
    de utilização real da rubrica orçamentária.

    Args:
        casa: 'camara' ou 'senado'.
        incluir_exemplos: Se True, extrai amostras reais de fornecedores e valores por categoria.
        ano: Ano opcional de referência.
        base_dir: Diretório base opcional dos dados.

    Returns:
        ExpenseCategoriesResponse com todas as categorias ordenadas por frequência de uso.
    """
    clean_casa = casa.strip().lower()
    lf = _resolve_ceap_dataset(casa=clean_casa, ano=ano, base_dir=base_dir)

    if ano is not None:
        lf = lf.filter(pl.col("ano") == ano)

    # Agrupa por categoria com contagem e total gasto
    agg_lf = (
        lf.group_by("categoria")
        .agg([
            pl.len().alias("qtd_lancamentos"),
            pl.col("valor").sum().alias("valor_total"),
        ])
        .sort(by="qtd_lancamentos", descending=True)
    )

    df_cats = agg_lf.collect()
    total_cats = df_cats.height

    if total_cats == 0:
        return ExpenseCategoriesResponse(
            casa=clean_casa,
            total_categorias=0,
            categorias=[],
        )

    # Se exemplos foram solicitados, coletamos amostras de fornecedores por categoria
    exemplos_map: Dict[str, List[Dict[str, Any]]] = {}
    if incluir_exemplos:
        df_exemplos = (
            lf.select(["categoria", "fornecedor", "valor"])
            .filter(pl.col("valor") > 0)
            .collect()
        )
        for cat in df_cats["categoria"].to_list():
            amostra_cat = (
                df_exemplos.filter(pl.col("categoria") == cat)
                .head(3)
                .iter_rows(named=True)
            )
            exemplos_map[cat] = [
                {"fornecedor": row["fornecedor"], "valor": round(float(row["valor"]), 2)}
                for row in amostra_cat
            ]

    categorias_out: List[ExpenseCategoryItem] = []
    for row in df_cats.iter_rows(named=True):
        cat_nome = row["categoria"]
        categorias_out.append(
            ExpenseCategoryItem(
                categoria=cat_nome,
                qtd_lancamentos=int(row["qtd_lancamentos"]),
                valor_total=round(float(row["valor_total"]), 2),
                exemplos=exemplos_map.get(cat_nome, []),
            )
        )

    return ExpenseCategoriesResponse(
        casa=clean_casa,
        total_categorias=total_cats,
        categorias=categorias_out,
    )


def check_parliamentary_expenses(
    casa: str,
    ano: int,
    categoria: Optional[str] = None,
    parlamentar_id: Optional[str] = None,
    limite_amostra: int = 5,
    base_dir: Optional[Path] = None,
) -> ExpenseAuditResult:
    """Audita despesas detalhadas calculando agregados estatísticos (mínimo, máximo, média e total).

    Atende à Claim 13 do Golden Dataset v1 (desmentir teto fixo de R$ 500 para combustível
    apresentando despesas empíricas superiores).

    Args:
        casa: 'camara' ou 'senado'.
        ano: Ano de referência da despesa.
        categoria: Nome ou substring da categoria de gasto (busca insensível a acentos/caixa/plural).
        parlamentar_id: ID do parlamentar para restringir a consulta individualmente.
        limite_amostra: Quantidade máxima de linhas amostrais a retornar no campo amostra.
        base_dir: Diretório base opcional dos dados.

    Returns:
        ExpenseAuditResult com métricas calculadas e amostra dos registros.
    """
    clean_casa = casa.strip().lower()
    filtros: Dict[str, Any] = {"casa": clean_casa, "ano": ano}
    if categoria:
        filtros["categoria"] = categoria
    if parlamentar_id:
        filtros["parlamentar_id"] = parlamentar_id

    lf = _resolve_ceap_dataset(casa=clean_casa, ano=ano, base_dir=base_dir)
    lf = lf.filter(pl.col("ano") == ano)

    if parlamentar_id:
        clean_pid = str(parlamentar_id).strip()
        lf = lf.filter(pl.col("id_parlamentar") == clean_pid)

    df_base = lf.collect()

    if categoria:
        # Filtro em memória com correspondência flexível (acentos, plural e casing)
        mask = [_matches_category(categoria, cat) for cat in df_base["categoria"].to_list()]
        df_filtered = df_base.filter(pl.Series(mask))
    else:
        df_filtered = df_base

    qtd = df_filtered.height
    if qtd == 0:
        return ExpenseAuditResult(
            casa=clean_casa,
            ano=ano,
            filtros_aplicados=filtros,
            qtd_lancamentos=0,
            valor_min=0.0,
            valor_max=0.0,
            valor_medio=0.0,
            valor_total=0.0,
            amostra=[],
        )

    val_series = df_filtered["valor"]
    v_min = float(val_series.min() or 0.0)
    v_max = float(val_series.max() or 0.0)
    v_mean = float(val_series.mean() or 0.0)
    v_total = float(val_series.sum() or 0.0)

    # Amostra de registros
    amostra_rows = (
        df_filtered.select(["nome_parlamentar", "categoria", "fornecedor", "valor"])
        .head(limite_amostra)
        .iter_rows(named=True)
    )
    amostra = [
        {
            "parlamentar": r["nome_parlamentar"],
            "categoria": r["categoria"],
            "fornecedor": r["fornecedor"],
            "valor": round(float(r["valor"]), 2),
        }
        for r in amostra_rows
    ]

    return ExpenseAuditResult(
        casa=clean_casa,
        ano=ano,
        filtros_aplicados=filtros,
        qtd_lancamentos=qtd,
        valor_min=round(v_min, 2),
        valor_max=round(v_max, 2),
        valor_medio=round(v_mean, 2),
        valor_total=round(v_total, 2),
        amostra=amostra,
    )

"""Testes unitários e analíticos para a camada de dados DuckDB (Task 1.3 e Task 1.5)."""

from pathlib import Path
import polars as pl
import pytest

from src.database.duckdb_client import DuckDBClient


@pytest.fixture
def duckdb_test_client():
    """Fixture que instancia DuckDBClient em memória (:memory:) e popula dados fictícios controlados."""
    client = DuckDBClient(database_path=":memory:")

    # 1. Criação e carga da tabela de despesas de candidatos (TSE)
    client.execute("""
        CREATE TABLE despesas_candidatos (
            ano INT,
            sq_candidato BIGINT,
            nm_candidato VARCHAR,
            ds_cargo VARCHAR,
            sg_uf VARCHAR,
            vr_despesa_paga DOUBLE
        );
    """)
    client.execute("""
        INSERT INTO despesas_candidatos VALUES
            (2026, 1001, 'CANDIDATO ALFA', 'DEPUTADO FEDERAL', 'SP', 15000.50),
            (2026, 1001, 'CANDIDATO ALFA', 'DEPUTADO FEDERAL', 'SP', 25000.00),
            (2026, 1001, 'CANDIDATO ALFA', 'DEPUTADO FEDERAL', 'SP', 999.50),
            (2026, 1002, 'CANDIDATA BETA', 'DEPUTADO FEDERAL', 'RJ', 50000.00),
            (2026, 1002, 'CANDIDATA BETA', 'DEPUTADO FEDERAL', 'RJ', 12500.25);
    """)

    # 2. Criação e carga da tabela de votações nominais (Câmara)
    client.execute("""
        CREATE TABLE votacoes_parlamentares (
            id_votacao VARCHAR,
            proposicao_id VARCHAR,
            deputado_nome VARCHAR,
            sigla_partido VARCHAR,
            sigla_uf VARCHAR,
            voto VARCHAR,
            data DATE
        );
    """)
    client.execute("""
        INSERT INTO votacoes_parlamentares VALUES
            ('VOT-01', 'PL-2630', 'DEPUTADO SILVA', 'PARTIDO A', 'SP', 'Sim', '2026-03-15'),
            ('VOT-01', 'PL-2630', 'DEPUTADO SOUZA', 'PARTIDO B', 'RJ', 'Não', '2026-03-15'),
            ('VOT-01', 'PL-2630', 'DEPUTADA LIMA', 'PARTIDO A', 'MG', 'Sim', '2026-03-15'),
            ('VOT-02', 'PEC-45', 'DEPUTADO SILVA', 'PARTIDO A', 'SP', 'Sim', '2026-04-10'),
            ('VOT-02', 'PEC-45', 'DEPUTADO SOUZA', 'PARTIDO B', 'RJ', 'Abstenção', '2026-04-10'),
            ('VOT-02', 'PEC-45', 'DEPUTADA LIMA', 'PARTIDO A', 'MG', 'Não', '2026-04-10');
    """)

    yield client
    client.close()


def test_duckdb_client_init_and_context_manager():
    """Valida inicialização em memória e encerramento limpo via context manager."""
    with DuckDBClient(database_path=":memory:") as client:
        assert client.is_in_memory is True
        assert client.read_only is False
        res = client.query("SELECT 100 AS teste")
        assert res == [{"teste": 100}]


def test_duckdb_query_returns_dict_list(duckdb_test_client):
    """Valida que o método query() retorna lista de dicionários mapeados por coluna."""
    results = duckdb_test_client.query(
        "SELECT nm_candidato, ds_cargo FROM despesas_candidatos WHERE sq_candidato = ?",
        [1001],
    )

    assert isinstance(results, list)
    assert len(results) == 3
    assert results[0] == {
        "nm_candidato": "CANDIDATO ALFA",
        "ds_cargo": "DEPUTADO FEDERAL",
    }


def test_duckdb_query_df_returns_polars_dataframe(duckdb_test_client):
    """Valida que o método query_df() retorna diretamente um DataFrame nativo do Polars."""
    df = duckdb_test_client.query_df(
        "SELECT nm_candidato, vr_despesa_paga FROM despesas_candidatos WHERE sq_candidato = ?",
        [1002],
    )

    assert isinstance(df, pl.DataFrame)
    assert df.height == 2
    assert "vr_despesa_paga" in df.columns
    assert df.schema["vr_despesa_paga"] == pl.Float64
    assert df["vr_despesa_paga"].to_list() == [50000.0, 12500.25]


def test_duckdb_parameterized_query_prevents_sql_injection(duckdb_test_client):
    """Valida que consultas parametrizadas tratam tentativas de SQL Injection de forma segura."""
    malicious_input = "CANDIDATO ALFA' OR '1'='1"

    results = duckdb_test_client.query(
        "SELECT * FROM despesas_candidatos WHERE nm_candidato = ?",
        [malicious_input],
    )

    # Não deve retornar nenhum registro pois não existe candidato com esse nome literal
    assert len(results) == 0


def test_sum_expenses_by_candidate(duckdb_test_client):
    """Critério Task 1.5: Teste unitário para soma acumulada de despesas por candidato SUM(vr_despesa_paga)."""
    # Candidato Alfa: 15000.50 + 25000.00 + 999.50 = 41000.00
    sql = """
        SELECT
            nm_candidato,
            ROUND(SUM(vr_despesa_paga), 2) AS total_gasto
        FROM despesas_candidatos
        WHERE sq_candidato = ?
        GROUP BY nm_candidato
    """
    res_alfa = duckdb_test_client.query(sql, [1001])
    assert len(res_alfa) == 1
    assert res_alfa[0]["nm_candidato"] == "CANDIDATO ALFA"
    assert res_alfa[0]["total_gasto"] == 41000.00

    # Candidata Beta: 50000.00 + 12500.25 = 62500.25
    res_beta = duckdb_test_client.query(sql, [1002])
    assert len(res_beta) == 1
    assert res_beta[0]["nm_candidato"] == "CANDIDATA BETA"
    assert res_beta[0]["total_gasto"] == 62500.25


def test_count_and_verify_nominal_votes(duckdb_test_client):
    """Critério Task 1.5: Teste unitário para contagem e verificação de votos nominais por parlamentar e proposição."""
    # 1. Verifica voto específico de um parlamentar em uma proposição
    sql_voto = """
        SELECT voto
        FROM votacoes_parlamentares
        WHERE deputado_nome = ? AND proposicao_id = ?
    """
    res_silva_pl = duckdb_test_client.query(sql_voto, ["DEPUTADO SILVA", "PL-2630"])
    assert len(res_silva_pl) == 1
    assert res_silva_pl[0]["voto"] == "Sim"

    res_souza_pec = duckdb_test_client.query(sql_voto, ["DEPUTADO SOUZA", "PEC-45"])
    assert len(res_souza_pec) == 1
    assert res_souza_pec[0]["voto"] == "Abstenção"

    # 2. Contagem agregada de votos por proposição
    sql_contagem = """
        SELECT
            voto,
            COUNT(*) AS total_votos
        FROM votacoes_parlamentares
        WHERE proposicao_id = ?
        GROUP BY voto
        ORDER BY voto
    """
    res_contagem_pl = duckdb_test_client.query(sql_contagem, ["PL-2630"])
    mapa_pl = {item["voto"]: item["total_votos"] for item in res_contagem_pl}
    assert mapa_pl["Sim"] == 2
    assert mapa_pl["Não"] == 1


def test_parquet_view_registration_and_globbing(tmp_path):
    """Critério Task 1.3: Valida leitura analítica de múltiplos Parquets via globbing e register_parquet_view."""
    # Cria dois arquivos Parquet particionados
    part1_dir = tmp_path / "data" / "ano=2026"
    part1_dir.mkdir(parents=True)
    df1 = pl.DataFrame({"ano": [2026], "valor": [100.0]})
    df1.write_parquet(part1_dir / "part1.parquet")

    part2_dir = tmp_path / "data" / "ano=2024"
    part2_dir.mkdir(parents=True)
    df2 = pl.DataFrame({"ano": [2024], "valor": [200.0]})
    df2.write_parquet(part2_dir / "part2.parquet")

    glob_pattern = str(tmp_path / "data" / "**" / "*.parquet")

    with DuckDBClient(":memory:") as client:
        # Registra a view usando o helper
        client.register_parquet_view("view_teste", glob_pattern)

        # Consulta com agregação somando os dois arquivos Parquet
        res = client.query("SELECT SUM(valor) AS total FROM view_teste")
        assert len(res) == 1
        assert res[0]["total"] == 300.0

        # Consulta filtrando uma partição específica
        res_2026 = client.query("SELECT valor FROM view_teste WHERE ano = ?", [2026])
        assert len(res_2026) == 1
        assert res_2026[0]["valor"] == 100.0


def test_query_parquet_direct_globbing(tmp_path):
    """Critério Task 1.3: Valida consulta analítica direta sobre múltiplos Parquets via query_parquet e query_parquet_df."""
    p1 = tmp_path / "part_a.parquet"
    p2 = tmp_path / "part_b.parquet"
    pl.DataFrame({"categoria": ["A", "B"], "total": [50.0, 75.0]}).write_parquet(p1)
    pl.DataFrame({"categoria": ["A", "C"], "total": [25.0, 10.0]}).write_parquet(p2)

    pattern = str(tmp_path / "*.parquet")

    with DuckDBClient(":memory:") as client:
        # Consulta direta em dicionários com filtro parametrizado
        results = client.query_parquet(
            pattern,
            sql_clause="WHERE categoria = ?",
            params=["A"],
        )
        assert len(results) == 2
        total_a = sum(r["total"] for r in results)
        assert total_a == 75.0

        # Consulta direta retornando Polars DataFrame
        df_result = client.query_parquet_df(
            pattern,
            sql_clause="WHERE categoria = 'B'",
        )
        assert isinstance(df_result, pl.DataFrame)
        assert df_result.height == 1
        assert df_result["total"][0] == 75.0


def test_register_parquet_view_with_list_of_files(tmp_path):
    """Critério Task 1.3: Valida registro de view passando uma lista explícita de caminhos de arquivos Parquet."""
    f1 = tmp_path / "file1.parquet"
    f2 = tmp_path / "file2.parquet"
    pl.DataFrame({"id": [1, 2], "score": [9.5, 8.0]}).write_parquet(f1)
    pl.DataFrame({"id": [3], "score": [7.0]}).write_parquet(f2)

    with DuckDBClient(":memory:") as client:
        client.register_parquet_view("view_lista", [str(f1), str(f2)])
        res = client.query("SELECT COUNT(*) AS total_linhas, AVG(score) AS media FROM view_lista")
        assert res[0]["total_linhas"] == 3
        assert round(res[0]["media"], 2) == 8.17


def test_register_default_views_nested_directory_structure(tmp_path):
    """Critério Task 1.3: Valida que register_default_views() descobre diretórios aninhados sem erro de múltiplos asteriscos."""
    # Cria estrutura compatível: tse/candidatos e camara/votacoes
    cand_dir = tmp_path / "tse" / "candidatos" / "ano=2026"
    cand_dir.mkdir(parents=True)
    pl.DataFrame({"NM_CANDIDATO": ["CANDIDATO 1"], "ano": [2026]}).write_parquet(cand_dir / "cand.parquet")

    vot_dir = tmp_path / "camara" / "votacoes" / "ano=2026"
    vot_dir.mkdir(parents=True)
    pl.DataFrame({"voto": ["Sim"], "ano": [2026]}).write_parquet(vot_dir / "vot.parquet")

    with DuckDBClient(":memory:") as client:
        registered = client.register_default_views(base_dir=tmp_path)

        assert "candidatos" in registered
        assert "votacoes" in registered

        # Consulta as views criadas
        res_cand = client.query("SELECT * FROM candidatos")
        assert len(res_cand) == 1
        assert res_cand[0]["NM_CANDIDATO"] == "CANDIDATO 1"

        res_vot = client.query("SELECT * FROM votacoes")
        assert len(res_vot) == 1
        assert res_vot[0]["voto"] == "Sim"


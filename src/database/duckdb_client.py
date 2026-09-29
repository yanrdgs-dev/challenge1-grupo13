"""Camada de acesso a dados analíticos e execução de queries parametrizadas via DuckDB."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import duckdb
import polars as pl

logger = logging.getLogger("Database.DuckDBClient")


class DuckDBClient:
    """Cliente gerenciador de conexões e execução analítica sobre arquivos Parquet via DuckDB.

    Atende aos critérios da Task 1.3:
    - Modo somente leitura (read-only) ativado por padrão para bancos em disco.
    - Suporte a conexões efêmeras em memória (':memory:') para testes.
    - Consultas parametrizadas para proteção estrita contra SQL Injection.
    - Métodos utilitários `query` (list[dict]) e `query_df` (pl.DataFrame).
    - Suporte robusto a globbing e registro de views sobre múltiplos arquivos Parquet.
    """

    def __init__(
        self,
        database_path: str = ":memory:",
        read_only: bool = True,
    ) -> None:
        """Inicializa o cliente DuckDB.

        Args:
            database_path: Caminho para o arquivo do banco (.duckdb) ou ':memory:' para banco efêmero.
            read_only: Se True, opera em modo somente leitura (aplicável a bancos em disco).
        """
        self.database_path = database_path
        self.is_in_memory = database_path in (":memory:", "")

        # Bancos em memória no DuckDB não aceitam flag read_only=True na inicialização
        self.read_only = False if self.is_in_memory else read_only

        self._con: Optional[duckdb.DuckDBPyConnection] = None
        self._connect()

    def _connect(self) -> None:
        """Estabelece a conexão com a engine DuckDB."""
        try:
            logger.info(
                "Conectando ao DuckDB (path='%s', read_only=%s, in_memory=%s)",
                self.database_path,
                self.read_only,
                self.is_in_memory,
            )
            self._con = duckdb.connect(
                database=self.database_path,
                read_only=self.read_only,
            )
        except Exception as err:
            logger.error("Falha ao inicializar conexão com DuckDB: %s", err, exc_info=True)
            raise

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Retorna a conexão ativa com o DuckDB."""
        if self._con is None:
            self._connect()
        return self._con

    def query(
        self,
        sql: str,
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Executa uma query analítica parametrizada e retorna o resultado como lista de dicionários.

        Args:
            sql: Comando SQL (com placeholders '?' ou nomeados '$param').
            params: Lista, tupla ou dicionário contendo os parâmetros da consulta.

        Returns:
            Lista de dicionários, onde cada item representa uma linha do resultado mapeada por coluna.
        """
        cursor = self._execute(sql, params)
        if cursor.description is None:
            return []

        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def query_df(
        self,
        sql: str,
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> pl.DataFrame:
        """Executa uma query parametrizada e retorna o resultado como um DataFrame nativo do Polars.

        Args:
            sql: Comando SQL parametrizado.
            params: Parâmetros da consulta.

        Returns:
            DataFrame do Polars com os resultados da consulta.
        """
        cursor = self._execute(sql, params)
        return cursor.pl()

    def execute(
        self,
        sql: str,
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> duckdb.DuckDBPyConnection:
        """Executa um comando SQL (DDL, views, pragmas) e retorna o cursor do DuckDB."""
        return self._execute(sql, params)

    def _execute(
        self,
        sql: str,
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> duckdb.DuckDBPyConnection:
        """Executa a consulta na conexão aplicando a parametrização de forma segura."""
        con = self.connection
        if params is not None:
            return con.execute(sql, params)
        return con.execute(sql)

    def _format_parquet_source(
        self,
        glob_pattern: Union[str, Path, List[Union[str, Path]]],
    ) -> str:
        """Formata o target de arquivos Parquet para uso na instrução read_parquet()."""
        if isinstance(glob_pattern, (list, tuple)):
            paths = [Path(p).as_posix() for p in glob_pattern]
            paths_str = ", ".join(f"'{p}'" for p in paths)
            return f"read_parquet([{paths_str}])"
        pat = Path(glob_pattern).as_posix() if isinstance(glob_pattern, Path) else str(glob_pattern)
        return f"read_parquet('{pat}')"

    def register_parquet_view(
        self,
        view_name: str,
        glob_pattern: Union[str, Path, List[Union[str, Path]]],
    ) -> None:
        """Cria ou substitui uma VIEW SQL vinculada a múltiplos arquivos Parquet via globbing.

        Args:
            view_name: Nome da VIEW SQL (ex.: 'despesas', 'votacoes').
            glob_pattern: Padrão glob dos arquivos Parquet (ex.: 'data/processed/**/*.parquet') ou lista de arquivos.
        """
        source = self._format_parquet_source(glob_pattern)
        sql = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM {source}"
        logger.info("Registrando view '%s' -> %s", view_name, source)
        self.execute(sql)

    def query_parquet(
        self,
        glob_pattern: Union[str, Path, List[Union[str, Path]]],
        sql_clause: str = "",
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Executa consulta analítica diretamente sobre arquivos Parquet via globbing sem view prévia.

        Critério Task 1.3: Leitura analítica direta de múltiplos arquivos Parquet via globbing.

        Args:
            glob_pattern: Padrão glob dos arquivos (ex.: 'data/processed/**/*.parquet') ou lista de arquivos.
            sql_clause: Cláusula SQL adicional (ex.: 'WHERE ano = ? GROUP BY ...').
            params: Parâmetros de consulta parametrizada.

        Returns:
            Lista de dicionários mapeados por coluna.
        """
        source = self._format_parquet_source(glob_pattern)
        clause = f" {sql_clause.strip()}" if sql_clause else ""
        sql = f"SELECT * FROM {source}{clause}"
        return self.query(sql, params)

    def query_parquet_df(
        self,
        glob_pattern: Union[str, Path, List[Union[str, Path]]],
        sql_clause: str = "",
        params: Optional[Union[List[Any], Tuple[Any, ...], Dict[str, Any]]] = None,
    ) -> pl.DataFrame:
        """Executa consulta analítica via globbing retornando diretamente um DataFrame Polars."""
        source = self._format_parquet_source(glob_pattern)
        clause = f" {sql_clause.strip()}" if sql_clause else ""
        sql = f"SELECT * FROM {source}{clause}"
        return self.query_df(sql, params)

    def register_default_views(
        self,
        base_dir: Union[str, Path] = "data/processed",
    ) -> Dict[str, str]:
        """Registra automaticamente as views analíticas padrão caso os diretórios Parquet existam.

        Mapeia os conjuntos de dados das fontes oficiais (TSE e Câmara):
        - `candidatos`: busca em tse/candidatos ou candidatos
        - `despesas`: busca em tse/despesas ou despesas
        - `bens`: busca em tse/bens ou bens
        - `votacoes`: busca em camara/votacoes ou votacoes
        - `ceap`: busca em camara/ceap ou ceap

        Evita erros de múltiplos '**' no DuckDB localizando diretórios reais e aplicando
        globbing estrito e compatível.

        Args:
            base_dir: Diretório base onde os arquivos Parquet processados residem.

        Returns:
            Dicionário com as views registradas e seus respectivos caminhos glob.
        """
        base_path = Path(base_dir)
        possible_dirs = {
            "candidatos": [base_path / "tse" / "candidatos", base_path / "candidatos"],
            "despesas": [base_path / "tse" / "despesas", base_path / "despesas"],
            "bens": [base_path / "tse" / "bens", base_path / "bens"],
            "votacoes": [base_path / "camara" / "votacoes", base_path / "votacoes"],
            "ceap": [base_path / "camara" / "ceap", base_path / "ceap"],
        }

        registered = {}
        for view_name, candidate_paths in possible_dirs.items():
            matched_dir = None
            for p in candidate_paths:
                if p.exists() and list(p.glob("**/*.parquet")):
                    matched_dir = p
                    break

            if matched_dir:
                # Usa padrão glob compatível com DuckDB (um único '**' por expressão)
                pattern = f"{matched_dir.as_posix()}/**/*.parquet"
                try:
                    self.register_parquet_view(view_name, pattern)
                    registered[view_name] = pattern
                except Exception as err:
                    logger.warning("Não foi possível registrar view '%s': %s", view_name, err)

        return registered

    def close(self) -> None:
        """Fecha a conexão com o banco de dados."""
        if self._con is not None:
            logger.info("Fechando conexão com DuckDB (%s)", self.database_path)
            self._con.close()
            self._con = None

    def __enter__(self) -> "DuckDBClient":
        """Suporte a gerenciador de contexto (with DuckDBClient() as client:)."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Encerra a conexão ao sair do bloco do gerenciador de contexto."""
        self.close()

"""ETL package for data ingestion, cleaning and parquet serialization."""


def __getattr__(name: str):
    if name in ("process_csv_to_parquet", "clean_currency_series", "clean_dataframe"):
        import src.etl.build_parquet as bp
        return getattr(bp, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["process_csv_to_parquet", "clean_currency_series", "clean_dataframe"]

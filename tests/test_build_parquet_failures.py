"""process_all_datasets informa as tarefas que falharam em vez de só logar."""

from src.etl import build_parquet


def test_failed_task_is_reported_through_failures_list(tmp_path, monkeypatch):
    ds = tmp_path / "datasets"
    (ds / "camara/cadastro").mkdir(parents=True)
    (ds / "camara/cadastro/deputados.csv").write_text("id;nome\n1;A\n", encoding="utf-8")

    def boom(**kwargs):
        raise ValueError("parse error")

    monkeypatch.setattr(build_parquet, "process_csv_to_parquet", boom)
    failures = []
    summaries = build_parquet.process_all_datasets(ds, tmp_path / "out", failures=failures)
    assert summaries == []
    assert [name for name, _ in failures] == ["Câmara - Deputados (Cadastro)"]
    assert isinstance(failures[0][1], ValueError)


def test_failures_argument_is_optional(tmp_path):
    assert build_parquet.process_all_datasets(tmp_path / "vazio", tmp_path / "out") == []

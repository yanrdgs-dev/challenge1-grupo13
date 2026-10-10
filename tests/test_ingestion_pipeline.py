"""Pipeline de ingestão: download (Câmara, Senado, TSE) -> build_parquet. Etapas mockadas."""

from pathlib import Path

import pytest

from src.etl import pipeline
from src.etl.download_datasets import DownloadError


@pytest.fixture
def calls(monkeypatch):
    log = []

    def fake_downloads(base_dir, client=None):
        log.append(("download_camara_senado", Path(base_dir)))
        return []

    def fake_tse(base_dir, anos, client=None):
        log.append(("download_tse", Path(base_dir), list(anos)))
        return []

    def fake_build(datasets_dir, output_base):
        log.append(("build_parquet", Path(datasets_dir), Path(output_base)))
        return [{"dataset_name": "x"}]

    monkeypatch.setattr(pipeline, "run_downloads", fake_downloads)
    monkeypatch.setattr(pipeline, "run_tse_downloads", fake_tse)
    monkeypatch.setattr(pipeline, "process_all_datasets", fake_build)
    return log


def names(calls):
    return [c[0] for c in calls]


def test_runs_downloads_then_build_in_order(calls, tmp_path):
    code = pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022])
    assert code == 0
    assert names(calls) == ["download_camara_senado", "download_tse", "build_parquet"]
    assert calls[1][2] == [2022]
    assert calls[2][1:] == (tmp_path / "ds", tmp_path / "out")


def test_aborts_before_build_when_any_download_fails(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("TSE fora do ar")])
    code = pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022])
    assert code == 1
    assert "build_parquet" not in names(calls)


def test_camara_senado_failure_also_aborts_but_tse_still_runs(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run_downloads", lambda *a, **k: [DownloadError("Câmara 500")])
    ran = []
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: ran.append(1) or [])
    code = pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022])
    assert code == 1 and ran == [1]
    assert "build_parquet" not in names(calls)


def test_allow_partial_builds_even_with_download_failures(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("x")])
    code = pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022], allow_partial=True)
    assert code == 0
    assert "build_parquet" in names(calls)


def test_skip_download_only_builds(calls, tmp_path):
    code = pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022], skip_download=True)
    assert code == 0
    assert names(calls) == ["build_parquet"]


def test_returns_nonzero_when_build_produces_nothing(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "process_all_datasets", lambda **k: [])
    assert pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022]) == 1


def test_build_exception_returns_nonzero(calls, monkeypatch, tmp_path):
    def boom(**k):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(pipeline, "process_all_datasets", boom)
    assert pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[2022]) == 1


def test_skip_tse_with_empty_years(calls, tmp_path):
    pipeline.run_pipeline(tmp_path / "ds", tmp_path / "out", anos_tse=[])
    assert "download_tse" not in names(calls)


def test_main_parses_arguments(calls, tmp_path):
    code = pipeline.main(["--datasets-dir", str(tmp_path / "d"), "--processed-dir", str(tmp_path / "p"),
                          "--tse-anos", "2022", "--skip-download"])
    assert code == 0
    assert calls[-1][1:] == (tmp_path / "d", tmp_path / "p")


def test_main_default_years_are_2022_and_2026(calls, tmp_path):
    pipeline.main(["--datasets-dir", str(tmp_path / "d"), "--processed-dir", str(tmp_path / "p")])
    assert [c for c in calls if c[0] == "download_tse"][0][2] == [2022, 2026]

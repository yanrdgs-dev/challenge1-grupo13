"""Pipeline de ingestão: download -> build (em staging) -> publicação atômica. Etapas mockadas."""

import fcntl
import json
from pathlib import Path

import pytest

from src.etl import pipeline
from src.etl.download_datasets import DownloadError
from src.etl.ingestion_state import IngestionState


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Substitui as etapas pesadas por fakes que registram as chamadas."""
    ds, out = tmp_path / "ds", tmp_path / "data" / "processed"
    ds.mkdir(parents=True)
    ctx = {"log": [], "changes": ["camara-ceap-2026"], "ds": ds, "out": out, "build_failures": [], "dim_error": None}
    ctx["download_failures"] = []

    def fake_downloads(base_dir, client=None, manifest=None, state=None, force=False, dry_run=False, changes=None):
        ctx["log"].append(("download_camara_senado", dict(force=force, dry_run=dry_run)))
        if changes is not None:
            changes.extend(ctx["changes"])
        return []

    def fake_tse(base_dir, anos, client=None, manifest=None, state=None, force=False, dry_run=False, changes=None):
        ctx["log"].append(("download_tse", list(anos), dict(force=force, dry_run=dry_run)))
        return []

    def fake_build(datasets_dir, output_base, failures=None):
        ctx["log"].append(("build_parquet", Path(output_base)))
        (Path(output_base) / "camara").mkdir(parents=True)
        (Path(output_base) / "camara" / "deputados.parquet").write_text("novo")
        failures.extend(ctx["build_failures"])
        return [{"dataset_name": "x"}]

    def fake_dim(output_path, **kwargs):
        ctx["log"].append(("dim_politicos", Path(output_path)))
        if ctx["dim_error"]:
            raise ctx["dim_error"]
        Path(output_path).write_text("dim")
        return Path(output_path)

    ctx["notified"] = []
    monkeypatch.setattr(pipeline, "notify_run", lambda run, state, env=None, **kw: ctx["notified"].append(run) or [])
    monkeypatch.setattr(pipeline, "run_downloads", fake_downloads)
    monkeypatch.setattr(pipeline, "run_tse_downloads", fake_tse)
    monkeypatch.setattr(pipeline, "process_all_datasets", fake_build)
    monkeypatch.setattr(pipeline, "build_and_save_dim_politicos", fake_dim)
    ctx["names"] = lambda: [c[0] for c in ctx["log"]]
    ctx["state"] = lambda: IngestionState.load(ds / ".ingestion_state.json")
    return ctx


def run(env, **kw):
    kw.setdefault("anos_tse", [2022])
    return pipeline.run_pipeline(env["ds"], env["out"], **kw)


def mark_as_built(env):
    env["out"].mkdir(parents=True, exist_ok=True)
    (env["out"] / "ingestion_info.json").write_text("{}")
    (env["out"] / "camara").mkdir(exist_ok=True)
    (env["out"] / "camara" / "deputados.parquet").write_text("antigo")


# ------------------------------- fluxo ------------------------------- #

def test_runs_downloads_then_build_then_dim_and_publishes(env):
    assert run(env) == 0
    assert env["names"]() == ["download_camara_senado", "download_tse", "build_parquet", "dim_politicos"]
    staging = Path(str(env["out"]) + ".staging")
    assert env["log"][2][1] == staging and env["log"][3][1] == staging / "dim_politicos.parquet"
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "novo"
    assert (env["out"] / "dim_politicos.parquet").read_text() == "dim"
    assert not staging.exists()


def test_no_news_and_already_built_skips_the_build(env):
    env["changes"] = []
    mark_as_built(env)
    assert run(env) == 0
    assert "build_parquet" not in env["names"]()
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "antigo"
    assert env["state"]().last_run["built"] is False


def test_first_run_builds_even_without_news(env):
    env["changes"] = []
    assert run(env) == 0 and "build_parquet" in env["names"]()


def test_news_trigger_build_and_clear_pending_flag(env):
    mark_as_built(env)
    assert run(env) == 0
    assert "build_parquet" in env["names"]()
    st = env["state"]()
    assert st.pending_build is False and st.last_run["built"] is True and st.last_run["downloaded"] == 1


def test_pending_build_from_a_previous_run_forces_a_build(env):
    env["changes"] = []
    mark_as_built(env)
    st = env["state"]()
    st.pending_build = True
    st.save()
    assert run(env) == 0 and "build_parquet" in env["names"]()


def test_force_build_builds_without_news(env):
    env["changes"] = []
    mark_as_built(env)
    assert run(env, force_build=True) == 0 and "build_parquet" in env["names"]()


def test_force_is_passed_to_the_downloads(env):
    run(env, force=True)
    assert env["log"][0][1]["force"] is True and env["log"][1][2]["force"] is True


def test_skip_download_only_builds(env):
    mark_as_built(env)
    assert run(env, skip_download=True) == 0
    assert env["names"]() == ["build_parquet", "dim_politicos"]


def test_skip_tse_with_empty_years(env):
    run(env, anos_tse=[])
    assert "download_tse" not in env["names"]()


# ------------------------------- falhas ------------------------------- #

def test_download_failure_aborts_before_build_but_remembers_pending_build(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("TSE fora do ar")])
    mark_as_built(env)
    assert run(env) == 1
    assert "build_parquet" not in env["names"]()
    assert env["state"]().pending_build is True and env["state"]().last_run["exit_code"] == 1


def test_allow_partial_builds_even_with_download_failures(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("x")])
    assert run(env, allow_partial=True) == 0 and "build_parquet" in env["names"]()


def test_camara_senado_failure_aborts_but_tse_still_runs(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run_downloads", lambda *a, **k: [DownloadError("Câmara 500")])
    ran = []
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: ran.append(1) or [])
    assert run(env) == 1 and ran == [1]


def test_build_task_failure_returns_nonzero_and_does_not_publish(env):
    mark_as_built(env)
    env["build_failures"] = [("TSE - Prestação de Contas", RuntimeError("parse error"))]
    assert run(env) == 1
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "antigo"
    assert not Path(str(env["out"]) + ".staging").exists()
    assert env["state"]().pending_build is True


def test_build_exception_returns_nonzero_and_keeps_published_data(env, monkeypatch):
    mark_as_built(env)

    def boom(**k):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(pipeline, "process_all_datasets", boom)
    assert run(env) == 1
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "antigo"


def test_dim_politicos_failure_does_not_publish(env):
    mark_as_built(env)
    env["dim_error"] = RuntimeError("sem deputados")
    assert run(env) == 1
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "antigo"
    assert not (env["out"] / "dim_politicos.parquet").exists()


def test_build_that_produces_nothing_is_an_error(env, monkeypatch):
    monkeypatch.setattr(pipeline, "process_all_datasets", lambda **k: [])
    assert run(env) == 1


# ------------------------------- publicação ------------------------------- #

def test_publish_replaces_top_level_dirs_and_drops_stale_datasets(env):
    mark_as_built(env)
    stale = env["out"] / "camara" / "dataset_antigo.parquet"
    stale.write_text("sobra")
    assert run(env) == 0
    assert not stale.exists()
    assert not [p for p in env["out"].parent.iterdir() if ".old" in p.name or p.name.startswith(".old")]
    assert not [p for p in env["out"].iterdir() if p.name.startswith(".old")]


def test_ingestion_info_lists_sources_and_data_date(env):
    st = env["state"]()
    st.record_file("camara-ceap-2026", url="https://x/a", dest="camara/ceap", fingerprint=None, size=1,
                   sha256="a" * 64, downloaded_at="2026-10-10T05:00:00+00:00")
    st.record_file("senado-materias-2026", url="https://x/b", dest="senado/materias", fingerprint=None, size=1,
                   sha256=None, downloaded_at="2026-10-10T06:30:00+00:00")
    st.save()
    assert run(env) == 0
    info = json.loads((env["out"] / "ingestion_info.json").read_text(encoding="utf-8"))
    assert info["dados_atualizados_em"] == "2026-10-10T06:30:00+00:00"
    assert info["fontes"]["camara-ceap-2026"]["baixado_em"] == "2026-10-10T05:00:00+00:00"
    assert info["gerado_em"]


# ------------------------------- verificação sem baixar, e lock ------------------------------- #

def test_check_only_reports_news_without_downloading_building_or_publishing(env):
    assert run(env, check_only=True) == 0
    assert env["log"][0][1]["dry_run"] is True and env["log"][1][2]["dry_run"] is True
    assert "build_parquet" not in env["names"]() and not env["out"].exists()
    assert env["state"]().last_run is None


def test_concurrent_run_is_skipped_while_the_lock_is_held(env):
    lock_path = env["ds"] / ".ingestion.lock"
    with open(lock_path, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(env) == 0
    assert env["log"] == []


def test_lock_is_released_after_the_run(env):
    run(env)
    run(env)
    assert env["names"]().count("build_parquet") >= 1 and len(env["log"]) > 4


# ------------------------------- CLI ------------------------------- #

def test_main_parses_arguments(env, tmp_path):
    code = pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]),
                          "--tse-anos", "2022", "--skip-download"])
    assert code == 0 and "build_parquet" in env["names"]()


def test_main_default_years_are_2022_and_2026(env):
    pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"])])
    assert [c for c in env["log"] if c[0] == "download_tse"][0][1] == [2022, 2026]


def test_main_flags_force_check_and_force_build(env):
    mark_as_built(env)
    pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]), "--check"])
    assert env["log"][0][1]["dry_run"] is True
    env["log"].clear()
    pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]), "--force", "--force-build"])
    assert env["log"][0][1]["force"] is True and "build_parquet" in env["names"]()


# ------------------------------- estado, status publicado e avisos ------------------------------- #

def test_run_records_news_and_failures_in_the_state(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("TSE fora do ar")])
    assert run(env) == 1
    last = env["state"]().last_run
    assert last["changes"] == ["camara-ceap-2026"] and last["failures"] == ["TSE fora do ar"] and last["exit_code"] == 1


def test_status_file_is_published_next_to_the_parquets_after_a_build(env):
    assert run(env) == 0
    status = json.loads((env["out"] / "ingestion_status.json").read_text(encoding="utf-8"))
    assert status["ultima_execucao"]["resultado"] == "ok" and status["ultima_execucao"]["build"] == "publicado"
    assert status["ultima_novidade"]["fontes"] == ["camara-ceap-2026"]


def test_status_file_is_refreshed_even_when_nothing_changed_and_the_build_is_skipped(env):
    mark_as_built(env)
    env["changes"] = []
    assert run(env) == 0
    status = json.loads((env["out"] / "ingestion_status.json").read_text(encoding="utf-8"))
    assert status["ultima_execucao"]["build"] == "ignorado" and status["ultima_execucao"]["total_novidades"] == 0


def test_status_file_also_reports_a_failed_run_without_touching_published_parquets(env):
    mark_as_built(env)
    env["build_failures"] = [("TSE", RuntimeError("parse"))]
    assert run(env) == 1
    status = json.loads((env["out"] / "ingestion_status.json").read_text(encoding="utf-8"))
    assert status["ultima_execucao"]["resultado"] == "falhou"
    assert (env["out"] / "camara" / "deputados.parquet").read_text() == "antigo"


def test_notify_is_called_once_per_real_run_with_the_run_record(env):
    run(env)
    assert len(env["notified"]) == 1 and env["notified"][0]["changes"] == ["camara-ceap-2026"]


def test_notify_is_called_on_failure_too(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run_tse_downloads", lambda *a, **k: [DownloadError("x")])
    run(env)
    assert env["notified"][0]["exit_code"] == 1


def test_notify_is_not_called_for_check_or_when_the_lock_is_held(env):
    run(env, check_only=True)
    with open(env["ds"] / ".ingestion.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(env)
    assert env["notified"] == []


def test_a_notification_error_never_changes_the_exit_code(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("webhook explodiu")

    monkeypatch.setattr(pipeline, "notify_run", boom)
    assert run(env) == 0


# ------------------------------- --status ------------------------------- #

def test_status_flag_prints_without_downloading_building_or_taking_the_lock(env, capsys):
    run(env)
    env["log"].clear()
    assert pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]), "--status"]) == 0
    out = capsys.readouterr().out
    assert "Última execução" in out and "camara-ceap-2026" in out
    assert env["log"] == []


def test_status_flag_json(env, capsys):
    run(env)
    pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]), "--status", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["ultima_execucao"]["resultado"] == "ok"


def test_status_flag_max_age_exits_2_when_stale(env, capsys):
    run(env)
    st = env["state"]()
    st.last_run["finished_at"] = "2020-01-01T00:00:00+00:00"
    st.history[-1]["finished_at"] = "2020-01-01T00:00:00+00:00"
    st.save()
    code = pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]),
                          "--status", "--max-age-hours", "6"])
    assert code == 2 and "desatualizada" in capsys.readouterr().out.lower()


def test_status_flag_max_age_ok_when_recent(env):
    run(env)
    assert pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]),
                          "--status", "--max-age-hours", "6"]) == 0


def test_status_flag_on_empty_state_says_never_ran_and_is_stale_with_max_age(env, capsys):
    assert pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]), "--status"]) == 0
    assert "nunca rodou" in capsys.readouterr().out.lower()
    assert pipeline.main(["--datasets-dir", str(env["ds"]), "--processed-dir", str(env["out"]),
                          "--status", "--max-age-hours", "6"]) == 2

"""Resumo legível do estado da ingestão: última execução, novidades, falhas e atraso."""

import json
from datetime import datetime, timedelta, timezone

from src.etl.ingestion_state import IngestionState
from src.etl.status import build_status, format_status, hours_since, is_stale, read_status_file, write_status_file

NOW = datetime(2026, 10, 10, 15, 0, 0, tzinfo=timezone.utc)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def state_with(tmp_path, runs):
    st = IngestionState.load(tmp_path / "s.json")
    for r in runs:
        st.record_run(**r)
    return st


def run(hours_ago, exit_code=0, downloaded=0, built=False, changes=None, failures=None, minutes=5):
    return dict(started_at=iso(hours_ago + minutes / 60), finished_at=iso(hours_ago), exit_code=exit_code,
                downloaded=downloaded, built=built, changes=changes or [], failures=failures or [])


# ------------------------------- build_status ------------------------------- #

def test_status_of_a_state_that_never_ran(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    s = build_status(st, NOW)
    assert s["ultima_execucao"] is None and s["ultimo_sucesso_em"] is None and s["ultima_novidade"] is None
    assert s["falhas_seguidas"] == 0 and s["historico"] == []


def test_status_last_run_ok_without_news(tmp_path):
    s = build_status(state_with(tmp_path, [run(2)]), NOW)
    u = s["ultima_execucao"]
    assert u["resultado"] == "ok" and u["build"] == "ignorado" and u["total_novidades"] == 0
    assert u["duracao_segundos"] == 300 and s["ultimo_sucesso_em"] == iso(2)


def test_status_reports_the_last_news_even_when_the_last_run_had_none(tmp_path):
    runs = [run(10, downloaded=2, built=True, changes=["camara-ceap-2026", "tse-bem_candidato_2026"]), run(3), run(1)]
    s = build_status(state_with(tmp_path, runs), NOW)
    assert s["ultima_execucao"]["total_novidades"] == 0
    assert s["ultima_novidade"] == {"em": iso(10), "total": 2, "fontes": ["camara-ceap-2026", "tse-bem_candidato_2026"]}


def test_status_failed_run_and_consecutive_failures(tmp_path):
    runs = [run(5), run(3, exit_code=1, failures=["Câmara: timeout"]), run(2, exit_code=1, failures=["Câmara: timeout"])]
    s = build_status(state_with(tmp_path, runs), NOW)
    assert s["ultima_execucao"]["resultado"] == "falhou" and s["ultima_execucao"]["build"] == "falhou"
    assert s["ultima_execucao"]["falhas"] == ["Câmara: timeout"]
    assert s["falhas_seguidas"] == 2 and s["ultimo_sucesso_em"] == iso(5)


def test_status_published_build(tmp_path):
    s = build_status(state_with(tmp_path, [run(1, downloaded=1, built=True, changes=["x"])]), NOW)
    assert s["ultima_execucao"]["build"] == "publicado"


def test_status_exposes_pending_build_data_date_sources_and_history(tmp_path):
    st = state_with(tmp_path, [run(i) for i in range(15, 0, -1)])
    st.pending_build = True
    st.record_file("a", url="u", dest="d", fingerprint=None, size=1, sha256=None, downloaded_at=iso(30))
    st.record_file("b", url="u", dest="d", fingerprint=None, size=1, sha256=None, downloaded_at=iso(8))
    s = build_status(st, NOW)
    assert s["carga_pendente"] is True and s["dados_atualizados_em"] == iso(8) and s["fontes_registradas"] == 2
    assert len(s["historico"]) == 10 and s["historico"][-1]["terminou_em"] == iso(1)


def test_status_is_json_serializable(tmp_path):
    json.dumps(build_status(state_with(tmp_path, [run(1, changes=["a"], downloaded=1)]), NOW), ensure_ascii=False)


# ------------------------------- atraso ------------------------------- #

def test_hours_since():
    assert hours_since(iso(3), NOW) == 3.0 and hours_since(None, NOW) is None


def test_is_stale_uses_the_last_success_not_the_last_attempt(tmp_path):
    s = build_status(state_with(tmp_path, [run(9), run(1, exit_code=1)]), NOW)
    assert is_stale(s, 6, NOW) is True and is_stale(s, 12, NOW) is False


def test_never_succeeded_is_stale(tmp_path):
    assert is_stale(build_status(IngestionState.load(tmp_path / "s.json"), NOW), 6, NOW) is True


# ------------------------------- texto ------------------------------- #

def test_format_status_never_ran(tmp_path):
    text = format_status(build_status(IngestionState.load(tmp_path / "s.json"), NOW), NOW)
    assert "nunca rodou" in text.lower()


def test_format_status_ok_with_news_in_portuguese(tmp_path):
    runs = [run(2, downloaded=2, built=True, changes=["camara-ceap-2026", "tse-bem_candidato_2026"])]
    text = format_status(build_status(state_with(tmp_path, runs), NOW), NOW)
    assert "Última execução" in text and "OK" in text and "há 2 h" in text
    assert "Novidades" in text and "2 fonte(s)" in text and "camara-ceap-2026" in text
    assert "publicado" in text


def test_format_status_without_news_says_none(tmp_path):
    text = format_status(build_status(state_with(tmp_path, [run(1)]), NOW), NOW)
    assert "nenhuma" in text.lower()


def test_format_status_failure_lists_the_errors_and_streak(tmp_path):
    runs = [run(2, exit_code=1, failures=["Câmara: timeout"]), run(1, exit_code=1, failures=["Câmara: timeout"])]
    text = format_status(build_status(state_with(tmp_path, runs), NOW), NOW)
    assert "FALHOU" in text and "Câmara: timeout" in text and "2 execuções seguidas" in text


def test_format_status_warns_about_pending_build(tmp_path):
    st = state_with(tmp_path, [run(1)])
    st.pending_build = True
    assert "pendente" in format_status(build_status(st, NOW), NOW).lower()


# ------------------------------- arquivo publicado ------------------------------- #

def test_status_file_roundtrip_is_atomic(tmp_path):
    s = build_status(state_with(tmp_path, [run(1)]), NOW)
    path = write_status_file(tmp_path / "processed", s)
    assert path.name == "ingestion_status.json"
    assert read_status_file(tmp_path / "processed") == s
    assert sorted(p.name for p in (tmp_path / "processed").iterdir()) == ["ingestion_status.json"]


def test_read_status_file_missing_or_corrupt_is_none(tmp_path):
    assert read_status_file(tmp_path) is None
    (tmp_path / "ingestion_status.json").write_text("{nao", encoding="utf-8")
    assert read_status_file(tmp_path) is None


def test_format_status_history_heading_agrees_in_number(tmp_path):
    one = format_status(build_status(state_with(tmp_path, [run(1)]), NOW), NOW)
    assert "Últimas 1 execuções" not in one and "Execução registrada" in one
    many = format_status(build_status(state_with(tmp_path, [run(2), run(1)]), NOW), NOW)
    assert "Últimas 2 execuções" in many

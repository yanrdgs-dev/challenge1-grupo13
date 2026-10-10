"""Estado da ingestão: o que foi baixado, quando e com qual impressão digital."""

import json

from src.etl.freshness import Fingerprint
from src.etl.ingestion_state import IngestionState

FP = Fingerprint(etag='"v1"', last_modified="Sat, 10 Oct 2026 06:00:00 GMT", content_length=10)


def test_missing_file_gives_empty_state(tmp_path):
    st = IngestionState.load(tmp_path / "state.json")
    assert st.get_file("x") is None and not st.pending_build


def test_record_and_reload_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    st = IngestionState.load(p)
    st.record_file("camara-ceap-2026", url="https://x/a", dest="camara/ceap", fingerprint=FP, size=10,
                   sha256="a" * 64, downloaded_at="2026-10-10T05:00:00+00:00")
    st.save()
    again = IngestionState.load(p)
    rec = again.get_file("camara-ceap-2026")
    assert rec["url"] == "https://x/a" and rec["size"] == 10 and rec["sha256"] == "a" * 64
    assert Fingerprint.from_dict(rec["fingerprint"]) == FP
    assert rec["downloaded_at"] == "2026-10-10T05:00:00+00:00"


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "state.json"
    st = IngestionState.load(p)
    st.record_file("a", url="u", dest="d", fingerprint=None, size=1, sha256=None, downloaded_at="t")
    st.save()
    assert sorted(x.name for x in tmp_path.iterdir()) == ["state.json"]
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == 1


def test_corrupt_state_file_is_set_aside_and_state_starts_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{nao é json", encoding="utf-8")
    st = IngestionState.load(p)
    assert st.get_file("x") is None
    assert (tmp_path / "state.json.corrupt").exists()


def test_adopted_record_has_no_download_date(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    st.record_file("a", url="u", dest="d", fingerprint=FP, size=None, sha256=None, downloaded_at=None, adopted=True)
    rec = st.get_file("a")
    assert rec["adopted"] is True and rec["downloaded_at"] is None


def test_pending_build_flag_survives_reload(tmp_path):
    p = tmp_path / "s.json"
    st = IngestionState.load(p)
    st.pending_build = True
    st.save()
    assert IngestionState.load(p).pending_build is True


def test_last_run_is_recorded_with_news_and_failures(tmp_path):
    p = tmp_path / "s.json"
    st = IngestionState.load(p)
    st.record_run(started_at="a", finished_at="b", exit_code=0, downloaded=3, built=True,
                  changes=["camara-ceap-2026", "tse-bem_candidato_2026"], failures=[])
    st.save()
    assert IngestionState.load(p).last_run == {
        "started_at": "a", "finished_at": "b", "exit_code": 0, "downloaded": 3, "built": True,
        "changes": ["camara-ceap-2026", "tse-bem_candidato_2026"], "failures": [],
        "changes_by_origin": {"camara": 1, "tse": 1}}


def test_record_run_without_details_defaults_to_empty_lists(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    st.record_run("a", "b", 0, 0, False)
    assert st.last_run["changes"] == [] and st.last_run["failures"] == []


def test_history_keeps_the_runs_in_order_and_is_capped(tmp_path):
    p = tmp_path / "s.json"
    st = IngestionState.load(p)
    for i in range(60):
        st.record_run(f"s{i}", f"f{i}", 0, 0, False)
    st.save()
    h = IngestionState.load(p).history
    assert len(h) == 50 and h[0]["started_at"] == "s10" and h[-1]["started_at"] == "s59"


def test_long_change_and_failure_lists_are_truncated_but_counted(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    st.record_run("a", "b", 1, 100, False, changes=[f"fonte-{i}" for i in range(100)],
                  failures=[f"erro {i}" for i in range(20)])
    assert len(st.last_run["changes"]) == 30 and st.last_run["downloaded"] == 100
    assert len(st.last_run["failures"]) == 5


def test_notification_memory_survives_reload(tmp_path):
    p = tmp_path / "s.json"
    st = IngestionState.load(p)
    st.notify = {"last_failure_signature": "x", "last_failure_notified_at": "2026-10-10T10:00:00+00:00"}
    st.save()
    assert IngestionState.load(p).notify["last_failure_signature"] == "x"


def test_run_counts_news_by_origin_before_truncating_the_id_list(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    changes = [f"camara-ceap-{i}" for i in range(26)] + [f"senado-ceaps-{i}" for i in range(11)] + [
        f"tse-consulta_cand_{i}" for i in range(45)]
    st.record_run("a", "b", 0, len(changes), True, changes=changes)
    run = st.last_run
    assert len(run["changes"]) == 30 and run["downloaded"] == 82
    assert run["changes_by_origin"] == {"camara": 26, "senado": 11, "tse": 45}


def test_run_without_news_has_empty_origin_counts(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    st.record_run("a", "b", 0, 0, False)
    assert st.last_run["changes_by_origin"] == {}

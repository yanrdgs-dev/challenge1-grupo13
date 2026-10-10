"""run_downloads e run_tse_downloads com estado: só baixam o que tem novidade. Rede mockada."""

import io
import zipfile

import httpx

from src.etl.download_datasets import run_downloads
from src.etl.ingestion_state import IngestionState
from src.etl.tse_ckan import run_tse_downloads
from tests.test_tse_ckan import make_handler

BODY = b"a;b\n" + b"1;2\n" * 400
OLD = "Mon, 05 Oct 2026 06:00:00 GMT"


def zip_of(name, content=BODY):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


MANIFEST = {
    "version": 1,
    "sources": [
        {"id": "a", "kind": "file", "url": "https://dados.example.gov.br/a.csv", "dest": "x/a.csv", "desc": "A"},
        {"id": "z", "kind": "zip_csv", "anos": [2030], "url": "https://dados.example.gov.br/z-{ano}.zip",
         "dest": "x/z", "prefix": "z-{ano}", "desc": "Z {ano}"},
        {"id": "d", "kind": "file", "refresh": "always", "url": "https://dados.example.gov.br/d.csv",
         "dest": "x/d.csv", "desc": "D"},
    ],
    "tse": {"packages": {}, "rules": [], "pending_ok": {}},
}


class Remote:
    def __init__(self):
        self.etags = {"a": '"a1"', "z": '"z1"'}
        self.requests = []
        self.zip_content = zip_of("z-2030.csv")  # fixo: o zip embute a hora de criação, que mudaria os bytes

    def handler(self, request):
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        key = "a" if path.endswith("a.csv") else "z" if path.endswith(".zip") else "d"
        headers = {"Last-Modified": OLD}
        if key in self.etags:
            headers["ETag"] = self.etags[key]
        content = self.zip_content if key == "z" else BODY
        return httpx.Response(200, content=content, headers=headers)

    def gets(self):
        return [p for m, p in self.requests if m == "GET"]

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def go(remote, tmp_path, state, **kw):
    changes = []
    with remote.client() as client:
        failures = run_downloads(tmp_path, client=client, manifest=MANIFEST, state=state, changes=changes, **kw)
    return failures, changes


def test_first_run_downloads_everything_and_reports_changes(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    failures, changes = go(remote, tmp_path, st)
    assert failures == [] and sorted(changes) == ["a", "d", "z-2030"]
    assert (tmp_path / "x/a.csv").exists() and (tmp_path / "x/z/z-2030.csv").exists()
    assert st.get_file("a")["sha256"] and st.get_file("z-2030")["fingerprint"]["etag"] == '"z1"'


def test_second_run_rechecks_the_always_source_but_reports_no_news(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    go(remote, tmp_path, st)
    remote.requests.clear()
    failures, changes = go(remote, tmp_path, st)
    assert failures == [] and changes == []  # conteúdo idêntico: não dispara rebuild
    assert remote.gets() == ["/d.csv"]


def test_only_the_source_with_new_etag_is_downloaded(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    go(remote, tmp_path, st)
    remote.etags["z"] = '"z2"'
    remote.requests.clear()
    _, changes = go(remote, tmp_path, st)
    assert sorted(remote.gets()) == ["/d.csv", "/z-2030.zip"]
    assert changes == []  # a nova versão do zip tem os mesmos bytes: sem novidade de conteúdo


def test_dry_run_lists_news_without_downloading_or_recording(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    failures, changes = go(remote, tmp_path, st, dry_run=True)
    assert failures == [] and sorted(changes) == ["a", "d", "z-2030"]
    assert remote.gets() == [] and not (tmp_path / "x").exists() and st.get_file("a") is None


def test_force_redownloads_everything_but_only_reports_content_changes(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    go(remote, tmp_path, st)
    remote.requests.clear()
    _, changes = go(remote, tmp_path, st, force=True)
    assert sorted(remote.gets()) == ["/a.csv", "/d.csv", "/z-2030.zip"] and changes == []


def test_failure_in_one_source_is_reported_and_others_still_sync(tmp_path):
    remote, st = Remote(), IngestionState.load(tmp_path / "s.json")
    original = remote.handler

    def flaky(request):
        return httpx.Response(404) if request.url.path.endswith("a.csv") else original(request)

    remote.handler = flaky
    failures, changes = go(remote, tmp_path, st)
    assert len(failures) == 1 and "404" in str(failures[0])
    assert sorted(changes) == ["d", "z-2030"] and st.get_file("a") is None


# ------------------------------- TSE ------------------------------- #

def test_tse_second_run_downloads_nothing(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    hits = []
    with httpx.Client(transport=httpx.MockTransport(make_handler(hits=hits))) as client:
        changes = []
        failures = run_tse_downloads(tmp_path, [2022], client=client, state=st, changes=changes)
    assert failures == [] and len(changes) > 10
    assert st.get_file("tse-consulta_cand_2022") is not None
    cdn_gets_before = len(hits)
    with httpx.Client(transport=httpx.MockTransport(make_handler(hits=hits))) as client:
        changes = []
        failures = run_tse_downloads(tmp_path, [2022], client=client, state=st, changes=changes)
    assert failures == [] and changes == []
    assert len(hits) > cdn_gets_before  # consultou o CKAN e fez HEAD, mas não baixou os zips de novo


def test_tse_dry_run_reports_without_downloading(tmp_path):
    st = IngestionState.load(tmp_path / "s.json")
    changes = []
    with httpx.Client(transport=httpx.MockTransport(make_handler())) as client:
        failures = run_tse_downloads(tmp_path, [2022], client=client, state=st, changes=changes, dry_run=True)
    assert failures == [] and len(changes) > 10
    assert not (tmp_path / "tse").exists()

"""Sincronização de uma fonte: decide se há novidade, baixa e registra o estado. Rede mockada."""

import hashlib

import httpx

from src.etl.download_datasets import download_file
from src.etl.ingestion_state import IngestionState
from src.etl.sync import sync_item

URL = "https://dados.example.gov.br/a.csv"
BODY = b"a;b\n" + b"1;2\n" * 400


class Server:
    """Servidor de mentira: versão atual do arquivo, validadores e contagem de requisições."""

    def __init__(self, etag='"v1"', lm="Mon, 05 Oct 2026 06:00:00 GMT", body=BODY, validators=True):
        self.etag, self.lm, self.body, self.validators = etag, lm, body, validators
        self.heads = self.gets = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        headers = {"ETag": self.etag, "Last-Modified": self.lm} if self.validators else {}
        if request.method == "HEAD":
            self.heads += 1
            return httpx.Response(200, headers={**headers, "Content-Length": str(len(self.body))})
        self.gets += 1
        return httpx.Response(200, content=self.body, headers=headers)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def run(server, tmp_path, state, refresh="validators", force=False, dry_run=False, item_id="a"):
    dest = tmp_path / "a.csv"
    with server.client() as client:
        return sync_item(
            item_id, URL, refresh=refresh, state=state, client=client,
            local_exists=dest.exists(), local_mtime=dest.stat().st_mtime if dest.exists() else None,
            local_size=dest.stat().st_size if dest.exists() else None,
            download=lambda force_: download_file(URL, dest, "teste", client=client, force=force_),
            force=force, dry_run=dry_run,
        )


def new_state(tmp_path):
    return IngestionState.load(tmp_path / "state.json")


def test_first_run_downloads_and_records_state(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    out = run(srv, tmp_path, st)
    assert out.action == "baixado" and (tmp_path / "a.csv").read_bytes() == BODY
    rec = st.get_file("a")
    assert rec["sha256"] == hashlib.sha256(BODY).hexdigest() and rec["size"] == len(BODY)
    assert rec["fingerprint"]["etag"] == '"v1"' and rec["downloaded_at"]
    assert IngestionState.load(tmp_path / "state.json").get_file("a") is not None  # salvo em disco


def test_second_run_without_news_does_not_download_again(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    run(srv, tmp_path, st)
    srv.gets = 0
    out = run(srv, tmp_path, st)
    assert out.action == "sem_novidade" and srv.gets == 0 and srv.heads >= 1


def test_new_etag_triggers_redownload_with_new_content(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    run(srv, tmp_path, st)
    srv.etag, srv.body = '"v2"', b"x;y\n" + b"3;4\n" * 500
    out = run(srv, tmp_path, st)
    assert out.action == "baixado" and (tmp_path / "a.csv").read_bytes() == srv.body
    assert st.get_file("a")["fingerprint"]["etag"] == '"v2"'


def test_refresh_always_downloads_every_time(tmp_path):
    srv, st = Server(validators=False), new_state(tmp_path)
    run(srv, tmp_path, st, refresh="always")
    run(srv, tmp_path, st, refresh="always")
    assert srv.gets == 2


def test_dry_run_reports_news_without_downloading_or_touching_state(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    out = run(srv, tmp_path, st, dry_run=True)
    assert out.action == "seria_baixado" and srv.gets == 0
    assert not (tmp_path / "a.csv").exists() and st.get_file("a") is None


def test_dry_run_without_news_says_so(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    run(srv, tmp_path, st)
    assert run(srv, tmp_path, st, dry_run=True).action == "sem_novidade"


def test_force_downloads_even_without_news(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    run(srv, tmp_path, st)
    srv.gets = 0
    assert run(srv, tmp_path, st, force=True).action == "baixado" and srv.gets == 1


def test_existing_file_without_state_is_adopted_when_remote_is_not_newer(tmp_path):
    (tmp_path / "a.csv").write_bytes(BODY)  # baixado antes de existir o estado; mtime = agora (> Last-Modified)
    srv, st = Server(), new_state(tmp_path)
    out = run(srv, tmp_path, st)
    assert out.action == "sem_novidade" and srv.gets == 0
    rec = st.get_file("a")
    assert rec["adopted"] is True and rec["fingerprint"]["etag"] == '"v1"'


def test_existing_file_older_than_remote_is_redownloaded(tmp_path):
    import os

    f = tmp_path / "a.csv"
    f.write_bytes(b"velho" * 400)
    os.utime(f, (1_790_000_000, 1_790_000_000))  # 2026-09-21
    srv, st = Server(), new_state(tmp_path)
    assert run(srv, tmp_path, st).action == "baixado" and f.read_bytes() == BODY


def test_failed_download_does_not_record_state_and_propagates(tmp_path):
    import pytest

    from src.etl.download_datasets import DownloadError

    def handler(request):
        return httpx.Response(200, headers={"ETag": '"v1"'}) if request.method == "HEAD" else httpx.Response(404)

    st = new_state(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(DownloadError):
        sync_item("a", URL, refresh="validators", state=st, client=client, local_exists=False, local_mtime=None,
                  local_size=None, download=lambda f: download_file(URL, tmp_path / "a.csv", "t", client=client))
    assert st.get_file("a") is None


def test_refresh_always_with_identical_content_is_not_a_news_item(tmp_path):
    srv, st = Server(validators=False), new_state(tmp_path)
    first = run(srv, tmp_path, st, refresh="always")
    assert first.action == "baixado"
    downloaded_at = st.get_file("a")["downloaded_at"]
    second = run(srv, tmp_path, st, refresh="always")
    assert srv.gets == 2  # baixou para comparar
    assert second.action == "sem_novidade" and "idêntico" in second.reason
    assert st.get_file("a")["downloaded_at"] == downloaded_at  # a data do dado não muda


def test_refresh_always_with_changed_content_is_a_news_item(tmp_path):
    srv, st = Server(validators=False), new_state(tmp_path)
    run(srv, tmp_path, st, refresh="always")
    srv.body = b"x;y\n" + b"9;9\n" * 500
    out = run(srv, tmp_path, st, refresh="always")
    assert out.action == "baixado" and (tmp_path / "a.csv").read_bytes() == srv.body
    assert st.get_file("a")["sha256"] == hashlib.sha256(srv.body).hexdigest()


def test_republished_file_with_same_bytes_is_not_a_news_item(tmp_path):
    srv, st = Server(), new_state(tmp_path)
    run(srv, tmp_path, st)
    srv.etag = '"v2"'  # o portal republicou, mas o conteúdo é o mesmo
    out = run(srv, tmp_path, st)
    assert out.action == "sem_novidade" and "idêntico" in out.reason
    assert st.get_file("a")["fingerprint"]["etag"] == '"v2"'  # a impressão digital nova é registrada

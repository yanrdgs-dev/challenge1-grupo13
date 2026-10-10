"""Download dos datasets públicos: rede sempre mockada (httpx.MockTransport), nada baixa de verdade."""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.etl import download_datasets
from src.etl.download_datasets import (
    DownloadError,
    download_file,
    download_zip_csv,
    make_client,
    run_downloads,
)

URL = "https://dadosabertos.example.gov.br/arquivo.csv"
BODY = b"a;b\n" + b"1;2\n" * 400  # > 1000 bytes


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=BODY)


def make_zip(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


# ------------------------------- caminho feliz ------------------------------- #

def test_download_file_writes_content_to_destination(tmp_path):
    dest = tmp_path / "sub" / "arquivo.csv"
    with client_for(ok_handler) as client:
        download_file(URL, dest, "teste", client=client)
    assert dest.read_bytes() == BODY
    assert not list(dest.parent.glob("*.part"))


def test_download_file_skips_when_valid_file_already_exists(tmp_path):
    dest = tmp_path / "arquivo.csv"
    dest.write_bytes(BODY)

    def handler(request):
        raise AssertionError("não devia haver requisição")

    with client_for(handler) as client:
        download_file(URL, dest, "teste", client=client)
    assert dest.read_bytes() == BODY


def test_download_file_content_length_matching_is_accepted(tmp_path):
    def handler(request):
        return httpx.Response(200, content=BODY, headers={"Content-Length": str(len(BODY))})

    dest = tmp_path / "a.csv"
    with client_for(handler) as client:
        download_file(URL, dest, "teste", client=client)
    assert dest.read_bytes() == BODY


# ------------------------------- download parcial / Content-Length ------------------------------- #

def test_content_length_mismatch_is_explicit_error(tmp_path):
    def handler(request):
        return httpx.Response(200, content=BODY[:100], headers={"Content-Length": str(len(BODY))})

    dest = tmp_path / "a.csv"
    with client_for(handler) as client, pytest.raises(DownloadError, match="Content-Length"):
        download_file(URL, dest, "teste", client=client)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_partial_download_does_not_overwrite_previous_good_file(tmp_path):
    dest = tmp_path / "a.csv"
    dest.write_bytes(b"x")  # pequeno demais para ser considerado válido, será substituído

    def handler(request):
        return httpx.Response(200, content=BODY[:100], headers={"Content-Length": str(len(BODY))})

    with client_for(handler) as client, pytest.raises(DownloadError):
        download_file(URL, dest, "teste", client=client)
    assert dest.read_bytes() == b"x"


def test_connection_dropped_midstream_is_explicit_error_and_leaves_no_corrupt_file(tmp_path):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield BODY[:200]
            raise httpx.ReadError("conexão encerrada no meio")

    def handler(request):
        return httpx.Response(200, stream=BrokenStream())

    dest = tmp_path / "a.csv"
    with client_for(handler) as client, pytest.raises(DownloadError):
        download_file(URL, dest, "teste", client=client)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


# ------------------------------- escrita atômica ------------------------------- #

def test_writes_to_temp_file_then_renames(tmp_path):
    dest = tmp_path / "a.csv"
    seen = {}
    real_replace = download_datasets.os.replace

    def spy_replace(src, dst):
        seen["src"] = Path(src)
        seen["src_content"] = Path(src).read_bytes()
        seen["dst_existed"] = Path(dst).exists()
        return real_replace(src, dst)

    with client_for(ok_handler) as client, patch.object(download_datasets.os, "replace", spy_replace):
        download_file(URL, dest, "teste", client=client)
    assert seen["src"] != dest and seen["src"].suffix == ".part"
    assert seen["src_content"] == BODY
    assert seen["dst_existed"] is False
    assert dest.read_bytes() == BODY


# ------------------------------- timeout / erro de rede / HTTP ------------------------------- #

@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("timeout"), httpx.ReadTimeout("timeout")])
def test_timeout_is_explicit_error(tmp_path, exc):
    def handler(request):
        raise exc

    dest = tmp_path / "a.csv"
    with client_for(handler) as client, pytest.raises(DownloadError, match="teste"):
        download_file(URL, dest, "teste", client=client)
    assert not dest.exists()


def test_network_error_is_explicit_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("sem rota")

    with client_for(handler) as client, pytest.raises(DownloadError):
        download_file(URL, tmp_path / "a.csv", "teste", client=client)


@pytest.mark.parametrize("status", [404, 500, 503])
def test_http_error_status_is_explicit_error(tmp_path, status):
    def handler(request):
        return httpx.Response(status, content=b"erro")

    dest = tmp_path / "a.csv"
    with client_for(handler) as client, pytest.raises(DownloadError, match=str(status)):
        download_file(URL, dest, "teste", client=client)
    assert not dest.exists()


# ------------------------------- SSL ------------------------------- #

def test_make_client_keeps_ssl_verification_on():
    with patch.object(download_datasets.httpx, "Client") as mock_client:
        make_client()
    kwargs = mock_client.call_args.kwargs
    assert kwargs.get("verify", True) is not False
    assert kwargs.get("timeout") is not None


def test_make_client_builds_a_real_client_with_valid_headers():
    # sem mock do httpx.Client: cabeçalhos não-ASCII fazem o construtor falhar
    with make_client() as client:
        assert client.headers["User-Agent"].isascii()


def test_module_never_disables_ssl():
    source = Path(download_datasets.__file__).read_text(encoding="utf-8")
    assert "CERT_NONE" not in source
    assert "check_hostname" not in source
    assert "verify=False" not in source.replace(" ", "")


# ------------------------------- zip ------------------------------- #

def test_download_zip_csv_extracts_and_removes_zip(tmp_path):
    payload = make_zip("Ano-2024.csv", BODY)

    def handler(request):
        return httpx.Response(200, content=payload)

    with client_for(handler) as client:
        download_zip_csv(URL, tmp_path, "Ano-2024", "CEAP 2024", client=client)
    assert (tmp_path / "Ano-2024.csv").read_bytes() == BODY
    assert not list(tmp_path.glob("*.zip")) and not list(tmp_path.glob("*.part"))


def test_download_zip_csv_skips_when_csv_already_extracted(tmp_path):
    (tmp_path / "Ano-2024.csv").write_bytes(BODY)

    def handler(request):
        raise AssertionError("não devia haver requisição")

    with client_for(handler) as client:
        download_zip_csv(URL, tmp_path, "Ano-2024", "CEAP 2024", client=client)


def test_download_zip_csv_corrupt_zip_is_explicit_error(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"isto nao e um zip" * 100)

    with client_for(handler) as client, pytest.raises(DownloadError, match="zip"):
        download_zip_csv(URL, tmp_path, "Ano-2024", "CEAP 2024", client=client)
    assert not list(tmp_path.glob("*"))


def test_download_zip_csv_truncated_zip_is_explicit_error(tmp_path):
    payload = make_zip("Ano-2024.csv", BODY)

    def handler(request):
        return httpx.Response(200, content=payload[:50], headers={"Content-Length": str(len(payload))})

    with client_for(handler) as client, pytest.raises(DownloadError):
        download_zip_csv(URL, tmp_path, "Ano-2024", "CEAP 2024", client=client)
    assert not list(tmp_path.glob("*"))


def test_download_zip_csv_rejects_path_traversal(tmp_path):
    out = tmp_path / "out"
    payload = make_zip("../evil.csv", BODY)

    def handler(request):
        return httpx.Response(200, content=payload)

    with client_for(handler) as client, pytest.raises(DownloadError):
        download_zip_csv(URL, out, "Ano-2024", "CEAP 2024", client=client)
    assert not (tmp_path / "evil.csv").exists()


# ------------------------------- orquestração ------------------------------- #

def test_run_downloads_reports_failures_instead_of_claiming_success(tmp_path):
    def handler(request):
        if "camara.leg.br/cotas" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=BODY)

    with client_for(handler) as client:
        failures = run_downloads(tmp_path, client=client)
    assert failures, "falhas precisam ser reportadas"
    assert all(isinstance(f, DownloadError) for f in failures)
    # os demais continuam sendo baixados
    assert (tmp_path / "senado" / "cadastro" / "senadores.csv").exists()


def test_main_returns_nonzero_when_any_download_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(download_datasets, "run_downloads", lambda base_dir, client=None: [DownloadError("x")])
    assert download_datasets.main(["--base-dir", str(tmp_path)]) == 1


def test_main_returns_zero_when_all_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr(download_datasets, "run_downloads", lambda base_dir, client=None: [])
    assert download_datasets.main(["--base-dir", str(tmp_path)]) == 0


# ------------------------------- erro de disco ------------------------------- #

def test_disk_error_while_writing_is_explicit_error_and_leaves_no_file(tmp_path):
    dest = tmp_path / "a.csv"

    def full_disk(*args, **kwargs):
        raise OSError(122, "Disk quota exceeded")

    with client_for(ok_handler) as client, patch.object(download_datasets.os, "replace", full_disk):
        with pytest.raises(DownloadError, match="Disk quota"):
            download_file(URL, dest, "teste", client=client)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))


def test_disk_error_while_extracting_is_explicit_error_and_cleans_partial_files(tmp_path):
    payload = make_zip("Ano-2024.csv", BODY)

    class FullDiskZip(zipfile.ZipFile):
        def extract(self, member, path=None, pwd=None):
            target = Path(path) / member.filename
            target.write_bytes(b"parcial")
            raise OSError(122, "Disk quota exceeded")

    def handler(request):
        return httpx.Response(200, content=payload)

    with client_for(handler) as client, patch.object(download_datasets.zipfile, "ZipFile", FullDiskZip):
        with pytest.raises(DownloadError, match="Disk quota"):
            download_zip_csv(URL, tmp_path, "Ano-2024", "CEAP 2024", client=client)
    assert not list(tmp_path.glob("*"))


# ------------------------------- checksum e manifesto ------------------------------- #

def test_download_with_matching_sha256_is_accepted(tmp_path):
    import hashlib

    dest = tmp_path / "a.csv"
    with client_for(ok_handler) as client:
        download_file(URL, dest, "teste", client=client, expected_sha256=hashlib.sha256(BODY).hexdigest())
    assert dest.read_bytes() == BODY


def test_download_with_wrong_sha256_is_explicit_error_and_leaves_no_file(tmp_path):
    dest = tmp_path / "a.csv"
    with client_for(ok_handler) as client, pytest.raises(DownloadError, match="sha256"):
        download_file(URL, dest, "teste", client=client, expected_sha256="0" * 64)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def test_run_downloads_follows_the_manifest_not_hardcoded_urls(tmp_path):
    manifest = {
        "version": 1,
        "sources": [
            {"id": "a", "kind": "file", "url": "https://dados.example.gov.br/a.csv", "dest": "x/a.csv", "desc": "A"},
            {"id": "z", "kind": "zip_csv", "anos": [2030], "url": "https://dados.example.gov.br/z-{ano}.zip",
             "dest": "x/z", "prefix": "z-{ano}", "desc": "Z {ano}"},
        ],
        "tse": {"packages": {}, "rules": [], "pending_ok": {}},
    }
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if str(request.url).endswith(".zip"):
            return httpx.Response(200, content=make_zip("z-2030.csv", BODY))
        return httpx.Response(200, content=BODY)

    with client_for(handler) as client:
        failures = run_downloads(tmp_path, client=client, manifest=manifest)
    assert failures == []
    assert seen == ["https://dados.example.gov.br/a.csv", "https://dados.example.gov.br/z-2030.zip"]
    assert (tmp_path / "x/a.csv").read_bytes() == BODY and (tmp_path / "x/z/z-2030.csv").exists()


def test_run_downloads_verifies_manifest_sha256(tmp_path):
    manifest = {
        "version": 1,
        "sources": [{"id": "a", "kind": "file", "url": "https://dados.example.gov.br/a.csv",
                     "dest": "x/a.csv", "desc": "A", "sha256": "f" * 64}],
        "tse": {"packages": {}, "rules": [], "pending_ok": {}},
    }
    with client_for(ok_handler) as client:
        failures = run_downloads(tmp_path, client=client, manifest=manifest)
    assert len(failures) == 1 and "sha256" in str(failures[0])
    assert not (tmp_path / "x/a.csv").exists()

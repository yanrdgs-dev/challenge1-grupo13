"""Detecção de novidades: impressão digital HTTP (ETag, Last-Modified, tamanho) e decisão de baixar ou não."""

import httpx

from src.etl.freshness import Fingerprint, decide, head_fingerprint

OLD = "Fri, 09 Oct 2026 06:00:00 GMT"
NEW = "Sat, 10 Oct 2026 06:00:00 GMT"


def fp(etag=None, lm=None, size=None):
    return Fingerprint(etag=etag, last_modified=lm, content_length=size)


def d(**kw):
    base = dict(refresh="validators", local_exists=True, local_mtime=None, local_size=None,
                prior=None, remote=None, force=False)
    base.update(kw)
    return decide(**base)


# ------------------------------- Fingerprint / HEAD ------------------------------- #

def test_fingerprint_roundtrip():
    f = fp('"abc"', OLD, 10)
    assert Fingerprint.from_dict(f.to_dict()) == f
    assert Fingerprint.from_dict(None) is None


def test_head_fingerprint_reads_validators():
    def handler(request):
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"ETag": '"v1"', "Last-Modified": OLD, "Content-Length": "123"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert head_fingerprint("https://x.gov.br/a", c) == fp('"v1"', OLD, 123)


def test_head_fingerprint_is_none_on_error_status_or_network_failure():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(405))) as c:
        assert head_fingerprint("https://x.gov.br/a", c) is None

    def boom(request):
        raise httpx.ConnectTimeout("lento")

    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        assert head_fingerprint("https://x.gov.br/a", c) is None


# ------------------------------- decide ------------------------------- #

def test_force_always_downloads():
    assert d(force=True, prior=fp('"a"'), remote=fp('"a"')).download


def test_missing_local_file_downloads():
    r = d(local_exists=False)
    assert r.download and "ausente" in r.reason


def test_refresh_always_downloads_even_when_nothing_changed():
    r = d(refresh="always", prior=fp(size=10), remote=fp(size=10))
    assert r.download and "always" in r.reason


def test_head_failed_keeps_local_copy():
    r = d(remote=None)
    assert not r.download and not r.adopt


def test_same_etag_means_no_news():
    r = d(prior=fp('"v1"', OLD, 10), remote=fp('"v1"', OLD, 10))
    assert not r.download


def test_different_etag_downloads():
    r = d(prior=fp('"v1"', OLD, 10), remote=fp('"v2"', OLD, 10))
    assert r.download and "ETag" in r.reason


def test_different_last_modified_downloads_when_there_is_no_etag():
    r = d(prior=fp(None, OLD, 10), remote=fp(None, NEW, 10))
    assert r.download and "Last-Modified" in r.reason


def test_weak_etag_prefix_is_compared_as_is():
    assert not d(prior=fp('W/"1"', OLD), remote=fp('W/"1"', OLD)).download
    assert d(prior=fp('W/"1"', OLD), remote=fp('W/"2"', OLD)).download


def test_without_prior_state_remote_newer_than_local_file_downloads():
    r = d(prior=None, remote=fp('"v1"', NEW, 10), local_mtime=1_790_900_000.0)  # 02/10
    assert r.download and "mais novo" in r.reason


def test_without_prior_state_local_file_newer_than_remote_is_adopted_as_baseline():
    r = d(prior=None, remote=fp('"v1"', OLD, 10), local_mtime=1_791_600_000.0)  # 10/10 02:40, depois do Last-Modified de 09/10
    assert not r.download and r.adopt


def test_without_validators_size_change_downloads():
    assert d(prior=fp(size=10), remote=fp(size=11)).download
    assert d(prior=None, remote=fp(size=11), local_size=10).download


def test_without_validators_same_size_is_no_news():
    r = d(prior=fp(size=10), remote=fp(size=10))
    assert not r.download
    r = d(prior=None, remote=fp(size=10), local_size=10)
    assert not r.download and r.adopt


def test_remote_without_any_information_keeps_local_copy():
    r = d(prior=fp('"v1"', OLD, 10), remote=fp())
    assert not r.download


# ------------------------------- timeout curto e disjuntor por host ------------------------------- #

def test_head_uses_a_short_timeout():
    seen = {}

    def handler(request):
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(30.0, read=180.0)) as c:
        head_fingerprint("https://x.gov.br/a", c)
    assert seen["timeout"]["read"] <= 20


def failing_client(counter):
    def handler(request):
        counter.append(request.url.host)
        raise httpx.ReadTimeout("sem resposta")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_breaker_skips_a_host_after_two_consecutive_failures():
    from src.etl.freshness import HostBreaker

    hits, breaker = [], HostBreaker(max_failures=2)
    with failing_client(hits) as c:
        results = [head_fingerprint(f"https://lento.gov.br/{i}", c, breaker) for i in range(5)]
    assert results == [None] * 5
    assert hits == ["lento.gov.br", "lento.gov.br"]  # as três últimas nem foram tentadas


def test_breaker_is_per_host_and_resets_on_success():
    from src.etl.freshness import HostBreaker

    state = {"fail": True}

    def handler(request):
        if request.url.host == "bom.gov.br" or not state["fail"]:
            return httpx.Response(200, headers={"ETag": '"x"'})
        raise httpx.ReadTimeout("sem resposta")

    breaker = HostBreaker(max_failures=2)
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert head_fingerprint("https://lento.gov.br/1", c, breaker) is None
        state["fail"] = False
        assert head_fingerprint("https://lento.gov.br/2", c, breaker) is not None  # sucesso zera a contagem
        state["fail"] = True
        assert head_fingerprint("https://lento.gov.br/3", c, breaker) is None
        assert head_fingerprint("https://bom.gov.br/1", c, breaker) is not None  # outro host não é afetado


def test_head_connect_timeout_is_short_because_httpx_retries_each_resolved_address():
    seen = {}

    def handler(request):
        seen["t"] = request.extensions["timeout"]
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        head_fingerprint("https://x.gov.br/a", c)
    assert seen["t"]["connect"] <= 5

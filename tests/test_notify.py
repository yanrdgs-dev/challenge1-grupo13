"""Avisos da ingestão: webhook (Discord, Slack, ntfy ou JSON genérico) e heartbeat externo. Rede mockada."""

import json

import httpx

from src.etl.ingestion_state import IngestionState
from src.etl.notify import NotifyConfig, format_message, notify_run, ping_heartbeat, send_webhook

DISCORD = "https://discord.com/api/webhooks/123/abc"
SLACK = "https://hooks.slack.com/services/T/B/x"
NTFY = "https://ntfy.sh/polis-ingestao"
HB = "https://hc-ping.com/uuid-aqui"


class Recorder:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url), request.headers, request.content))
        return httpx.Response(self.status)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def run_ok(changes=(), built=False, downloaded=None):
    return {"started_at": "2026-10-10T14:00:00+00:00", "finished_at": "2026-10-10T14:05:00+00:00", "exit_code": 0,
            "downloaded": len(changes) if downloaded is None else downloaded, "built": built,
            "changes": list(changes), "failures": []}


def run_fail(failures=("Câmara: timeout",)):
    return {"started_at": "2026-10-10T14:00:00+00:00", "finished_at": "2026-10-10T14:05:00+00:00", "exit_code": 1,
            "downloaded": 0, "built": False, "changes": [], "failures": list(failures)}


def state(tmp_path):
    return IngestionState.load(tmp_path / "s.json")


# ------------------------------- config ------------------------------- #

def test_config_from_env_defaults():
    c = NotifyConfig.from_env({})
    assert c.webhook_url is None and c.heartbeat_url is None and c.mode == "changes"


def test_config_reads_env_and_ignores_invalid_mode():
    c = NotifyConfig.from_env({"INGESTION_WEBHOOK_URL": DISCORD, "INGESTION_HEARTBEAT_URL": HB, "INGESTION_NOTIFY": "always"})
    assert (c.webhook_url, c.heartbeat_url, c.mode) == (DISCORD, HB, "always")
    assert NotifyConfig.from_env({"INGESTION_NOTIFY": "talvez"}).mode == "changes"


# ------------------------------- formatos de webhook ------------------------------- #

def test_discord_payload():
    rec = Recorder()
    with rec.client() as c:
        assert send_webhook(DISCORD, "Título", "texto", c) is True
    body = json.loads(rec.calls[0][3])
    assert "Título" in body["content"] and "texto" in body["content"]


def test_slack_payload():
    rec = Recorder()
    with rec.client() as c:
        send_webhook(SLACK, "Título", "texto", c)
    assert "Título" in json.loads(rec.calls[0][3])["text"]


def test_ntfy_payload_is_plain_text_with_title_header():
    rec = Recorder()
    with rec.client() as c:
        send_webhook(NTFY, "Ingestão falhou", "detalhe", c)
    method, url, headers, content = rec.calls[0]
    assert content.decode("utf-8") == "detalhe" and "Title" in headers


def test_generic_webhook_gets_json_title_and_text():
    rec = Recorder()
    with rec.client() as c:
        send_webhook("https://meu-servico.example.com/hook", "T", "X", c)
    body = json.loads(rec.calls[0][3])
    assert body["title"] == "T" and body["text"] == "X"


def test_long_message_is_truncated_for_discord():
    rec = Recorder()
    with rec.client() as c:
        send_webhook(DISCORD, "T", "x" * 5000, c)
    assert len(json.loads(rec.calls[0][3])["content"]) <= 2000


def test_webhook_failure_never_raises():
    def boom(request):
        raise httpx.ConnectTimeout("fora")

    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        assert send_webhook(DISCORD, "T", "X", c) is False
    with Recorder(status=500).client() as c:
        assert send_webhook(DISCORD, "T", "X", c) is False


# ------------------------------- heartbeat ------------------------------- #

def test_heartbeat_ok_pings_the_url_and_failure_pings_fail_suffix():
    rec = Recorder()
    with rec.client() as c:
        ping_heartbeat(HB, ok=True, client=c)
        ping_heartbeat(HB + "/", ok=False, client=c)
    assert [x[1] for x in rec.calls] == [HB, HB + "/fail"]


def test_heartbeat_failure_never_raises():
    def boom(request):
        raise httpx.ReadTimeout("x")

    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        assert ping_heartbeat(HB, ok=True, client=c) is False


# ------------------------------- mensagens ------------------------------- #

def test_message_for_news_lists_sources():
    title, text = format_message(run_ok(["camara-ceap-2026", "tse-bem_candidato_2026"], built=True), recovered=False)
    assert "novidade" in title.lower() and "camara-ceap-2026" in text and "publicad" in text.lower()


def test_message_for_failure_lists_errors():
    title, text = format_message(run_fail(["Câmara: timeout", "Senado: 500"]), recovered=False)
    assert "falhou" in title.lower() and "Câmara: timeout" in text and "Senado: 500" in text


def test_message_for_recovery():
    title, _ = format_message(run_ok(), recovered=True)
    assert "recuper" in title.lower() or "normaliz" in title.lower()


# ------------------------------- política de aviso ------------------------------- #

def go(tmp_path, run, env, rec=None, st=None, now="2026-10-10T14:05:00+00:00"):
    rec = rec or Recorder()
    st = st or state(tmp_path)
    with rec.client() as c:
        sent = notify_run(run, st, env, client=c, now=now)
    return sent, rec, st


ENV = {"INGESTION_WEBHOOK_URL": DISCORD, "INGESTION_HEARTBEAT_URL": HB}


def test_nothing_configured_sends_nothing(tmp_path):
    sent, rec, _ = go(tmp_path, run_fail(), {})
    assert sent == [] and rec.calls == []


def test_mode_off_sends_nothing_even_on_failure(tmp_path):
    sent, rec, _ = go(tmp_path, run_fail(), {**ENV, "INGESTION_NOTIFY": "off"})
    assert rec.calls == []


def test_failure_sends_webhook_and_fail_heartbeat(tmp_path):
    sent, rec, _ = go(tmp_path, run_fail(), ENV)
    urls = [c[1] for c in rec.calls]
    assert DISCORD in urls and HB + "/fail" in urls and set(sent) == {"webhook", "heartbeat"}


def test_success_without_news_pings_heartbeat_only_in_default_mode(tmp_path):
    sent, rec, _ = go(tmp_path, run_ok(), ENV)
    assert [c[1] for c in rec.calls] == [HB] and sent == ["heartbeat"]


def test_success_with_news_sends_webhook_and_heartbeat(tmp_path):
    sent, rec, _ = go(tmp_path, run_ok(["a"], built=True), ENV)
    assert DISCORD in [c[1] for c in rec.calls] and HB in [c[1] for c in rec.calls]


def test_mode_always_sends_webhook_even_without_news(tmp_path):
    sent, rec, _ = go(tmp_path, run_ok(), {**ENV, "INGESTION_NOTIFY": "always"})
    assert DISCORD in [c[1] for c in rec.calls]


def test_mode_failures_does_not_announce_news(tmp_path):
    sent, rec, _ = go(tmp_path, run_ok(["a"], built=True), {**ENV, "INGESTION_NOTIFY": "failures"})
    assert DISCORD not in [c[1] for c in rec.calls]


def test_repeated_identical_failure_is_not_announced_every_run(tmp_path):
    st = state(tmp_path)
    go(tmp_path, run_fail(), ENV, st=st, now="2026-10-10T14:05:00+00:00")
    _, rec, _ = go(tmp_path, run_fail(), ENV, st=st, now="2026-10-10T15:05:00+00:00")
    urls = [c[1] for c in rec.calls]
    assert DISCORD not in urls and HB + "/fail" in urls  # o heartbeat continua informando


def test_repeated_failure_is_reannounced_after_six_hours(tmp_path):
    st = state(tmp_path)
    go(tmp_path, run_fail(), ENV, st=st, now="2026-10-10T14:05:00+00:00")
    _, rec, _ = go(tmp_path, run_fail(), ENV, st=st, now="2026-10-10T20:30:00+00:00")
    assert DISCORD in [c[1] for c in rec.calls]


def test_a_different_failure_is_announced_immediately(tmp_path):
    st = state(tmp_path)
    go(tmp_path, run_fail(["Câmara: timeout"]), ENV, st=st, now="2026-10-10T14:05:00+00:00")
    _, rec, _ = go(tmp_path, run_fail(["Senado: 500"]), ENV, st=st, now="2026-10-10T15:05:00+00:00")
    assert DISCORD in [c[1] for c in rec.calls]


def test_recovery_is_announced_once_after_a_failure(tmp_path):
    st = state(tmp_path)
    go(tmp_path, run_fail(), ENV, st=st)
    _, rec, _ = go(tmp_path, run_ok(), ENV, st=st)
    assert DISCORD in [c[1] for c in rec.calls]
    _, rec2, _ = go(tmp_path, run_ok(), ENV, st=st)
    assert DISCORD not in [c[1] for c in rec2.calls]


def test_notification_memory_is_cleared_on_success(tmp_path):
    st = state(tmp_path)
    go(tmp_path, run_fail(), ENV, st=st)
    assert st.notify.get("last_failure_signature")
    go(tmp_path, run_ok(), ENV, st=st)
    assert not st.notify.get("last_failure_signature")

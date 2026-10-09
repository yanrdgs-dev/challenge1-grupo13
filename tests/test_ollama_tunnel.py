"""Proxy com Bearer (Caddy) + túnel (cloudflared) na frente do Ollama.

O Ollama não tem autenticação: sem estes dois, expor a porta 11434 entrega o modelo a qualquer um.
"""

from pathlib import Path

import pytest

from scripts import start_ollama_tunnel as tunnel

ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
KEY = "a" * 40


# ------------------------------------ Caddyfile ------------------------------------ #

@pytest.fixture(scope="module")
def caddyfile():
    assert CADDYFILE.exists(), "falta deploy/Caddyfile"
    return CADDYFILE.read_text(encoding="utf-8")


def test_requires_the_bearer_key_from_the_environment_not_from_the_file(caddyfile):
    assert 'header Authorization "Bearer {env.OLLAMA_API_KEY}"' in caddyfile
    assert KEY not in caddyfile


def test_anything_not_authorized_is_rejected_with_401(caddyfile):
    assert "respond 401" in caddyfile or "respond \"Unauthorized\" 401" in caddyfile


def test_listens_only_on_localhost_so_the_tunnel_is_the_only_way_in(caddyfile):
    assert "bind 127.0.0.1" in caddyfile


def test_only_the_inference_endpoints_are_forwarded(caddyfile):
    """Mesmo com a chave, ninguém remoto apaga nem baixa modelos (/api/delete, /api/pull, /api/create)."""
    for allowed in ("/api/chat", "/api/generate", "/api/tags"):
        assert allowed in caddyfile
    for blocked in ("/api/delete", "/api/pull", "/api/create", "/api/push", "/api/copy"):
        assert blocked not in caddyfile


def test_the_key_is_not_forwarded_to_ollama_and_bodies_are_capped(caddyfile):
    assert "header_up -Authorization" in caddyfile
    assert "max_size" in caddyfile


def test_proxies_to_the_local_ollama_and_disables_admin_and_auto_https(caddyfile):
    assert "reverse_proxy localhost:11434" in caddyfile
    assert "admin off" in caddyfile and "auto_https off" in caddyfile


# ------------------------------------ script do túnel ------------------------------------ #

class FakeProc:
    def __init__(self, cmd, env=None):
        self.cmd, self.env = cmd, env
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class Harness:
    def __init__(self, tools=("caddy", "cloudflared"), ollama=True, busy=False, valid=True,
                 proxy_codes=(401, 200), url="https://exemplo-aleatorio.trycloudflare.com"):
        self.tools, self.ollama, self.busy, self.valid = set(tools), ollama, busy, valid
        self.proxy_codes, self.url = list(proxy_codes), url
        self.procs, self.requests, self.validated = [], [], []

    def spawn(self, cmd, env=None):
        proc = FakeProc(cmd, env)
        self.procs.append(proc)
        return proc

    def http_get(self, url, headers=None):
        self.requests.append((url, headers or {}))
        return self.proxy_codes.pop(0)

    def run(self, argv=None, env=None):
        return tunnel.main(
            argv or [],
            env={"OLLAMA_API_KEY": KEY} if env is None else env,
            which=lambda name: f"/usr/bin/{name}" if name in self.tools else None,
            spawn=self.spawn,
            run_validate=lambda cmd, env: (self.validated.append((cmd, env)) or self.valid),
            http_get=self.http_get,
            ollama_up=lambda url: self.ollama,
            port_in_use=lambda port: self.busy,
            read_tunnel_url=lambda proc, timeout: self.url,
            wait_for_exit=lambda: None,
        )

    def proc(self, name):
        return next(p for p in self.procs if name in p.cmd[0])


def test_happy_path_starts_proxy_and_tunnel_and_stops_both(capsys):
    h = Harness()
    assert h.run() == 0
    assert [Path(p.cmd[0]).name for p in h.procs if Path(p.cmd[0]).name in ("caddy", "cloudflared")] == [
        "caddy", "cloudflared"]
    assert all(p.terminated for p in h.procs)
    assert "https://exemplo-aleatorio.trycloudflare.com" in capsys.readouterr().out


def test_tunnel_points_at_the_proxy_never_at_ollama_directly():
    h = Harness()
    h.run()
    cloudflared = h.proc("cloudflared")
    assert "http://localhost:8080" in cloudflared.cmd
    assert not any("11434" in part for part in cloudflared.cmd)


def test_caddy_receives_the_key_through_the_environment_not_the_command_line():
    h = Harness()
    h.run()
    caddy = h.proc("caddy")
    assert caddy.env["OLLAMA_API_KEY"] == KEY
    assert not any(KEY in part for part in caddy.cmd)


def test_caddyfile_is_validated_before_starting():
    h = Harness()
    h.run()
    assert h.validated and "validate" in h.validated[0][0]


def test_invalid_caddyfile_aborts_before_starting_anything():
    h = Harness(valid=False)
    assert h.run() == 2
    assert h.procs == []


def test_self_test_proves_401_without_the_key_and_200_with_it():
    h = Harness()
    h.run()
    (_, no_key_headers), (_, key_headers) = h.requests[:2]
    assert "Authorization" not in no_key_headers
    assert key_headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("codes", [(200, 200), (401, 401), (500, 200)])
def test_failed_self_test_aborts_and_tears_everything_down(codes, capsys):
    h = Harness(proxy_codes=codes)
    assert h.run() == 2
    assert all(p.terminated for p in h.procs)
    assert not any("cloudflared" in p.cmd[0] for p in h.procs), "o túnel só abre depois do autoteste"


@pytest.mark.parametrize("env", [{}, {"OLLAMA_API_KEY": ""}, {"OLLAMA_API_KEY": "   "}, {"OLLAMA_API_KEY": "curta"}])
def test_missing_or_weak_key_is_refused(env, capsys):
    """Chave vazia faria o matcher aceitar 'Bearer ' sem nada: a porta ficaria aberta."""
    h = Harness()
    assert h.run(env=env) == 2
    assert h.procs == []
    assert "OLLAMA_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["caddy", "cloudflared"])
def test_missing_binary_gives_an_install_hint(missing, capsys):
    h = Harness(tools=[t for t in ("caddy", "cloudflared") if t != missing])
    assert h.run() == 2
    assert h.procs == []
    err = capsys.readouterr().err
    assert missing in err and "brew install" in err


def test_ollama_down_aborts(capsys):
    h = Harness(ollama=False)
    assert h.run() == 2
    assert h.procs == []
    assert "Ollama" in capsys.readouterr().err


def test_busy_proxy_port_aborts(capsys):
    h = Harness(busy=True)
    assert h.run() == 2
    assert h.procs == []
    assert "8080" in capsys.readouterr().err


def test_tunnel_that_gives_no_url_fails_and_cleans_up():
    h = Harness(url=None)
    assert h.run() == 2
    assert all(p.terminated for p in h.procs)


def test_the_key_is_never_printed(capsys):
    h = Harness()
    h.run()
    out = capsys.readouterr()
    assert KEY not in out.out and KEY not in out.err


def test_prints_how_to_point_the_vm_at_the_new_url(capsys):
    Harness().run()
    out = capsys.readouterr().out
    assert "OLLAMA_BASE_URL=https://exemplo-aleatorio.trycloudflare.com" in out
    assert "/srv/factcheck/.env" in out


def test_no_tunnel_mode_runs_only_the_proxy_for_local_testing():
    h = Harness()
    assert h.run(["--no-tunnel"]) == 0
    assert not any("cloudflared" in p.cmd[0] for p in h.procs)


def test_extracts_the_quick_tunnel_url_from_cloudflared_output():
    lines = [
        "2026-10-09T18:00:00Z INF Thank you for trying Cloudflare Tunnel.",
        "2026-10-09T18:00:01Z INF |  https://quick-brown-fox-123.trycloudflare.com  |",
        "2026-10-09T18:00:02Z INF Registered tunnel connection",
    ]
    assert tunnel.find_tunnel_url(lines) == "https://quick-brown-fox-123.trycloudflare.com"
    assert tunnel.find_tunnel_url(["nada de url aqui"]) is None


# ------------------------------------ túnel só vale depois de registrado ------------------------------------ #

def test_registered_connection_line_is_recognized():
    assert tunnel.is_tunnel_registered(
        "2026-10-09T18:00:02Z INF Registered tunnel connection connIndex=0 event=0 location=gru01 protocol=quic")
    assert not tunnel.is_tunnel_registered("2026-10-09T18:00:01Z INF |  https://x.trycloudflare.com  |")
    assert not tunnel.is_tunnel_registered(
        "2026-10-09T18:00:19Z ERR Failed to dial a quic connection error=timeout")


def test_url_alone_is_not_enough_the_connection_must_be_registered():
    only_url = ["INF |  https://quick-fox-1.trycloudflare.com  |", "ERR Failed to dial a quic connection"]
    assert tunnel.tunnel_url_when_ready(only_url) is None
    ready = only_url[:1] + ["INF Registered tunnel connection connIndex=0"]
    assert tunnel.tunnel_url_when_ready(ready) == "https://quick-fox-1.trycloudflare.com"


def test_unreachable_cloudflare_edge_explains_the_blocked_port(capsys):
    h = Harness(url=None)
    assert h.run() == 2
    err = capsys.readouterr().err
    assert "7844" in err and "rede" in err

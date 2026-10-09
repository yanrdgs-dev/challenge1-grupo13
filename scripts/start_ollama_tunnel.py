"""Expõe o Ollama local para a VM do Azure: Caddy (exige Bearer) + túnel Cloudflare.

    OLLAMA_API_KEY=$(openssl rand -hex 32) uv run python scripts/start_ollama_tunnel.py
    uv run python scripts/start_ollama_tunnel.py --ssh deploy@<ip-da-vm> --ssh-key ~/.ssh/factcheck_vm

Antes de abrir o túnel, o script prova que o proxy responde 401 sem a chave e 200 com ela.
O túnel rápido do Cloudflare muda de URL a cada execução: copie o `OLLAMA_BASE_URL` impresso para
/srv/factcheck/.env da VM e recrie os containers. A máquina precisa ficar ligada e acordada
(no macOS o script chama `caffeinate` enquanto roda).

Modo --ssh: para redes que bloqueiam a porta 7844 do Cloudflare (campus, laboratório). Abre um túnel
SSH reverso até a VM; o Ollama passa a aparecer no gateway da rede Docker `factcheck` da VM
(172.28.0.1:11434), só para os containers. Não usa Caddy, Cloudflare nem OLLAMA_API_KEY: a barreira é
a chave SSH. Reconecta sozinho se a conexão cair.

Código de saída: 0 = encerrado normalmente, 2 = pré-condição ou autoteste falhou.
"""

import argparse
import ipaddress
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
MIN_KEY_LENGTH = 32
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# Começa por alfanumérico: um destino iniciado em "-" seria lido pelo ssh como opção (ProxyCommand etc.).
SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*$")
DEFAULT_BIND_ADDRESS = "172.28.0.1"
INITIAL_BACKOFF = 2
MAX_BACKOFF = 60
STABLE_SECONDS = 30
INSTALL_HINT = {"caddy": "brew install caddy", "cloudflared": "brew install cloudflared"}


def find_tunnel_url(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        match = TUNNEL_URL_RE.search(line)
        if match:
            return match.group(0)
    return None


def is_tunnel_registered(line: str) -> bool:
    return "Registered tunnel connection" in line


def tunnel_url_when_ready(lines: Iterable[str]) -> Optional[str]:
    """A URL só vale depois que o cloudflared registra a conexão com a borda da Cloudflare."""
    url = None
    for line in lines:
        url = url or find_tunnel_url([line])
        if url and is_tunnel_registered(line):
            return url
    return None


# --------------------------------- dependências reais --------------------------------- #

def _spawn(cmd: List[str], env: Optional[Mapping[str, str]] = None) -> Any:
    """Só o cloudflared usa pipe (a URL do túnel sai na saída dele). Pipe que ninguém lê enche e
    trava o processo, então os demais gravam o log em arquivo."""
    name = Path(cmd[0]).name
    kwargs: Dict[str, Any] = {"env": dict(env) if env is not None else None, "stderr": subprocess.STDOUT}
    if name == "cloudflared":
        kwargs.update(stdout=subprocess.PIPE, text=True)
    else:
        log_path = Path(tempfile.gettempdir()) / f"factcheck-tunnel-{name}.log"
        kwargs["stdout"] = open(log_path, "ab")
        print(f"Log do {name}: {log_path}")
    return subprocess.Popen(cmd, **kwargs)


def _run_validate(cmd: List[str], env: Mapping[str, str]) -> bool:
    result = subprocess.run(cmd, env=dict(env), capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
    return result.returncode == 0


def _http_get(url: str, headers: Optional[Dict[str, str]] = None) -> int:
    import httpx

    return httpx.get(url, headers=headers or {}, timeout=5.0).status_code


def _ollama_up(url: str) -> bool:
    import httpx

    try:
        return httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _read_tunnel_url(proc: Any, timeout: float) -> Optional[str]:
    """Lê a saída do cloudflared até achar a URL; a thread segue drenando para o pipe não encher."""
    lines: "queue.Queue[Optional[str]]" = queue.Queue()

    def pump() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    url: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=1.0)
        except queue.Empty:
            continue
        if line is None:
            return None
        url = url or find_tunnel_url([line])
        if url and is_tunnel_registered(line):
            return url
    return None


def _wait_for_signal(procs: List[Any]) -> None:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.wait(2.0):
        dead = [p for p in procs if p.poll() is not None]
        if dead:
            print("ERRO: um dos processos encerrou sozinho; derrubando o resto.", file=sys.stderr)
            return


def _stop(proc: Any) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


def _remote_check(cmd: List[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=40).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _install_signal_handlers() -> threading.Event:
    event = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: event.set())
    return event


def supervise_ssh(
    spawn: Callable,
    cmd: List[str],
    sleep: Callable,
    now: Callable,
    stopped: Callable[[], bool],
    proc: Any = None,
) -> None:
    """Mantém o túnel SSH de pé: reconecta com backoff (2 s até 60 s) quando a conexão cai.

    Uma conexão que durou pelo menos STABLE_SECONDS zera o backoff. Ao pedido de parada, derruba o
    ssh em andamento e não reconecta.
    """
    backoff = INITIAL_BACKOFF
    while True:
        if proc is None:
            proc = spawn(cmd)
        started = now()
        while proc.poll() is None:
            if stopped():
                _stop(proc)
                return
            sleep(1)
        if stopped():
            return
        lived = now() - started
        backoff = INITIAL_BACKOFF if lived >= STABLE_SECONDS else min(max(backoff, INITIAL_BACKOFF) * 2, MAX_BACKOFF)
        print(f"Túnel SSH caiu após {lived:.0f} s; reconectando em {backoff} s.", file=sys.stderr)
        sleep(backoff)
        proc = None


def _main_ssh(args: argparse.Namespace, base_env: Mapping[str, str], which: Callable, spawn: Callable,
              ollama_up: Callable, remote_check: Callable, stopped: Callable[[], bool],
              sleep: Callable, now: Callable) -> int:
    target = args.ssh or ""
    if not SSH_TARGET_RE.match(target):
        print(f"ERRO: destino SSH inválido ({target!r}). Use usuario@host, sem espaços nem opções.", file=sys.stderr)
        return 2
    try:
        bind = str(ipaddress.IPv4Address(args.bind_address))
    except ValueError:
        print(f"ERRO: --bind-address inválido ({args.bind_address!r}); use um IPv4.", file=sys.stderr)
        return 2
    if not 1 <= args.remote_port <= 65535:
        print("ERRO: --remote-port fora do intervalo 1-65535.", file=sys.stderr)
        return 2
    ssh = which("ssh")
    if not ssh:
        print("ERRO: o cliente 'ssh' não está instalado.", file=sys.stderr)
        return 2
    ollama_url = base_env.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if not ollama_up(ollama_url):
        print(f"ERRO: Ollama não respondeu em {ollama_url}. Ligue-o primeiro.", file=sys.stderr)
        return 2

    options = ["-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
               "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
    if args.ssh_key:
        options += ["-i", args.ssh_key, "-o", "IdentitiesOnly=yes"]
    forward = f"{bind}:{args.remote_port}:localhost:11434"
    cmd = [ssh, "-N", "-R", forward, *options, "--", target]
    url = f"http://{bind}:{args.remote_port}"

    proc = spawn(cmd)
    extras: List[Any] = []
    try:
        sleep(3)
        if proc.poll() is not None:
            print("ERRO: o ssh encerrou logo ao conectar. Causas comuns: chave errada ou sem permissão (use "
                  "--ssh-key), host fora do known_hosts (conecte uma vez à mão e confira a impressão digital), "
                  "IP bloqueado no NSG da VM, ou GatewayPorts ausente no sshd.", file=sys.stderr)
            return 2

        check = [ssh, *options, "--", target, f"curl -fsS -m 10 -o /dev/null {url}/api/tags"]
        ok = False
        for _ in range(3):
            if remote_check(check):
                ok = True
                break
            sleep(2)
        if not ok:
            print(f"ERRO no autoteste: a VM não alcançou o Ollama em {url}. O túnel foi encerrado.",
                  file=sys.stderr)
            _stop(proc)
            return 2

        print(f"Túnel SSH OK: a VM enxerga o Ollama em {url} (só pelos containers da rede Docker).\n"
              "Na VM, em /srv/factcheck/.env, defina:\n"
              f"  OLLAMA_BASE_URL={url}\n"
              "e recrie os containers (docker compose -f docker-compose.prod.yml up -d).\n"
              "O endereço é fixo. Ctrl+C para encerrar; se a conexão cair, ele reconecta sozinho.")
        if which("caffeinate"):
            extras.append(spawn([which("caffeinate"), "-dims", "-w", str(os.getpid())]))
        supervise_ssh(spawn, cmd, sleep=sleep, now=now, stopped=stopped, proc=proc)
        return 0
    finally:
        for extra in extras:
            _stop(extra)


# --------------------------------- orquestração --------------------------------- #

def _probe(http_get: Callable, url: str, headers: Dict[str, str], sleep: Callable, attempts: int = 20) -> Optional[int]:
    """Código HTTP, esperando o Caddy subir (conexão recusada nos primeiros instantes)."""
    for _ in range(attempts):
        try:
            return http_get(url, headers)
        except Exception:
            sleep(0.5)
    return None


def main(
    argv: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    which: Callable = shutil.which,
    spawn: Callable = _spawn,
    run_validate: Callable = _run_validate,
    http_get: Callable = _http_get,
    ollama_up: Callable = _ollama_up,
    port_in_use: Callable = _port_in_use,
    read_tunnel_url: Callable = _read_tunnel_url,
    wait_for_exit: Optional[Callable[[], None]] = None,
    sleep: Callable = time.sleep,
    remote_check: Callable = _remote_check,
    stopped: Optional[Callable[[], bool]] = None,
    now: Callable = time.monotonic,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8080, help="Porta local do proxy (padrão 8080).")
    parser.add_argument("--no-tunnel", action="store_true", help="Só o proxy, para testar localmente.")
    parser.add_argument("--caddyfile", default=str(CADDYFILE))
    parser.add_argument("--ssh", metavar="USUARIO@HOST", default=None,
                        help="Túnel SSH reverso até a VM, em vez de Caddy + Cloudflare.")
    parser.add_argument("--ssh-key", default=None, help="Chave privada para o --ssh.")
    parser.add_argument("--bind-address", default=DEFAULT_BIND_ADDRESS,
                        help="Endereço de escuta na VM (gateway da rede Docker). Padrão 172.28.0.1.")
    parser.add_argument("--remote-port", type=int, default=11434, help="Porta de escuta na VM.")
    args = parser.parse_args(argv)

    base_env = dict(os.environ if env is None else env)
    if args.ssh is not None:
        return _main_ssh(args, base_env, which, spawn, ollama_up, remote_check,
                         stopped or _install_signal_handlers().is_set, sleep, now)
    key = (base_env.get("OLLAMA_API_KEY") or "").strip()
    if len(key) < MIN_KEY_LENGTH:
        print(f"ERRO: OLLAMA_API_KEY ausente ou curta (mínimo {MIN_KEY_LENGTH} caracteres). "
              "Gere uma com: openssl rand -hex 32", file=sys.stderr)
        return 2

    needed = ["caddy"] + ([] if args.no_tunnel else ["cloudflared"])
    for tool in needed:
        if not which(tool):
            print(f"ERRO: '{tool}' não está instalado. Instale com: {INSTALL_HINT[tool]}", file=sys.stderr)
            return 2

    ollama_url = base_env.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if not ollama_up(ollama_url):
        print(f"ERRO: Ollama não respondeu em {ollama_url}. Ligue-o primeiro.", file=sys.stderr)
        return 2
    if port_in_use(args.port):
        print(f"ERRO: a porta {args.port} já está em uso.", file=sys.stderr)
        return 2

    caddy_env = {**base_env, "OLLAMA_API_KEY": key, "PROXY_PORT": str(args.port)}
    caddy_cmd = [which("caddy"), "run", "--config", args.caddyfile, "--adapter", "caddyfile"]
    if not run_validate([which("caddy"), "validate", "--config", args.caddyfile, "--adapter", "caddyfile"], caddy_env):
        print("ERRO: o Caddyfile é inválido.", file=sys.stderr)
        return 2

    procs: List[Any] = []
    try:
        procs.append(spawn(caddy_cmd, caddy_env))
        proxy = f"http://127.0.0.1:{args.port}"

        # Autoteste: sem a chave tem de ser 401; com a chave tem de chegar ao Ollama (200).
        without_key = _probe(http_get, f"{proxy}/api/tags", {}, sleep)
        with_key = _probe(http_get, f"{proxy}/api/tags", {"Authorization": f"Bearer {key}"}, sleep)
        if without_key != 401 or with_key != 200:
            print(f"ERRO no autoteste do proxy: sem chave={without_key} (esperado 401), "
                  f"com chave={with_key} (esperado 200). O túnel não foi aberto.", file=sys.stderr)
            return 2
        print(f"Proxy OK em {proxy} (401 sem chave, 200 com chave).")

        if args.no_tunnel:
            print("Modo --no-tunnel: Ctrl+C para encerrar.")
        else:
            cloudflared = spawn([which("cloudflared"), "tunnel", "--url", f"http://localhost:{args.port}",
                                 "--no-autoupdate"])
            procs.append(cloudflared)
            url = read_tunnel_url(cloudflared, 45.0)
            if not url:
                print("ERRO: o cloudflared não conseguiu conectar à Cloudflare em 45 s. Redes que bloqueiam a "
                      "porta 7844 (UDP e TCP), como as de campus e laboratório, impedem o túnel: tente outra "
                      "rede (hotspot do celular) ou use uma alternativa que saia pela 443.", file=sys.stderr)
                return 2
            print(f"\nTúnel aberto: {url}\n"
                  "Na VM do Azure, em /srv/factcheck/.env, defina:\n"
                  f"  OLLAMA_BASE_URL={url}\n"
                  "  OLLAMA_API_KEY=<a mesma chave>\n"
                  "e recrie os containers (docker compose -f docker-compose.prod.yml up -d).\n"
                  "A URL muda a cada execução. Ctrl+C para encerrar.")

        if which("caffeinate"):
            procs.append(spawn([which("caffeinate"), "-dims", "-w", str(os.getpid())]))

        (wait_for_exit or (lambda: _wait_for_signal(procs)))()
        return 0
    finally:
        for proc in reversed(procs):
            _stop(proc)


if __name__ == "__main__":
    sys.exit(main())

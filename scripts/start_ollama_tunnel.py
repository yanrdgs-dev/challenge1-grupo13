"""Expõe o Ollama local para a VM do Azure: Caddy (exige Bearer) + túnel Cloudflare.

    OLLAMA_API_KEY=$(openssl rand -hex 32) uv run python scripts/start_ollama_tunnel.py

Antes de abrir o túnel, o script prova que o proxy responde 401 sem a chave e 200 com ela.
O túnel rápido do Cloudflare muda de URL a cada execução: copie o `OLLAMA_BASE_URL` impresso para
/srv/factcheck/.env da VM e recrie os containers. A máquina precisa ficar ligada e acordada
(no macOS o script chama `caffeinate` enquanto roda).

Código de saída: 0 = encerrado normalmente, 2 = pré-condição ou autoteste falhou.
"""

import argparse
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
INSTALL_HINT = {"caddy": "brew install caddy", "cloudflared": "brew install cloudflared"}


def find_tunnel_url(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        match = TUNNEL_URL_RE.search(line)
        if match:
            return match.group(0)
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
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=1.0)
        except queue.Empty:
            continue
        if line is None:
            return None
        url = find_tunnel_url([line])
        if url:
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
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8080, help="Porta local do proxy (padrão 8080).")
    parser.add_argument("--no-tunnel", action="store_true", help="Só o proxy, para testar localmente.")
    parser.add_argument("--caddyfile", default=str(CADDYFILE))
    args = parser.parse_args(argv)

    base_env = dict(os.environ if env is None else env)
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
            url = read_tunnel_url(cloudflared, 30.0)
            if not url:
                print("ERRO: o cloudflared não informou a URL do túnel em 30 s.", file=sys.stderr)
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

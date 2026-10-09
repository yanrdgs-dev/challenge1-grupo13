"""Roda a avaliação completa: sobe judge e router, executa o golden experiment e derruba os serviços.

Uso manual, na máquina onde o Ollama está ligado (não roda a cada push):
    uv run python scripts/run_eval.py
    uv run python scripts/run_eval.py --run-name prompt-novo --prompt-label staging

Opções que o script não conhece (--run-name, --local, --threshold ...) vão direto para
scripts/run_golden_experiment.py. Código de saída: 0 = gate aprovado, 1 = reprovado, 2 = erro de
uso ou de infraestrutura (Ollama fora do ar, porta ocupada, serviço que não subiu).
"""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTER_PORT = 18000
DEFAULT_JUDGE_PORT = 18001
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM_TIMEOUT = "120"
STOP_GRACE_SECONDS = 10


class WaitTimeout(Exception):
    """O processo não terminou dentro do prazo (par de subprocess.TimeoutExpired)."""


# --------------------------------- dependências reais --------------------------------- #

_log_dir: Optional[Path] = None


def _spawn(cmd: List[str], env: Dict[str, str]) -> Any:
    """Sobe um serviço com o log em arquivo (pipe cheio travaria o processo)."""
    global _log_dir
    if _log_dir is None:
        _log_dir = Path(tempfile.mkdtemp(prefix="factcheck-eval-"))
    name = "judge" if "judge_service" in " ".join(cmd) else "router"
    log = open(_log_dir / f"{name}.log", "wb")
    return subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)


def _is_healthy(url: str) -> bool:
    import httpx

    try:
        return httpx.get(f"{url}/health", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _ollama_up(url: str) -> bool:
    import httpx

    headers = {}
    api_key = (os.getenv("OLLAMA_API_KEY") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        return httpx.get(f"{url.rstrip('/')}/api/tags", headers=headers, timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


def _experiment(argv: List[str]) -> int:
    from scripts.run_golden_experiment import main as golden_main

    return golden_main(argv)


# --------------------------------- orquestração --------------------------------- #

def _stop(proc: Any) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except (WaitTimeout, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait(timeout=STOP_GRACE_SECONDS)


def _service_env(base: Mapping[str, str], prompt_label: Optional[str], judge_url: Optional[str]) -> Dict[str, str]:
    env = dict(base)
    env.setdefault("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT)
    if prompt_label:
        env["LANGFUSE_PROMPT_LABEL"] = prompt_label
    if judge_url:
        env["JUDGE_SERVICE_URL"] = judge_url
    return env


def _wait_until_healthy(
    services: Dict[str, Any], urls: Dict[str, str], timeout: int, is_healthy: Callable, sleep: Callable
) -> Optional[str]:
    """Devolve None quando todos respondem, ou a mensagem de erro."""
    for _ in range(max(timeout, 1)):
        for name, proc in services.items():
            if proc.poll() is not None:
                return f"O serviço '{name}' encerrou durante a subida (código {proc.poll()})."
        if all(is_healthy(url) for url in urls.values()):
            return None
        sleep(1)
    return f"Os serviços não ficaram saudáveis em {timeout} s."


def main(
    argv: Optional[List[str]] = None,
    spawn: Callable = _spawn,
    experiment: Callable = _experiment,
    is_healthy: Callable = _is_healthy,
    port_in_use: Callable = _port_in_use,
    ollama_up: Callable = _ollama_up,
    sleep: Optional[Callable] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    import time

    sleep = sleep or time.sleep
    base_env = os.environ if env is None else env

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompt-label", default=None, help="Label dos prompts no Langfuse (ex.: staging).")
    parser.add_argument("--startup-timeout", type=int, default=120, help="Segundos para os serviços subirem.")
    parser.add_argument("--router-port", type=int, default=DEFAULT_ROUTER_PORT)
    parser.add_argument("--judge-port", type=int, default=DEFAULT_JUDGE_PORT)
    args, experiment_args = parser.parse_known_args(argv)

    ollama_url = base_env.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL)
    if not ollama_up(ollama_url):
        print(f"ERRO: Ollama não respondeu em {ollama_url}. Ligue-o (e o túnel, se for remoto) e tente de novo.",
              file=sys.stderr)
        return 2
    for port in (args.judge_port, args.router_port):
        if port_in_use(port):
            print(f"ERRO: a porta {port} já está em uso; medir outro serviço invalidaria o experiment.",
                  file=sys.stderr)
            return 2

    judge_url = f"http://localhost:{args.judge_port}"
    router_url = f"http://localhost:{args.router_port}"
    python = [sys.executable, "-m", "uvicorn"]
    services: Dict[str, Any] = {}

    try:
        services["judge"] = spawn(
            python + ["src.services.judge_service:app", "--port", str(args.judge_port)],
            _service_env(base_env, args.prompt_label, None),
        )
        services["router"] = spawn(
            python + ["src.services.router_service:app", "--port", str(args.router_port)],
            _service_env(base_env, args.prompt_label, judge_url),
        )

        problem = _wait_until_healthy(
            services, {"judge": judge_url, "router": router_url}, args.startup_timeout, is_healthy, sleep
        )
        if problem:
            print(f"ERRO: {problem}", file=sys.stderr)
            return 2

        try:
            return experiment(["--router-url", router_url] + experiment_args)
        except Exception as exc:
            print(f"ERRO de execução: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    finally:
        for name in ("router", "judge"):
            if name in services:
                _stop(services[name])
        if _log_dir is not None:
            print(f"Logs dos serviços: {_log_dir}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    sys.exit(main())

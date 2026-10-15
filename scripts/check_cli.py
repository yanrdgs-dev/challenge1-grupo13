"""CLI local: envia uma alegação ao router e mostra o veredito, sem abrir o site.

Na máquina onde o Ollama está ligado (sobe o judge e o router em portas locais e derruba ao sair):
    uv run python scripts/check_cli.py                               # modo interativo
    uv run python scripts/check_cli.py "O PL 2630/2020 foi aprovado?"  # uma pergunta só

Com um router já no ar (por exemplo, a stack do docker compose), sem subir nada:
    uv run python scripts/check_cli.py --url http://localhost:8000 "O PLN 2/2025 trata da LDO de 2026?"

Opções que o script não conhece (--prompt-label, --router-port, --judge-port ...) vão para scripts/run_eval.py.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUEST_TIMEOUT_SECONDS = 300.0   # uma checagem com o modelo local leva de 10 s a alguns minutos
EXIT_WORDS = {"sair", "exit", "quit", "q"}


def ask(url: str, claim: str, client: Any = None) -> Dict[str, Any]:
    """POST /check do router; erro HTTP vira RuntimeError legível."""
    import httpx

    http = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    response = http.post(f"{url.rstrip('/')}/check", json={"claim": claim})
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"{response.status_code} {detail}")
    return response.json()


def format_response(data: Dict[str, Any]) -> str:
    """Resposta do /check em texto para o terminal (partes ausentes são omitidas)."""
    head = f"{data.get('veredito', '?')}"
    if data.get("confianca"):
        head += f"  (confiança {data['confianca']})"
    lines = ["", head]
    if data.get("justificativa"):
        lines.append(data["justificativa"])
    if data.get("fontes_primarias"):
        lines.append("Fontes: " + "; ".join(data["fontes_primarias"]))
    if data.get("ferramentas_usadas"):
        lines.append("Ferramentas: " + " → ".join(data["ferramentas_usadas"]))
    if data.get("regra_acionada"):
        lines.append(f"Regra: {data['regra_acionada']}")
    if data.get("dados_atualizados_em"):
        lines.append(f"Base atualizada em: {str(data['dados_atualizados_em'])[:10]}")
    if data.get("tempo_total_ms") is not None:
        lines.append(f"Tempo: {data['tempo_total_ms'] / 1000:.1f} s".replace(".", ","))
    return "\n".join(lines) + "\n"


def session(
    url: str,
    ask: Callable[[str, str], Dict[str, Any]] = ask,
    read: Callable[[str], str] = input,
    out: Optional[TextIO] = None,
) -> int:
    """Laço interativo: uma linha = uma alegação. Linha vazia é ignorada; 'sair', Ctrl+D ou Ctrl+C encerram."""
    out = out or sys.stdout
    print("Digite a alegação e Enter ('sair' para encerrar).", file=out)
    while True:
        try:
            claim = read("alegação> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return 0
        if not claim:
            continue
        if claim.lower() in EXIT_WORDS:
            return 0
        try:
            print(format_response(ask(url, claim)), file=out)
        except Exception as exc:
            print(f"ERRO: {exc}", file=out)


def _start_services(run_session: Callable[[str], int], argv: List[str]) -> int:
    """Sobe judge e router locais (reaproveita o orquestrador do run_eval) e roda a sessão neles."""
    from scripts import run_eval

    return run_eval.main(argv, experiment=lambda args: run_session(args[args.index("--router-url") + 1]))


def main(
    argv: Optional[List[str]] = None,
    ask: Callable[..., Dict[str, Any]] = ask,
    start_services: Callable[..., int] = _start_services,
    interactive: Optional[Callable[[str], int]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("claim", nargs="?", help="Alegação (sem ela, abre o modo interativo).")
    parser.add_argument("--url", default=None, help="Router já no ar; sem ele os serviços locais são iniciados.")
    args, passthrough = parser.parse_known_args(argv)

    def run_session(url: str) -> int:
        if args.claim:
            try:
                print(format_response(ask(url, args.claim)))
                return 0
            except Exception as exc:
                print(f"ERRO: {exc}", file=sys.stderr)
                return 1
        return interactive(url) if interactive else session(url, ask=ask)

    if args.url:
        return run_session(args.url)
    return start_services(run_session, passthrough)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    sys.exit(main())

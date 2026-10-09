"""Publica os prompts padrão (src/prompts/defaults.py) no Langfuse.

Regras:
- Prompt que ainda não existe  -> criado com a label ``production`` (migração inicial).
- Prompt igual ao de produção  -> nada a fazer.
- Prompt diferente do de produção -> nova versão com a label ``staging`` (nunca direto em produção).
  Depois, rode o experiment com ``LANGFUSE_PROMPT_LABEL=staging`` e promova pela interface do Langfuse.

Uso:
    uv run python scripts/langfuse_push_prompts.py
    uv run python scripts/langfuse_push_prompts.py --dry-run
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.prompts.defaults import DEFAULT_PROMPTS  # noqa: E402


def _langfuse_client():
    from dotenv import load_dotenv
    from langfuse import get_client

    load_dotenv()
    return get_client()


def push_prompts(client: Any, prompts: Dict[str, str], dry_run: bool = False) -> List[Dict[str, Any]]:
    results = []
    for name, text in prompts.items():
        try:
            current = client.get_prompt(name, label="production", type="text", cache_ttl_seconds=0, max_retries=0)
        except Exception:
            current = None

        if current is None:
            action, labels = "criado", ["production"]
        elif current.prompt == text:
            results.append({"name": name, "action": "sem mudança", "version": current.version})
            continue
        else:
            action, labels = "nova versão (staging)", ["staging"]

        if not dry_run:
            client.create_prompt(name=name, prompt=text, labels=labels, type="text")
        results.append({"name": name, "action": action, "labels": labels})
    return results


def main(argv: Optional[List[str]] = None, client_factory: Callable = _langfuse_client) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria feito sem escrever.")
    args = parser.parse_args(argv)

    try:
        client = None if args.dry_run else client_factory()
        if args.dry_run:
            for name in DEFAULT_PROMPTS:
                print(f"[dry-run] {name}")
            return 0
        results = push_prompts(client, DEFAULT_PROMPTS)
    except Exception as exc:
        print(f"ERRO: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    for item in results:
        print(f"{item['name']}: {item['action']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

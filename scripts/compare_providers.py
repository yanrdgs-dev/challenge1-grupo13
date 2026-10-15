"""Roda as claims da demonstração em cada provedor de LLM, um por vez, e registra cada execução no Langfuse.

Cada execução sobe o judge e o router locais com UM provedor só (``LLM_PROVIDERS=<provedor>``, sem fallback), roda
``evaluation/golden_demo_claims.json`` e grava o experimento no Langfuse com o nome ``demo-<provedor>``. Assim dá
para comparar vereditos, rastros e tempo lado a lado, e filtrar as generations pelo modelo que respondeu.

Uso manual (as chaves de Groq e DeepSeek ficam no .env; nada é impresso):
    uv run python scripts/compare_providers.py                       # groq, deepseek e ollama
    uv run python scripts/compare_providers.py --providers groq,deepseek
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEMO_CLAIMS = ROOT / "evaluation" / "golden_demo_claims.json"
KNOWN = ("groq", "deepseek", "ollama")


def provider_env(base: Dict[str, str], provider: str) -> Dict[str, str]:
    """Ambiente dos serviços com um único provedor e sem rotação: o resultado é só daquele provedor."""
    env = dict(base)
    env["LLM_PROVIDERS"] = provider
    env["LLM_STRATEGY"] = "fallback"
    env.pop("LLM_PROVIDER", None)
    env.pop("FALLBACK_PROVIDER", None)
    env.setdefault("ROUTER_LLM_TIMEOUT", "120")
    env["DEEPSEEK_DAILY_CAP"] = env.get("DEEPSEEK_DAILY_CAP") or "0"   # o teto padrão (200) não corta a comparação
    return env


def main(
    argv: Optional[List[str]] = None,
    run_eval_main: Optional[Callable[..., int]] = None,
    base_env: Optional[Dict[str, str]] = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--providers", default="groq,deepseek,ollama")
    parser.add_argument("--claims", default=str(DEMO_CLAIMS))
    parser.add_argument("--prompt-label", default="eval")
    parser.add_argument("--out-dir", default=None, help="Pasta para os resumos JSON de cada provedor.")
    args = parser.parse_args(argv)

    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    unknown = [p for p in providers if p not in KNOWN]
    if unknown:
        print(f"Provedor desconhecido: {unknown}. Opções: {list(KNOWN)}", file=sys.stderr)
        return 2

    if run_eval_main is None:
        from scripts import run_eval

        run_eval_main = run_eval.main
    base = dict(os.environ if base_env is None else base_env)
    codes: Dict[str, int] = {}
    for provider in providers:
        extra = ["--json-out", str(Path(args.out_dir) / f"demo-{provider}.json")] if args.out_dir else []
        started = time.perf_counter()
        print(f"\n=== {provider} ===", flush=True)
        codes[provider] = run_eval_main(
            ["--prompt-label", args.prompt_label, "--run-name", f"demo-{provider}", "--local",
             "--golden-path", args.claims, *extra],
            env=provider_env(base, provider),
        )
        print(f"=== {provider}: código {codes[provider]} em {time.perf_counter() - started:.0f} s ===", flush=True)
    print("\nResumo:", json.dumps(codes))
    return 0 if all(code in (0, 1) for code in codes.values()) else 2   # 1 = gate reprovado, não é erro de infraestrutura


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    sys.exit(main())

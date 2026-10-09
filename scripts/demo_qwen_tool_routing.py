#!/usr/bin/env python3
"""Demo interativa de roteamento e classificação de tools com Qwen2.5:7b via Ollama.

Permite testar como o modelo qwen2.5:7b atua como Agente Roteador, identificando
qual tool do catálogo de fact-checking chamar e quais parâmetros extrair da frase.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

# Permite rodar o script diretamente (python scripts/demo_qwen_tool_routing.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tools.knowledge_tools import DATA_SOURCES, INSTITUTIONAL_TOPICS, available_data_types  # noqa: E402

# Adiciona o diretório raiz ao PYTHONPATH
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Importa as tools reais já implementadas no projeto
try:
    from src.tools.resolve_politician import resolve_politician
    from src.tools.resolve_proposition import resolve_proposition
except ImportError:
    resolve_politician = None  # type: ignore
    resolve_proposition = None  # type: ignore

# Códigos de cor ANSI para terminal
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"
DIM = "\033[2m"

# Catálogo oficial de tools do Agente Roteador
# Catálogo de tools e prompt do router: definidos em src/ (as imagens não levam scripts/).
from src.services.tool_catalog import ROUTER_SYSTEM_PROMPT, TOOLS_CATALOG  # noqa: E402,F401

# Frases de exemplo usadas só pelo demo (avaliação em lote e modo interativo).
SAMPLE_CLAIMS = [
    {
        "id": 1,
        "text": "Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS).",
        "expected_tool": "get_top_ceap_spender",
    },
    {
        "id": 2,
        "text": "Senadores podem usar a verba indenizatória (CEAPS) para pagar consultorias e assessorias técnicas para o mandato.",
        "expected_tool": "list_expense_categories",
    },
    {
        "id": 4,
        "text": "A urgência do PL 2630/2020, o chamado 'PL das Fake News', foi aprovada pelo Plenário da Câmara dos Deputados.",
        "expected_tool": "resolve_proposition",
    },
    {
        "id": 5,
        "text": "O Senado aprovou, em votação nominal, o texto-base da PEC da Reforma Tributária em 2023.",
        "expected_tool": "resolve_proposition",
    },
    {
        "id": 13,
        "text": "Existe um limite máximo de R$ 500 por mês para gastos com combustível na Câmara dos Deputados em 2023.",
        "expected_tool": "check_parliamentary_expenses",
    },
    {
        "id": 15,
        "text": "O Congresso aprovou a tese do Marco Temporal para demarcação de terras indígenas em 2023.",
        "expected_tool": "resolve_proposition",
    },
    {
        "id": "extra-1",
        "text": "Nikolas Ferreira é deputado federal eleito por Minas Gerais.",
        "expected_tool": "resolve_politician",
    },
    {
        "id": "extra-2",
        "text": "A senadora Soraya Thronicke votou a favor da cassação na CPI em 2021.",
        "expected_tool": "resolve_politician",
    },
]


def call_ollama_router(
    prompt: str,
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Envia a frase ao modelo qwen2.5 no Ollama com as tools habilitadas."""
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "tools": TOOLS_CATALOG,
        "stream": False,
    }

    start = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    duration_s = time.perf_counter() - start

    message = data.get("message", {})
    tool_calls = message.get("tool_calls", [])
    content = message.get("content", "")

    return {
        "tool_calls": tool_calls,
        "content": content,
        "duration_s": duration_s,
        "raw_response": data,
    }


def execute_live_tool(tool_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Executa a tool Python real caso já esteja implementada no projeto."""
    if tool_name == "resolve_politician" and resolve_politician is not None:
        try:
            res = resolve_politician(
                nome_busca=args.get("nome_busca", ""),
                uf=args.get("uf"),
                cargo=args.get("cargo"),
                ano=args.get("ano"),
            )
            # Fallback defensivo: se não encontrou com a UF fornecida, tenta sem a UF
            # para o caso de a alegação ter citado o estado errado
            if (res.get("ideCadastro") is None and res.get("sq_candidato") is None) and args.get("uf"):
                fallback = resolve_politician(
                    nome_busca=args.get("nome_busca", ""),
                    cargo=args.get("cargo"),
                    ano=args.get("ano"),
                )
                if fallback.get("ideCadastro") or fallback.get("sq_candidato"):
                    return fallback
            return res
        except Exception as e:
            return {"erro": str(e)}

    if tool_name == "resolve_proposition" and resolve_proposition is not None:
        try:
            return resolve_proposition(
                casa=args.get("casa", "camara"),
                sigla_tipo=args.get("sigla_tipo"),
                numero=args.get("numero"),
                ano=args.get("ano"),
                termo_busca=args.get("termo_busca"),
            )
        except Exception as e:
            return {"erro": str(e)}

    return None


def print_routing_result(phrase: str, result: Dict[str, Any], show_live_exec: bool = True) -> None:
    """Exibe o resultado do roteamento de forma visual e colorida."""
    duration = result["duration_s"]
    tool_calls = result["tool_calls"]
    content = result["content"].strip()

    print(f"\n{BOLD}{'='*80}{RESET}")
    print(f"{BOLD}💬 Frase / Claim:{RESET} {YELLOW}\"{phrase}\"{RESET}")
    print(f"{DIM}⏱️  Latência de Inferência:{RESET} {CYAN}{duration*1000:.1f} ms{RESET}")

    if content:
        print(f"\n{BOLD}💡 Raciocínio do Qwen2.5:{RESET}\n  {DIM}{content}{RESET}")

    if not tool_calls:
        print(f"\n{RED}❌ Nenhuma tool foi acionada pelo modelo.{RESET}")
        return

    print(f"\n{BOLD}🛠️  Tool(s) Selecionada(s):{RESET}")
    for idx, tc in enumerate(tool_calls, 1):
        fn = tc.get("function", {})
        tool_name = fn.get("name", "desconhecida")
        args = fn.get("arguments", {})

        print(f"  {BOLD}[{idx}] {GREEN}{tool_name}{RESET}")
        print(f"      {BOLD}Parâmetros extraídos:{RESET}")
        for param, val in args.items():
            print(f"        • {CYAN}{param}{RESET}: {BOLD}{val}{RESET}")

        if show_live_exec and tool_name in ("resolve_politician", "resolve_proposition"):
            print(f"\n      {MAGENTA}⚡ Executando tool real do projeto no código...{RESET}")
            start_exec = time.perf_counter()
            exec_res = execute_live_tool(tool_name, args)
            exec_time = (time.perf_counter() - start_exec) * 1000
            print(f"      {DIM}(Concluído em {exec_time:.2f} ms){RESET}")
            if exec_res:
                print(f"      {BOLD}Retorno da Tool:{RESET}")
                formatted = json.dumps(exec_res, indent=8, ensure_ascii=False)
                # Remove primeira linha de indentação para alinhar
                print(f"        {formatted.strip()}")


def run_batch_evaluation(model: str, base_url: str) -> None:
    """Executa a bateria de testes com amostras do Golden Dataset."""
    print(f"\n{BOLD}{CYAN}=== INICIANDO BENCHMARK DE ROTEAMENTO ({model}) ==={RESET}")
    print(f"Testando {len(SAMPLE_CLAIMS)} alegações representativas...\n")

    correct = 0
    total = len(SAMPLE_CLAIMS)
    latencies: List[float] = []

    for item in SAMPLE_CLAIMS:
        phrase = item["text"]
        expected = item["expected_tool"]

        print(f"{BOLD}[Claim {item['id']}]{RESET} {phrase[:65]}...")
        try:
            res = call_ollama_router(phrase, model=model, base_url=base_url)
            latencies.append(res["duration_s"])
            tool_calls = res.get("tool_calls", [])

            if tool_calls:
                chosen = tool_calls[0].get("function", {}).get("name", "")
                args = tool_calls[0].get("function", {}).get("arguments", {})
                is_match = (chosen == expected)
                if is_match:
                    correct += 1
                    status = f"{GREEN}✓ CORRETO{RESET}"
                else:
                    status = f"{RED}✗ DIVERGENTE (Esperava {expected}){RESET}"

                print(f"  → Tool: {BOLD}{chosen}{RESET} | Args: {args} | {status} ({res['duration_s']*1000:.0f}ms)")
            else:
                print(f"  → {RED}Nenhuma tool chamada (Esperava {expected}){RESET}")
        except Exception as e:
            print(f"  → {RED}Erro na chamada ao Ollama: {e}{RESET}")
        print()

    avg_latency = (sum(latencies) / len(latencies)) * 1000 if latencies else 0.0
    accuracy = (correct / total) * 100

    print(f"{BOLD}{'='*80}{RESET}")
    print(f"{BOLD}📊 RESUMO DO BENCHMARK ({model}):{RESET}")
    print(f"  • Acurácia de Classificação de Tool: {GREEN if accuracy >= 80 else YELLOW}{accuracy:.1f}% ({correct}/{total}){RESET}")
    print(f"  • Latência Média por Inferência: {CYAN}{avg_latency:.1f} ms{RESET}")
    print(f"{BOLD}{'='*80}{RESET}\n")


def interactive_mode(model: str, base_url: str) -> None:
    """Modo direto: uma frase por input com classificação imediata."""
    print(f"\n{BOLD}{GREEN}=== Classificador de Tools com {model} (Ollama) ==={RESET}")
    print(f"{DIM}Servidor: {base_url}{RESET}")
    print(f"Digite uma frase por vez para identificar a tool e os parâmetros.")
    print(f"{DIM}(Pressione Enter vazio ou Ctrl+C para sair){RESET}\n")

    counter = 1
    while True:
        try:
            prompt_label = f"{BOLD}[Frase {counter}] Digite a frase > {RESET}"
            user_input = input(prompt_label).strip()

            if not user_input or user_input.lower() in ("sair", "exit", "quit", "q"):
                print("\nEncerrando a demo. Até mais!")
                break

            print(f"{DIM}Classificando com {model}...{RESET}")
            result = call_ollama_router(user_input, model=model, base_url=base_url)
            print_routing_result(user_input, result, show_live_exec=True)
            print()
            counter += 1

        except (KeyboardInterrupt, EOFError):
            print("\n\nEncerrando a demo. Até mais!")
            break
        except Exception as e:
            print(f"{RED}Erro ao processar frase: {e}{RESET}\n")



def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo de classificação e roteamento de tools com Qwen2.5:7b via Ollama."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen2.5:7b",
        help="Nome do modelo no Ollama (padrão: qwen2.5:7b)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="http://localhost:11434",
        help="URL base do Ollama (padrão: http://localhost:11434)",
    )
    parser.add_argument(
        "--phrase",
        type=str,
        default=None,
        help="Testa diretamente uma frase específica via CLI",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Executa o benchmark em lote com as alegações do Golden Dataset",
    )

    args = parser.parse_args()

    # Validação rápida de conectividade com o Ollama
    try:
        resp = httpx.get(f"{args.host.rstrip('/')}/api/tags", timeout=5.0)
        resp.raise_for_status()
        installed_models = [m["name"] for m in resp.json().get("models", [])]
        matched = any(args.model in m for m in installed_models)
        if not matched:
            print(f"{YELLOW}Aviso: Modelo '{args.model}' não foi encontrado explicitamente em: {installed_models}{RESET}")
    except Exception as e:
        print(f"{RED}Erro: Não foi possível conectar ao Ollama em {args.host}: {e}{RESET}")
        print("Verifique se o Ollama está rodando ('ollama serve').")
        sys.exit(1)

    if args.phrase:
        res = call_ollama_router(args.phrase, model=args.model, base_url=args.host)
        print_routing_result(args.phrase, res, show_live_exec=True)
    elif args.batch:
        run_batch_evaluation(model=args.model, base_url=args.host)
    else:
        interactive_mode(model=args.model, base_url=args.host)


if __name__ == "__main__":
    main()

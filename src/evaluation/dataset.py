"""Carga, validação e sincronização idempotente do golden dataset com o Langfuse."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

logger = logging.getLogger("Evaluation.Dataset")

DATASET_NAME = "golden_dataset_v1"
VALID_VERDICTS = ("VERDADEIRO", "FALSO", "INCONCLUSIVO")
VALID_CATEGORIES = ("GASTOS", "VOTACOES", "ELEICOES")
# Por que uma claim esperada INCONCLUSIVO o é: sem ponto de ancoragem (nenhuma tool deve rodar) ou porque a tool
# rodou e não trouxe evidência (candidato ambíguo ou inexistente, dado ainda não publicado).
VALID_INCONCLUSIVE_REASONS = ("subespecificada", "evidencia_vazia")


class DatasetSyncError(RuntimeError):
    """Falha ao sincronizar o dataset (criação do dataset ou de algum item)."""


def item_id(golden_id: int, dataset_name: str = DATASET_NAME) -> str:
    """ID determinístico do item no Langfuse (upsert por id; precisa ser globalmente único)."""
    return f"{dataset_name}-claim-{int(golden_id):02d}"


def load_golden_dataset(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Lê e valida o ``golden_dataset_v1.json``. Levanta ``ValueError`` se estiver malformado."""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        raise ValueError("O golden dataset deve ser uma lista não vazia.")

    seen = set()
    for position, entry in enumerate(items, start=1):
        if not isinstance(entry, dict) or entry.get("id") is None:
            raise ValueError(f"Item {position} sem 'id'.")
        if entry["id"] in seen:
            raise ValueError(f"Id duplicado no golden dataset: {entry['id']}.")
        seen.add(entry["id"])
        if not str(entry.get("claim") or "").strip():
            raise ValueError(f"Claim {entry['id']} está vazia.")
        if entry.get("expected_verdict") not in VALID_VERDICTS:
            raise ValueError(f"Claim {entry['id']}: veredito esperado inválido ({entry.get('expected_verdict')!r}).")
        if entry.get("category") not in VALID_CATEGORIES:
            raise ValueError(f"Claim {entry['id']}: categoria inválida ({entry.get('category')!r}).")
        reason = entry.get("inconclusive_reason")
        if reason is not None and reason not in VALID_INCONCLUSIVE_REASONS:
            raise ValueError(f"Claim {entry['id']}: inconclusive_reason inválido ({reason!r}).")
    return items


def sync_golden_dataset(
    client: Any, items: List[Dict[str, Any]], dry_run: bool = False, dataset_name: str = DATASET_NAME
) -> Dict[str, Any]:
    """Cria o dataset e faz upsert de cada claim pelo id determinístico (rodar de novo é seguro).

    Tenta todos os itens e, se algum falhar, levanta ``DatasetSyncError`` listando os ids.
    """
    summary = {"dataset": dataset_name, "items": len(items)}
    if dry_run:
        return summary

    try:
        client.create_dataset(
            name=dataset_name,
            description=f"{dataset_name}: claims com veredito esperado (VERDADEIRO, FALSO e INCONCLUSIVO) - portão de aceite da regra 5.",
            metadata={"source": f"{dataset_name}.json"},
        )
    except Exception as exc:
        raise DatasetSyncError(f"Não foi possível criar o dataset '{dataset_name}': {exc}") from exc

    failed = []
    for entry in items:
        try:
            client.create_dataset_item(
                dataset_name=dataset_name,
                id=item_id(entry["id"], dataset_name),
                input={"claim": entry["claim"]},
                expected_output={"expected_verdict": entry["expected_verdict"]},
                metadata={
                    "golden_id": entry["id"],
                    "category": entry["category"],
                    "target_entity": entry.get("target_entity"),
                    **{k: entry[k] for k in ("inconclusive_reason", "expected_tools") if entry.get(k) is not None},
                },
            )
        except Exception as exc:
            logger.error("Falha ao sincronizar %s: %s", item_id(entry["id"], dataset_name), exc)
            failed.append(item_id(entry["id"], dataset_name))

    if failed:
        raise DatasetSyncError(f"{len(failed)} item(ns) não sincronizado(s): {', '.join(failed)}")
    return summary

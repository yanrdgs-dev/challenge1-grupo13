"""Sincronização idempotente do golden dataset com o Langfuse (client mockado)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.evaluation.dataset import (
    DATASET_NAME,
    DatasetSyncError,
    item_id,
    load_golden_dataset,
    sync_golden_dataset,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden_dataset_v1.json"


def claim(i=1, verdict="VERDADEIRO", category="GASTOS"):
    return {"id": i, "claim": f"claim {i}", "expected_verdict": verdict, "category": category,
            "target_entity": "Câmara dos Deputados"}


# ------------------------------- carga e validação ------------------------------- #

def test_real_golden_dataset_loads_with_30_valid_claims():
    items = load_golden_dataset(GOLDEN)
    assert len(items) == 30
    assert {c["expected_verdict"] for c in items} == {"VERDADEIRO", "FALSO", "INCONCLUSIVO"}
    assert {c["category"] for c in items} == {"GASTOS", "VOTACOES"}


@pytest.mark.parametrize("broken", [
    [claim(1), claim(1)],                                   # id duplicado
    [{**claim(1), "expected_verdict": "TALVEZ"}],           # veredito inválido
    [{**claim(1), "category": "OUTRA"}],                    # categoria inválida
    [{**claim(1), "claim": "  "}],                          # claim vazia
    [{k: v for k, v in claim(1).items() if k != "id"}],     # sem id
])
def test_invalid_dataset_is_rejected(tmp_path, broken):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError):
        load_golden_dataset(path)


def test_item_id_is_deterministic_and_namespaced():
    assert item_id(7) == "golden_dataset_v1-claim-07"
    assert item_id(7) == item_id(7)
    assert item_id(30) == "golden_dataset_v1-claim-30"


# ------------------------------------ sync ------------------------------------ #

def test_sync_creates_dataset_then_upserts_every_item():
    client = MagicMock()
    items = [claim(1), claim(2, "FALSO", "VOTACOES")]

    summary = sync_golden_dataset(client, items)

    client.create_dataset.assert_called_once()
    assert client.create_dataset.call_args.kwargs["name"] == DATASET_NAME
    assert client.create_dataset_item.call_count == 2
    first = client.create_dataset_item.call_args_list[0].kwargs
    assert first["dataset_name"] == DATASET_NAME
    assert first["id"] == "golden_dataset_v1-claim-01"
    assert first["input"] == {"claim": "claim 1"}
    assert first["expected_output"] == {"expected_verdict": "VERDADEIRO"}
    assert first["metadata"] == {"golden_id": 1, "category": "GASTOS", "target_entity": "Câmara dos Deputados"}
    assert summary == {"dataset": DATASET_NAME, "items": 2}


def test_sync_is_idempotent_same_ids_on_every_run():
    items = [claim(i) for i in range(1, 6)]
    c1, c2 = MagicMock(), MagicMock()
    sync_golden_dataset(c1, items)
    sync_golden_dataset(c2, items)
    ids1 = [call.kwargs["id"] for call in c1.create_dataset_item.call_args_list]
    ids2 = [call.kwargs["id"] for call in c2.create_dataset_item.call_args_list]
    assert ids1 == ids2 and len(set(ids1)) == 5


def test_sync_attempts_all_items_and_reports_the_failed_ones():
    client = MagicMock()
    client.create_dataset_item.side_effect = [None, Exception("falha de rede"), None]
    with pytest.raises(DatasetSyncError) as exc:
        sync_golden_dataset(client, [claim(1), claim(2), claim(3)])
    assert client.create_dataset_item.call_count == 3
    assert "golden_dataset_v1-claim-02" in str(exc.value)


def test_sync_fails_loudly_when_dataset_cannot_be_created():
    client = MagicMock()
    client.create_dataset.side_effect = Exception("401")
    with pytest.raises(DatasetSyncError):
        sync_golden_dataset(client, [claim(1)])
    client.create_dataset_item.assert_not_called()


def test_dry_run_does_not_touch_the_client():
    client = MagicMock()
    summary = sync_golden_dataset(client, [claim(1), claim(2)], dry_run=True)
    assert summary == {"dataset": DATASET_NAME, "items": 2}
    client.create_dataset.assert_not_called()
    client.create_dataset_item.assert_not_called()


# ------------------------------------ CLI ------------------------------------ #

def test_cli_dry_run_validates_without_creating_a_client(capsys):
    from scripts.langfuse_sync_dataset import main

    factory = MagicMock()
    assert main(["--path", str(GOLDEN), "--dry-run"], client_factory=factory) == 0
    factory.assert_not_called()
    assert "30 itens" in capsys.readouterr().out


def test_cli_syncs_with_the_provided_client():
    from scripts.langfuse_sync_dataset import main

    client = MagicMock()
    assert main(["--path", str(GOLDEN)], client_factory=lambda: client) == 0
    assert client.create_dataset_item.call_count == 30


def test_cli_returns_error_code_on_invalid_file(tmp_path, capsys):
    from scripts.langfuse_sync_dataset import main

    bad = tmp_path / "g.json"
    bad.write_text("[]")
    assert main(["--path", str(bad), "--dry-run"]) == 1
    assert "ERRO" in capsys.readouterr().err

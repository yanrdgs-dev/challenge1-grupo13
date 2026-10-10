"""GET /api/ingestion/status: o estado da última ingestão, lido do arquivo publicado junto dos parquets."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.services.router_service import app  # o app que a imagem do router executa (ver o teste de guarda abaixo)

client = TestClient(app)


def status_payload(finished_hours_ago=1, resultado="ok"):
    finished = (datetime.now(timezone.utc) - timedelta(hours=finished_hours_ago)).isoformat(timespec="seconds")
    return {
        "gerado_em": finished,
        "ultima_execucao": {"iniciou_em": finished, "terminou_em": finished, "duracao_segundos": 60,
                            "resultado": resultado, "exit_code": 0 if resultado == "ok" else 1,
                            "fontes_com_novidade": [], "total_novidades": 0, "build": "ignorado", "falhas": []},
        "ultimo_sucesso_em": finished if resultado == "ok" else None,
        "ultima_novidade": None, "carga_pendente": False, "dados_atualizados_em": finished,
        "fontes_registradas": 82, "falhas_seguidas": 0, "historico": [],
    }


@pytest.fixture
def processed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))
    return tmp_path


def test_returns_the_published_status(processed):
    (processed / "ingestion_status.json").write_text(json.dumps(status_payload()), encoding="utf-8")
    r = client.get("/api/ingestion/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ultima_execucao"]["resultado"] == "ok" and body["fontes_registradas"] == 82


def test_adds_age_and_staleness_computed_at_request_time(processed):
    (processed / "ingestion_status.json").write_text(json.dumps(status_payload(finished_hours_ago=1)), encoding="utf-8")
    body = client.get("/api/ingestion/status").json()
    assert 0.9 < body["ultimo_sucesso_ha_horas"] < 1.2 and body["desatualizada"] is False
    (processed / "ingestion_status.json").write_text(json.dumps(status_payload(finished_hours_ago=30)), encoding="utf-8")
    body = client.get("/api/ingestion/status").json()
    assert body["desatualizada"] is True


def test_missing_status_is_a_404_with_a_clear_message(processed):
    r = client.get("/api/ingestion/status")
    assert r.status_code == 404 and "ingestão" in r.json()["detail"].lower()


def test_corrupt_status_is_a_404_not_a_500(processed):
    (processed / "ingestion_status.json").write_text("{nao", encoding="utf-8")
    assert client.get("/api/ingestion/status").status_code == 404


def test_never_succeeded_is_reported_as_stale(processed):
    (processed / "ingestion_status.json").write_text(json.dumps(status_payload(resultado="falhou")), encoding="utf-8")
    body = client.get("/api/ingestion/status").json()
    assert body["desatualizada"] is True and body["ultimo_sucesso_ha_horas"] is None


def test_route_lives_on_the_app_the_router_image_actually_runs():
    """Guarda: o primeiro deploy do endpoint 404ou porque ele estava em src.api.main, que o Docker não usa."""
    dockerfile = (Path(__file__).resolve().parents[1] / "docker" / "Dockerfile.router").read_text(encoding="utf-8")
    module, attr = re.search(r'"uvicorn",\s*"([\w.]+):(\w+)"', dockerfile).groups()
    assert (module, attr) == ("src.services.router_service", "app"), "o CMD do router mudou: ajuste este teste e o registro da rota"
    assert "/api/ingestion/status" in {getattr(r, "path", None) for r in app.routes}

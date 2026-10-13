"""Página /status do frontend: contrato com o backend, rota, link e testes de lógica no build.

Valida a estrutura dos arquivos (nada é renderizado). A lógica pura roda com `npm test` (node:test).
"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api.routes.ingestion import ingestion_status  # noqa: F401  (a rota existe)
from src.etl.ingestion_state import IngestionState
from src.etl.status import build_status

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
SRC = FRONT / "src"


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def interface_keys(source: str, name: str) -> set:
    body = re.search(rf"export interface {name} \{{(.*?)\n\}}", source, re.S).group(1)
    return set(re.findall(r"^\s{2}(\w+)\??:", body, re.M))


def backend_status():
    st = IngestionState.load(Path("/nonexistent/state.json"))
    changes = ["camara-a", "tse-b"]
    st.record_run("2026-10-10T14:00:00+00:00", "2026-10-10T14:05:00+00:00", 0, 2, True, changes=changes, deferred=0)
    status = build_status(st, datetime(2026, 10, 10, 15, tzinfo=timezone.utc))
    status.update({"ultimo_sucesso_ha_horas": 0.9, "desatualizada": False})  # acrescentados pelo endpoint
    return status


def test_typescript_interface_matches_the_keys_the_backend_returns():
    src = text(SRC / "ingestionStatus.ts")
    status = backend_status()
    assert interface_keys(src, "IngestionStatus") == set(status)
    assert interface_keys(src, "RunSummary") == set(status["ultima_execucao"])
    assert interface_keys(src, "LatestNews") == {"em", "total", "por_origem", "fontes"}
    assert interface_keys(src, "HistoryEntry") == set(status["historico"][0])


def test_page_reads_the_public_endpoint_and_handles_missing_status_and_errors():
    page = text(SRC / "StatusPage.tsx")
    assert '"/api/ingestion/status"' in page
    assert "404" in page  # ingestão ainda não publicou o status
    assert "setInterval" in page and "clearInterval" in page  # atualiza sozinha e limpa ao sair
    assert "aria-live" in page  # leitores de tela percebem a atualização


def test_page_shows_the_origin_breakdown_that_was_missing_before():
    page = text(SRC / "StatusPage.tsx")
    assert "novidades_por_origem" in page and "sortedOrigins" in page


def test_main_serves_the_status_page_on_the_status_path():
    main = text(SRC / "main.tsx")
    assert "StatusPage" in main and "/status" in main


def test_app_links_to_the_status_page():
    assert 'href="/status"' in text(SRC / "App.tsx")


def test_nginx_already_falls_back_to_index_html_so_status_needs_no_server_change():
    assert "try_files $uri /index.html" in text(ROOT / "docker" / "nginx.frontend.conf")


def test_logic_tests_run_in_the_docker_build_and_are_excluded_from_the_app_typecheck():
    assert '"test"' in text(FRONT / "package.json") and "node --test" in text(FRONT / "package.json")
    assert "npm test" in text(ROOT / "docker" / "Dockerfile.frontend")
    tsconfig = text(FRONT / "tsconfig.app.json")
    assert "exclude" in tsconfig and ".test.ts" in tsconfig


def test_logic_unit_tests_pass():
    # No CI as dependências do frontend só são instaladas dentro do build da imagem (Dockerfile.frontend roda
    # `npm test` ali); este teste cobre o ambiente local, onde `npm ci` já foi feito.
    if not (FRONT / "node_modules" / ".bin" / "tsc").exists():
        pytest.skip("dependências do frontend não instaladas (npm ci); o build da imagem roda estes testes")
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node não instalado")
    result = subprocess.run(["npm", "test", "--silent"], cwd=FRONT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-800:]

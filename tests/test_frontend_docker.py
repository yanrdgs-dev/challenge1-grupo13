"""Imagem do frontend: build estático do Vite servido por nginx, com proxy de /api para o router.

Valida a estrutura dos arquivos (nada é executado). O build real roda no CI e o smoke test confere `nginx -t`.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile.frontend"
NGINX = ROOT / "docker" / "nginx.frontend.conf"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
COMPOSE_DEV = ROOT / "docker-compose.yml"


@pytest.fixture(scope="module")
def dockerfile():
    assert DOCKERFILE.exists(), "falta docker/Dockerfile.frontend"
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nginx():
    assert NGINX.exists(), "falta docker/nginx.frontend.conf"
    return NGINX.read_text(encoding="utf-8")


def location_block(nginx_conf, path):
    match = re.search(r"location\s+" + re.escape(path) + r"\s*\{(.*?)\n\s{4}\}", nginx_conf, re.S)
    assert match, f"location {path} não encontrado"
    return match.group(1)


# ------------------------------------ Dockerfile ------------------------------------ #

def test_dockerfile_is_multi_stage_node_build_then_nginx(dockerfile):
    stages = re.findall(r"^FROM\s+(\S+)", dockerfile, re.M)
    assert len(stages) == 2
    assert stages[0].startswith("node:") and stages[1].startswith("nginx:")


def test_base_images_are_pinned_to_a_version(dockerfile):
    for image in re.findall(r"^FROM\s+(\S+)", dockerfile, re.M):
        assert ":" in image and not image.endswith(":latest"), image


def test_build_uses_the_lockfile_and_the_project_build_script(dockerfile):
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile, "o build roda `tsc -b`: erro de tipo reprova a imagem"


def test_only_the_frontend_folder_goes_into_the_build_stage(dockerfile):
    copies = re.findall(r"^COPY\s+(?!--from)(\S+)", dockerfile, re.M)
    assert copies and all(c.startswith(("frontend/", "docker/nginx")) for c in copies)


def test_final_image_carries_only_the_static_build_and_the_nginx_config(dockerfile):
    assert re.search(r"COPY --from=\S+ /app/dist /usr/share/nginx/html", dockerfile)
    assert "docker/nginx.frontend.conf" in dockerfile and "/etc/nginx/conf.d/default.conf" in dockerfile
    assert "node_modules" not in dockerfile.split("FROM nginx")[-1]


def test_image_has_a_healthcheck_through_the_proxy(dockerfile):
    assert "HEALTHCHECK" in dockerfile and "/api/health" in dockerfile


def test_dockerignore_keeps_local_node_artifacts_out_of_the_context():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "frontend/node_modules" in ignore and "frontend/dist" in ignore


# ------------------------------------ nginx ------------------------------------ #

def test_spa_falls_back_to_index_html(nginx):
    assert "try_files $uri /index.html" in location_block(nginx, "/")


def test_api_is_proxied_to_the_router_service_on_the_compose_network(nginx):
    block = location_block(nginx, "/api/")
    assert "proxy_pass $router" in block
    assert "http://router-service:8000" in nginx


def test_upstream_is_resolved_at_request_time_so_nginx_starts_without_the_router(nginx):
    assert "resolver 127.0.0.11" in nginx
    assert re.search(r"set\s+\$router\s+http://router-service:8000", nginx)


def test_sse_stream_is_never_buffered_and_may_take_minutes(nginx):
    block = location_block(nginx, "/api/check/stream")
    assert "proxy_buffering off" in block
    assert "proxy_cache off" in block
    timeout = int(re.search(r"proxy_read_timeout\s+(\d+)s", block).group(1))
    assert timeout >= 300, "o Ollama local leva dezenas de segundos por checagem"
    assert 'proxy_set_header Connection ""' in block and "proxy_http_version 1.1" in block


def test_expensive_endpoints_are_rate_limited_per_client(nginx):
    """Cada checagem ocupa o Ollama local por ~40 s: sem limite, um cliente derruba o serviço para todos."""
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=checks:\d+m\s+rate=\d+r/m", nginx)
    for path in ("/api/check/stream", "/api/check"):
        assert "limit_req zone=checks" in location_block(nginx, path)
    assert "limit_req_status 429" in nginx


def test_request_bodies_are_capped(nginx):
    assert re.search(r"client_max_body_size\s+\d+k", nginx)


def test_basic_security_headers_and_no_version_leak(nginx):
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert header in nginx
    assert "server_tokens off" in nginx


def test_hashed_assets_are_cached_but_the_html_shell_is_not(nginx):
    assert "immutable" in location_block(nginx, "/assets/")
    assert "no-cache" in location_block(nginx, "/")


# ------------------------------------ compose de produção e local ------------------------------------ #

@pytest.fixture(scope="module")
def prod():
    return yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))


def test_prod_runs_the_frontend_image_of_the_deployed_commit(prod):
    image = prod["services"]["frontend"]["image"]
    assert image.startswith("ghcr.io/${GHCR_OWNER:?") and "factcheck-frontend" in image
    assert ":${IMAGE_TAG:?" in image


def test_only_the_proxy_is_published_frontend_router_and_judge_stay_internal(prod):
    assert "ports" not in prod["services"]["frontend"], "quem publica 80/443 é o Caddy (tests/test_https_domain.py)"
    assert "ports" not in prod["services"]["router-service"]
    assert "ports" not in prod["services"]["judge-service"]


def test_frontend_starts_after_a_healthy_router(prod):
    assert prod["services"]["frontend"]["depends_on"]["router-service"]["condition"] == "service_healthy"
    assert prod["services"]["frontend"]["restart"] == "unless-stopped"
    assert "healthcheck" in prod["services"]["frontend"]


def test_dev_compose_also_builds_the_frontend():
    dev = yaml.safe_load(COMPOSE_DEV.read_text(encoding="utf-8"))
    frontend = dev["services"]["frontend"]
    assert frontend["build"]["dockerfile"] == "docker/Dockerfile.frontend"
    assert "router-service" in frontend["depends_on"]

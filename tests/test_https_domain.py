"""HTTPS do domínio polis.software: Caddy na frente do nginx do frontend, na VM do Azure.

Valida a estrutura dos arquivos (nada é executado). O certificado em si só pode ser emitido com o DNS
apontando para a VM, então isso é conferido no deploy (docs/ci_cd.md).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
CADDYFILE = ROOT / "deploy" / "Caddyfile.site"
NGINX = ROOT / "docker" / "nginx.frontend.conf"
CD = ROOT / ".github" / "workflows" / "cd.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DOMAIN = "polis.software"


@pytest.fixture(scope="module")
def prod():
    return yaml.safe_load(COMPOSE_PROD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def caddyfile():
    assert CADDYFILE.exists(), "falta deploy/Caddyfile.site"
    return CADDYFILE.read_text(encoding="utf-8")


def site_block(caddyfile, address):
    match = re.search(r"^" + re.escape(address) + r"\s*\{(.*?)^\}", caddyfile, re.S | re.M)
    assert match, f"bloco do site {address} não encontrado"
    return match.group(1)


# ------------------------------------ compose ------------------------------------ #

def test_caddy_is_the_only_service_published_and_serves_http_and_https(prod):
    assert sorted(prod["services"]["caddy"]["ports"]) == ["443:443", "80:80"]
    for name in ("frontend", "router-service", "judge-service"):
        assert "ports" not in prod["services"][name], f"{name} só pode ser alcançado pela rede do compose"


def test_caddy_image_is_pinned_to_a_version(prod):
    image = prod["services"]["caddy"]["image"]
    assert image.startswith("caddy:") and not image.endswith((":latest", ":2")) and ":" in image


def test_caddy_waits_for_a_healthy_frontend_and_restarts(prod):
    caddy = prod["services"]["caddy"]
    assert caddy["depends_on"]["frontend"]["condition"] == "service_healthy"
    assert caddy["restart"] == "unless-stopped"
    assert "healthcheck" in caddy
    assert "env_file" not in caddy, "o Caddy não precisa de nenhum segredo"


def test_certificates_survive_container_recreation(prod):
    """Sem volume em /data, cada deploy pediria um certificado novo e estouraria o limite do Let's Encrypt."""
    volumes = prod["services"]["caddy"]["volumes"]
    assert any(v.endswith(":/data") for v in volumes)
    assert "caddy_data" in prod["volumes"]


def test_caddyfile_is_mounted_read_only_from_the_vm_deploy_folder(prod):
    mounts = [v for v in prod["services"]["caddy"]["volumes"] if v.endswith(":/etc/caddy/Caddyfile:ro")]
    assert mounts and mounts[0].startswith("/srv/factcheck/"), "caminho absoluto da VM, não relativo ao checkout"


# ------------------------------------ Caddyfile ------------------------------------ #

def test_apex_domain_is_proxied_to_the_frontend_and_gets_automatic_https(caddyfile):
    block = site_block(caddyfile, DOMAIN)
    assert "reverse_proxy frontend:80" in block
    assert "auto_https off" not in caddyfile


def test_www_redirects_permanently_to_the_apex_domain(caddyfile):
    block = site_block(caddyfile, f"www.{DOMAIN}")
    assert re.search(rf"redir\s+https://{re.escape(DOMAIN)}\{{uri\}}\s+permanent", block)


def test_sse_stream_is_not_buffered_by_the_proxy(caddyfile):
    assert "flush_interval -1" in site_block(caddyfile, DOMAIN)


def test_local_health_check_host_is_served_over_plain_http_without_redirect(caddyfile):
    """O health check do CD bate em http://localhost/api/health, sem certificado e sem 308 para https."""
    block = site_block(caddyfile, "http://localhost")
    assert "reverse_proxy frontend:80" in block


def test_caddyfile_does_not_trust_a_client_supplied_forwarded_for(caddyfile):
    assert "trusted_proxies" not in caddyfile


# ------------------------------------ nginx atrás do Caddy ------------------------------------ #

def test_nginx_rate_limits_by_real_client_ip_not_by_the_proxy_ip():
    """Atrás do Caddy, $remote_addr seria sempre o do proxy: todos os usuários dividiriam um único limite."""
    nginx = NGINX.read_text(encoding="utf-8")
    assert re.search(r"set_real_ip_from\s+172\.28\.0\.0/24", nginx), "só a rede do compose é confiável"
    assert "real_ip_header X-Forwarded-For" in nginx
    assert "set_real_ip_from 0.0.0.0/0" not in nginx


# ------------------------------------ CD e CI ------------------------------------ #

def test_cd_sends_the_caddyfile_to_the_vm_before_starting_the_stack():
    text = CD.read_text(encoding="utf-8")
    assert "deploy/Caddyfile.site" in text and "/srv/factcheck/Caddyfile.site" in text
    assert text.index("Caddyfile.site") < text.index("compose up -d")


def test_ci_validates_the_caddyfile_syntax():
    text = CI.read_text(encoding="utf-8")
    assert re.search(r"caddy\s+validate", text) and "deploy/Caddyfile.site" in text

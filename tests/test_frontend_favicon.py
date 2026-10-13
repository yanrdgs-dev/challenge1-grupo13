"""Ícone da aba do navegador: o mesmo símbolo (templo) que a sidebar mostra ao lado de "Pólis".

Valida a estrutura dos arquivos (nada é executado nem renderizado).
"""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
INDEX = FRONTEND / "index.html"
FAVICON = FRONTEND / "public" / "favicon.svg"
APP = FRONTEND / "src" / "App.tsx"


@pytest.fixture(scope="module")
def favicon():
    assert FAVICON.exists(), "falta frontend/public/favicon.svg"
    return FAVICON.read_text(encoding="utf-8")


def logo_paths():
    """Os `d` dos paths do PolisLogo da sidebar: a fonte única do símbolo."""
    source = APP.read_text(encoding="utf-8")
    body = re.search(r"function PolisLogo\(.*?\n}\n", source, re.S).group(0)
    return re.findall(r'\bd="([^"]+)"', body)


def test_index_links_the_svg_favicon():
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r'<link[^>]+rel="icon"[^>]+href="/favicon\.svg"', html)
    assert 'type="image/svg+xml"' in html


def test_favicon_draws_exactly_the_sidebar_logo(favicon):
    paths = logo_paths()
    assert len(paths) == 3
    for d in paths:
        assert f'd="{d}"' in favicon, f"falta o path do PolisLogo: {d}"


def test_favicon_uses_the_sidebar_colors_white_symbol_on_emerald(favicon):
    assert "#047857" in favicon.lower(), "fundo emerald-700, como o selo da sidebar"
    assert re.search(r'stroke="(#fff|#ffffff|white)"', favicon, re.I)


def test_favicon_is_a_self_contained_svg(favicon):
    assert favicon.lstrip().startswith("<svg") and "viewBox" in favicon
    assert not re.search(r"<script|<image|href=", favicon), "sem script nem recurso externo"
    assert "currentColor" not in favicon, "na aba não há CSS herdado: a cor precisa ser explícita"


def test_vite_default_logo_is_gone(favicon):
    assert "#863bff" not in favicon.lower()

"""Arquitetura: o código de produção (src/) nunca depende de scripts/.

As imagens Docker só levam o que o serviço precisa. O judge copia apenas `src/`, então qualquer
`from scripts...` dentro de `src/` derruba o container na subida (ModuleNotFoundError), coisa que os
testes locais não pegam porque rodam a partir da raiz do repositório.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports_from_scripts(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "scripts":
            yield node.lineno, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "scripts":
                    yield node.lineno, alias.name


def test_src_never_imports_from_scripts():
    offenders = [
        f"{path.relative_to(ROOT)}:{line} importa {module}"
        for path in sorted((ROOT / "src").rglob("*.py"))
        for line, module in _imports_from_scripts(path)
    ]
    assert not offenders, "src/ depende de scripts/ (a imagem não o contém):\n" + "\n".join(offenders)


def test_tool_catalog_and_router_prompt_live_in_src():
    from src.services import tool_catalog

    assert isinstance(tool_catalog.TOOLS_CATALOG, list) and tool_catalog.TOOLS_CATALOG
    assert isinstance(tool_catalog.ROUTER_SYSTEM_PROMPT, str) and tool_catalog.ROUTER_SYSTEM_PROMPT


def test_demo_script_reuses_the_same_objects_from_src():
    """O demo e os testes antigos importam de scripts: precisam enxergar exatamente os mesmos objetos."""
    from scripts import demo_qwen_tool_routing as demo
    from src.services import tool_catalog

    assert demo.TOOLS_CATALOG is tool_catalog.TOOLS_CATALOG
    assert demo.ROUTER_SYSTEM_PROMPT is tool_catalog.ROUTER_SYSTEM_PROMPT

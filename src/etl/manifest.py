"""Manifesto declarativo das fontes de dados públicas (Câmara, Senado e regras do TSE).

O manifesto é versionado junto do código: trocar uma URL ou incluir um ano é uma mudança de dados
revisável, não de lógica. Veja `datasets_manifest.json`.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

MANIFEST_PATH = Path(__file__).with_name("datasets_manifest.json")
SUPPORTED_VERSION = 1
KINDS = ("file", "zip_csv")
REFRESH_MODES = ("validators", "always")


class ManifestError(ValueError):
    """Manifesto ausente, ilegível ou inválido."""


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    url: str
    dest: str  # relativo ao diretório de datasets; arquivo (file) ou diretório (zip_csv)
    desc: str
    prefix: Optional[str]  # zip_csv: prefixo do CSV extraído, usado para saber se já foi baixado
    sha256: Optional[str]
    refresh: str
    ano: Optional[int]


@dataclass(frozen=True)
class TseRule:
    package: str
    pattern: str  # regex do nome do zip sem extensão; {a} vira o ano
    dest: str  # {a} vira o ano


@dataclass(frozen=True)
class TseConfig:
    packages: Dict[int, Dict[str, str]]
    rules: List[TseRule]
    pending_ok: Dict[int, Set[str]]


def load_manifest(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    path = Path(path) if path else MANIFEST_PATH
    if not path.exists():
        raise ManifestError(f"manifesto não encontrado: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifesto {path} não é JSON válido: {e}") from e
    validate_manifest(manifest)
    return manifest


def _fail(source_id: Any, message: str) -> None:
    raise ManifestError(f"fonte '{source_id}': {message}")


def _validate_source(src: Dict[str, Any]) -> None:
    sid = src.get("id")
    if not sid or not isinstance(sid, str):
        raise ManifestError("fonte sem id")
    if src.get("kind") not in KINDS:
        _fail(sid, f"kind inválido {src.get('kind')!r} (esperado: {', '.join(KINDS)})")
    for key in ("url", "dest"):
        if not src.get(key):
            _fail(sid, f"campo obrigatório ausente: {key}")
    if not src["url"].startswith("https://"):
        _fail(sid, "url precisa ser https://")
    dest = src["dest"]
    if dest.startswith("/") or ".." in Path(dest).parts:
        _fail(sid, f"dest precisa ser relativo e sem '..': {dest}")
    if src["kind"] == "zip_csv" and not src.get("prefix"):
        _fail(sid, "zip_csv exige prefix")
    anos = src.get("anos")
    placeholders = any("{ano}" in str(src.get(k, "")) for k in ("url", "dest", "prefix"))
    if anos is not None:
        if not isinstance(anos, list) or not anos or not all(isinstance(a, int) for a in anos):
            _fail(sid, "anos precisa ser uma lista não vazia de inteiros")
        if not placeholders:
            _fail(sid, "tem anos mas nenhum campo usa {ano}")
    elif placeholders:
        _fail(sid, "usa {ano} mas não define anos")
    if src.get("sha256") is not None and not re.fullmatch(r"[0-9a-f]{64}", str(src["sha256"])):
        _fail(sid, "sha256 precisa ter 64 caracteres hexadecimais minúsculos")
    if src.get("refresh", "validators") not in REFRESH_MODES:
        _fail(sid, f"refresh inválido {src.get('refresh')!r} (esperado: {', '.join(REFRESH_MODES)})")


def validate_manifest(manifest: Dict[str, Any]) -> None:
    if manifest.get("version") != SUPPORTED_VERSION:
        raise ManifestError(f"version {manifest.get('version')!r} não suportada (esperado {SUPPORTED_VERSION})")
    for src in manifest.get("sources", []):
        _validate_source(src)
    ids = [s for src in manifest.get("sources", []) for s in [src["id"]]]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ManifestError(f"ids duplicados no manifesto: {', '.join(duplicated)}")
    _validate_tse(manifest.get("tse", {}))


def _validate_tse(tse: Dict[str, Any]) -> None:
    packages = tse.get("packages", {})
    known = {pkg for year in packages.values() for pkg in year}
    for rule in tse.get("rules", []):
        for key in ("package", "pattern", "dest"):
            if not rule.get(key):
                raise ManifestError(f"regra TSE sem campo {key}: {rule}")
        if rule["package"] not in known:
            raise ManifestError(f"regra TSE usa pacote '{rule['package']}' que nenhum ano define")
        try:
            re.compile(rule["pattern"].replace("{a}", "2000"))
        except re.error as e:
            raise ManifestError(f"regra TSE com regex inválida {rule['pattern']!r}: {e}") from e
        if rule["dest"].startswith("/") or ".." in Path(rule["dest"]).parts:
            raise ManifestError(f"regra TSE com dest inválido: {rule['dest']}")


def _fmt(value: Optional[str], ano: Optional[int]) -> Optional[str]:
    return None if value is None else value.replace("{ano}", str(ano))


def expand_sources(manifest: Dict[str, Any]) -> List[Source]:
    """Expande {ano} e devolve uma Source por arquivo (ou zip) a baixar."""
    validate_manifest(manifest)
    out: List[Source] = []
    for src in manifest.get("sources", []):
        for ano in src.get("anos") or [None]:
            out.append(Source(
                id=src["id"] if ano is None else f"{src['id']}-{ano}",
                kind=src["kind"],
                url=_fmt(src["url"], ano),
                dest=_fmt(src["dest"], ano),
                desc=_fmt(src.get("desc", src["id"]), ano),
                prefix=_fmt(src.get("prefix"), ano),
                sha256=src.get("sha256"),
                refresh=src.get("refresh", "validators"),
                ano=ano,
            ))
    return out


def tse_config(manifest: Dict[str, Any]) -> TseConfig:
    tse = manifest.get("tse", {})
    return TseConfig(
        packages={int(year): dict(pkgs) for year, pkgs in tse.get("packages", {}).items()},
        rules=[TseRule(r["package"], r["pattern"], r["dest"]) for r in tse.get("rules", [])],
        pending_ok={int(year): set(pkgs) for year, pkgs in tse.get("pending_ok", {}).items()},
    )

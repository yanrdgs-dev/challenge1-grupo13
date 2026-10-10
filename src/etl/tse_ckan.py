"""Download dos dados do TSE via API CKAN (`dadosabertos.tse.jus.br`).

As URLs dos recursos vêm do `package_show` do CKAN, nunca de padrões adivinhados. Cada recurso
escolhido é extraído no diretório que `build_parquet.process_all_datasets` lê.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import httpx

from src.etl.download_datasets import DownloadError, download_zip_csv, local_zip_state, make_client
from src.etl.freshness import HostBreaker
from src.etl.ingestion_state import IngestionState
from src.etl.manifest import load_manifest, tse_config
from src.etl.sync import sync_item

logger = logging.getLogger("ETL.TSE")

CKAN_PACKAGE_SHOW = "https://dadosabertos.tse.jus.br/api/3/action/package_show"

@dataclass(frozen=True)
class TseDownload:
    url: str
    stem: str
    dest_dir: Path
    desc: str


def fetch_resources(package_id: str, client: Optional[httpx.Client] = None) -> List[dict]:
    """Lista os recursos (`name`, `url`, ...) de um pacote CKAN do TSE."""
    own_client = client is None
    client = client or make_client()
    try:
        resp = client.get(CKAN_PACKAGE_SHOW, params={"id": package_id})
    except httpx.TimeoutException as e:
        raise DownloadError(f"CKAN {package_id}: timeout: {e}") from e
    except httpx.HTTPError as e:
        raise DownloadError(f"CKAN {package_id}: erro de rede: {e}") from e
    finally:
        if own_client:
            client.close()

    if resp.status_code >= 400:
        if resp.status_code == 404:
            raise DownloadError(f"CKAN {package_id}: pacote inexistente (HTTP 404)")
        raise DownloadError(f"CKAN {package_id}: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise DownloadError(f"CKAN {package_id}: resposta não é JSON válido") from e
    if not payload.get("success"):
        raise DownloadError(f"CKAN {package_id}: pacote inexistente ou erro da API")
    return payload["result"]["resources"]


def plan_tse_downloads(
    ano: int, datasets_dir: Path, client: Optional[httpx.Client] = None, manifest: Optional[dict] = None
) -> List[TseDownload]:
    """Escolhe, nos pacotes do CKAN, os zips que o ETL usa. Recurso esperado que sumiu é erro.

    Pacotes, regras e recursos ainda não publicados vêm da seção `tse` do manifesto.
    """
    cfg = tse_config(manifest if manifest is not None else load_manifest())
    if ano not in cfg.packages:
        raise ValueError(f"Ano {ano} sem layout TSE conhecido (suportados: {sorted(cfg.packages)})")
    datasets_dir = Path(datasets_dir)

    resources: Dict[str, List[dict]] = {}
    for key, package_id in cfg.packages[ano].items():
        resources[key] = fetch_resources(package_id, client=client)

    plan: List[TseDownload] = []
    for rule in cfg.rules:
        package, pattern, subdir = rule.package, rule.pattern.replace("{a}", str(ano)), rule.dest.replace("{a}", str(ano))
        if package not in resources:
            continue
        regex = re.compile(pattern)
        matched = []
        for r in resources[package]:
            url = r.get("url", "")
            stem = url.rsplit("/", 1)[-1].removesuffix(".zip")
            if url.endswith(".zip") and regex.fullmatch(stem):
                matched.append(TseDownload(
                    url=url, stem=stem, dest_dir=datasets_dir / subdir,
                    desc=f"TSE {stem}",
                ))
        if not matched and package in cfg.pending_ok.get(ano, set()):
            logger.warning(
                "TSE %s: '%s' ainda não publicado no CKAN (%s); segue sem esse recurso",
                ano, pattern, cfg.packages[ano][package],
            )
            continue
        if not matched:
            raise DownloadError(f"CKAN {cfg.packages[ano][package]}: nenhum recurso para '{pattern}'")
        plan.extend(matched)
    return plan


def run_tse_downloads(
    datasets_dir: Path, anos: Sequence[int], client: Optional[httpx.Client] = None,
    manifest: Optional[dict] = None, state: Optional[IngestionState] = None,
    force: bool = False, dry_run: bool = False, changes: Optional[List[str]] = None,
) -> List[DownloadError]:
    """Baixa e extrai os zips do TSE. Falhas são devolvidas e não interrompem os demais.

    Com `state`, só baixa o que tem novidade (ETag/Last-Modified do CDN) e acrescenta a `changes` o id
    `tse-<nome do zip>` de cada recurso atualizado (ou que seria, em `dry_run`).
    """
    own_client = client is None
    client = client or make_client()
    failures: List[DownloadError] = []
    breaker = HostBreaker()
    try:
        for ano in anos:
            try:
                plan = plan_tse_downloads(ano, datasets_dir, client=client, manifest=manifest)
            except DownloadError as e:
                logger.error("%s", e)
                failures.append(e)
                continue
            for item in plan:
                try:
                    if state is None:
                        download_zip_csv(item.url, item.dest_dir, item.stem, item.desc, client=client)
                        continue
                    exists, mtime, size = local_zip_state(item.dest_dir, item.stem)
                    outcome = sync_item(
                        f"tse-{item.stem}", item.url, refresh="validators", state=state, client=client,
                        local_exists=exists, local_mtime=mtime, local_size=size,
                        download=lambda force_, i=item: download_zip_csv(
                            i.url, i.dest_dir, i.stem, i.desc, client=client, force=force_),
                        force=force, dry_run=dry_run, breaker=breaker,
                        dest=item.dest_dir.relative_to(datasets_dir).as_posix(),
                    )
                    if changes is not None and outcome.action != "sem_novidade":
                        changes.append(f"tse-{item.stem}")
                except DownloadError as e:
                    logger.error("%s", e)
                    failures.append(e)
    finally:
        if own_client:
            client.close()
    return failures

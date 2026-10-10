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

from src.etl.download_datasets import DownloadError, download_zip_csv, make_client

logger = logging.getLogger("ETL.TSE")

CKAN_PACKAGE_SHOW = "https://dadosabertos.tse.jus.br/api/3/action/package_show"

# Pacotes CKAN por ano. O de prestação de contas de 2022 tem um id fora do padrão no portal.
PACKAGES: Dict[int, Dict[str, str]] = {
    2022: {
        "candidatos": "candidatos-2022",
        "prestacao": "dadosabertos-tse-jus-br-dataset-prestacao-de-contas-eleitorais-2022",
        "resultados": "resultados-2022",
    },
    2026: {
        "candidatos": "candidatos-2026",
        "prestacao": "prestacao-de-contas-eleitorais-2026",
        "resultados": "resultados-2026",
    },
}

# Pacotes cujos recursos ainda podem não ter sido publicados: logo após o 1º turno de 2026 o TSE só tinha
# relatórios em PDF em `resultados-2026`. Recurso ausente aí é aviso ("ainda não publicado"), não falha.
# Para anos já encerrados (2022) a ausência continua sendo erro.
PENDING_OK: Dict[int, set] = {2026: {"resultados"}}

# (pacote, regex do nome do zip sem extensão, subdiretório de destino). `{a}` vira o ano.
# Em 2022 as redes sociais vêm por UF; em 2026, em um zip único.
RULES = [
    ("candidatos", r"consulta_cand_{a}", "tse/candidatos"),
    ("candidatos", r"consulta_cand_complementar_{a}", "tse/candidatos"),
    ("candidatos", r"bem_candidato_{a}", "tse/bens"),
    ("candidatos", r"consulta_coligacao_{a}", "tse/coligacoes"),
    ("candidatos", r"motivo_cassacao_{a}", "tse/cassacao"),
    ("candidatos", r"rede_social_candidato_{a}(_[A-Z]{{2}})?", "tse/redes_sociais"),
    ("prestacao", r"prestacao_de_contas_eleitorais_candidatos_{a}", "tse/prestacao_contas"),
    ("resultados", r"Historico_Totalizacao_Presidente_BR_[12]T_{a}", "tse/votacao/totalizacao"),
    ("resultados", r"votacao_candidato_munzona_{a}", "tse/votacao/munzona/votacao_candidato_munzona_{a}"),
    ("resultados", r"detalhe_votacao_secao_{a}", "tse/votacao/secao/detalhe_votacao_secao_{a}"),
]


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
    ano: int, datasets_dir: Path, client: Optional[httpx.Client] = None
) -> List[TseDownload]:
    """Escolhe, nos pacotes do CKAN, os zips que o ETL usa. Recurso esperado que sumiu é erro."""
    if ano not in PACKAGES:
        raise ValueError(f"Ano {ano} sem layout TSE conhecido (suportados: {sorted(PACKAGES)})")
    datasets_dir = Path(datasets_dir)

    resources: Dict[str, List[dict]] = {}
    for key, package_id in PACKAGES[ano].items():
        resources[key] = fetch_resources(package_id, client=client)

    plan: List[TseDownload] = []
    for package, pattern, subdir in RULES:
        regex = re.compile(pattern.format(a=ano))
        matched = []
        for r in resources[package]:
            url = r.get("url", "")
            stem = url.rsplit("/", 1)[-1].removesuffix(".zip")
            if url.endswith(".zip") and regex.fullmatch(stem):
                matched.append(TseDownload(
                    url=url, stem=stem, dest_dir=datasets_dir / subdir.format(a=ano),
                    desc=f"TSE {stem}",
                ))
        if not matched and package in PENDING_OK.get(ano, set()):
            logger.warning(
                "TSE %s: '%s' ainda não publicado no CKAN (%s); segue sem esse recurso",
                ano, pattern.format(a=ano), PACKAGES[ano][package],
            )
            continue
        if not matched:
            raise DownloadError(
                f"CKAN {PACKAGES[ano][package]}: nenhum recurso para '{pattern.format(a=ano)}'"
            )
        plan.extend(matched)
    return plan


def run_tse_downloads(
    datasets_dir: Path, anos: Sequence[int], client: Optional[httpx.Client] = None
) -> List[DownloadError]:
    """Baixa e extrai os zips do TSE. Falhas são devolvidas e não interrompem os demais."""
    own_client = client is None
    client = client or make_client(timeout=120.0)
    failures: List[DownloadError] = []
    try:
        for ano in anos:
            try:
                plan = plan_tse_downloads(ano, datasets_dir, client=client)
            except DownloadError as e:
                logger.error("%s", e)
                failures.append(e)
                continue
            for item in plan:
                try:
                    download_zip_csv(item.url, item.dest_dir, item.stem, item.desc, client=client)
                except DownloadError as e:
                    logger.error("%s", e)
                    failures.append(e)
    finally:
        if own_client:
            client.close()
    return failures

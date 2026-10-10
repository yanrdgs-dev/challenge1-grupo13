"""Cliente CKAN do TSE: lista os recursos reais de cada pacote e escolhe os zips que o ETL espera.

Rede sempre mockada (httpx.MockTransport); nenhum dado do TSE é baixado de verdade.
"""

import io
import zipfile
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.etl.download_datasets import DownloadError
from src.etl.tse_ckan import (
    fetch_resources,
    plan_tse_downloads,
    run_tse_downloads,
)

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
PRESTACAO_PKG = "dadosabertos-tse-jus-br-dataset-prestacao-de-contas-eleitorais-2022"
UFS = ["AC", "SP", "BR"]


def res(name, url):
    return {"name": name, "format": "CSV", "url": url}


PACKAGES = {
    "candidatos-2022": [
        res("Candidatos", f"{CDN}/consulta_cand/consulta_cand_2022.zip"),
        res("Candidatos - Informações complementares",
            f"{CDN}/consulta_cand_complementar/consulta_cand_complementar_2022.zip"),
        res("Bens de candidatos", f"{CDN}/bem_candidato/bem_candidato_2022.zip"),
        res("Coligações", f"{CDN}/consulta_coligacao/consulta_coligacao_2022.zip"),
        res("Vagas", f"{CDN}/consulta_vagas/consulta_vagas_2022.zip"),
        res("Motivo da Cassação", f"{CDN}/motivo_cassacao/motivo_cassacao_2022.zip"),
        *[res(f"{uf} - Redes sociais de candidatos", f"{CDN}/consulta_cand/rede_social_candidato_2022_{uf}.zip")
          for uf in UFS],
        res("AC - Fotos de candidatos",
            "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/fotos/foto_cand2022_AC_div.zip"),
    ],
    PRESTACAO_PKG: [
        res("Prestação de contas de órgãos partidários",
            f"{CDN}/prestacao_contas/prestacao_de_contas_eleitorais_orgaos_partidarios_2022.zip"),
        res("Prestação de contas de candidatos",
            f"{CDN}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.zip"),
        res("CNPJ – Campanha", f"{CDN}/prestacao_contas/CNPJ_campanha_2022.zip"),
    ],
    "resultados-2022": [
        res("BR - Histórico totalização Presidente 1º Turno - 2022",
            "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/Historico_Totalizacao_Presidente_BR_1T_2022.zip"),
        res("BR - Histórico totalização Presidente 2º Turno - 2022",
            "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/Historico_Totalizacao_Presidente_BR_2T_2022.zip"),
        res("Votação nominal por município e zona",
            f"{CDN}/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"),
        res("Votação em partido por município e zona",
            f"{CDN}/votacao_partido_munzona/votacao_partido_munzona_2022.zip"),
        res("Detalhe da apuração por seção eleitoral",
            f"{CDN}/detalhe_votacao_secao/detalhe_votacao_secao_2022.zip"),
        res("SP - Votação por seção eleitoral - 2022", f"{CDN}/votacao_secao/votacao_secao_2022_SP.zip"),
    ],
}

PRESTACAO_PKG_2026 = "prestacao-de-contas-eleitorais-2026"
PACKAGES.update({
    "candidatos-2026": [
        res("Candidatos", f"{CDN}/consulta_cand/consulta_cand_2026.zip"),
        res("Candidatos - Informações complementares",
            f"{CDN}/consulta_cand_complementar/consulta_cand_complementar_2026.zip"),
        res("Bens de candidatos", f"{CDN}/bem_candidato/bem_candidato_2026.zip"),
        res("Coligações", f"{CDN}/consulta_coligacao/consulta_coligacao_2026.zip"),
        res("Vagas", f"{CDN}/consulta_vagas/consulta_vagas_2026.zip"),
        res("Motivo da Cassação", f"{CDN}/motivo_cassacao/motivo_cassacao_2026.zip"),
        res("Redes sociais de candidatos", f"{CDN}/consulta_cand/rede_social_candidato_2026.zip"),
        res("Histórico de candidaturas", f"{CDN}/historico_candidatura/historico_candidatura_2026.zip"),
        res("AC - Proposta de governo", f"{CDN}/proposta_governo/proposta_governo_2026_AC.zip"),
    ],
    PRESTACAO_PKG_2026: [
        res("Prestação de contas de órgãos partidários",
            f"{CDN}/prestacao_contas/prestacao_de_contas_eleitorais_orgaos_partidarios_2026.zip"),
        res("Prestação de contas de candidatos",
            f"{CDN}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip"),
    ],
    # logo após o 1º turno o TSE só publicou relatórios em PDF; os CSVs de votos ainda não existem
    "resultados-2026": [
        {"name": "BR - Relatório de Totalização - 2026", "format": "PDF",
         "url": f"{CDN}/relatorio_resultado_totalizacao/Relatorio_Resultado_Totalizacao_2026_BR.zip"},
    ],
})

CSV = b"a;b\n" + b"1;2\n" * 400


def zip_bytes(csv_name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, CSV)
    return buf.getvalue()


def make_handler(packages=None, hits=None, fail_urls=(), inner=None):
    inner = inner or (lambda stem: f"{stem}.csv")
    packages = PACKAGES if packages is None else packages

    def handler(request: httpx.Request) -> httpx.Response:
        if hits is not None:
            hits.append(str(request.url))
        url = request.url
        if url.host == "dadosabertos.tse.jus.br":
            pkg = parse_qs(urlparse(str(url)).query)["id"][0]
            if pkg not in packages:
                return httpx.Response(404, json={"success": False, "error": {"message": "Não encontrado"}})
            return httpx.Response(200, json={"success": True, "result": {"id": pkg, "resources": packages[pkg]}})
        if str(url) in fail_urls:
            return httpx.Response(500)
        stem = url.path.rsplit("/", 1)[-1].removesuffix(".zip")
        return httpx.Response(200, content=zip_bytes(inner(stem)))

    return handler


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------- fetch_resources ------------------------------- #

def test_fetch_resources_returns_name_and_url():
    with client_for(make_handler()) as client:
        resources = fetch_resources("candidatos-2022", client=client)
    assert {"name": "Candidatos", "url": f"{CDN}/consulta_cand/consulta_cand_2022.zip"} in [
        {"name": r["name"], "url": r["url"]} for r in resources
    ]


def test_fetch_resources_unknown_package_is_explicit_error():
    with client_for(make_handler()) as client, pytest.raises(DownloadError, match="inexistente"):
        fetch_resources("inexistente", client=client)


def test_fetch_resources_timeout_is_explicit_error():
    def handler(request):
        raise httpx.ReadTimeout("timeout")

    with client_for(handler) as client, pytest.raises(DownloadError, match="candidatos-2022"):
        fetch_resources("candidatos-2022", client=client)


def test_fetch_resources_network_error_is_explicit_error():
    def handler(request):
        raise httpx.ConnectError("sem rota")

    with client_for(handler) as client, pytest.raises(DownloadError):
        fetch_resources("candidatos-2022", client=client)


def test_fetch_resources_http_error_is_explicit_error():
    with client_for(lambda r: httpx.Response(503)) as client, pytest.raises(DownloadError, match="503"):
        fetch_resources("candidatos-2022", client=client)


def test_fetch_resources_invalid_json_is_explicit_error():
    with client_for(lambda r: httpx.Response(200, content=b"<html>manutencao</html>")) as client, pytest.raises(
        DownloadError, match="JSON"
    ):
        fetch_resources("candidatos-2022", client=client)


# ------------------------------- plan_tse_downloads ------------------------------- #

def dests(plan):
    return {(p.url.rsplit("/", 1)[-1], p.dest_dir.as_posix()) for p in plan}


def test_plan_maps_each_resource_to_the_directory_the_etl_reads(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2022, tmp_path, client=client)
    got = dests(plan)
    t = tmp_path.as_posix()
    assert ("consulta_cand_2022.zip", f"{t}/tse/candidatos") in got
    assert ("consulta_cand_complementar_2022.zip", f"{t}/tse/candidatos") in got
    assert ("bem_candidato_2022.zip", f"{t}/tse/bens") in got
    assert ("consulta_coligacao_2022.zip", f"{t}/tse/coligacoes") in got
    assert ("motivo_cassacao_2022.zip", f"{t}/tse/cassacao") in got
    assert ("prestacao_de_contas_eleitorais_candidatos_2022.zip", f"{t}/tse/prestacao_contas") in got
    assert ("Historico_Totalizacao_Presidente_BR_1T_2022.zip", f"{t}/tse/votacao/totalizacao") in got
    assert ("Historico_Totalizacao_Presidente_BR_2T_2022.zip", f"{t}/tse/votacao/totalizacao") in got
    assert ("votacao_candidato_munzona_2022.zip",
            f"{t}/tse/votacao/munzona/votacao_candidato_munzona_2022") in got
    assert ("detalhe_votacao_secao_2022.zip", f"{t}/tse/votacao/secao/detalhe_votacao_secao_2022") in got


def test_plan_takes_social_networks_urls_from_ckan_for_every_uf(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2022, tmp_path, client=client)
    redes = {p.url for p in plan if p.dest_dir == tmp_path / "tse" / "redes_sociais"}
    assert redes == {f"{CDN}/consulta_cand/rede_social_candidato_2022_{uf}.zip" for uf in UFS}


def test_plan_ignores_resources_the_etl_does_not_use(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2022, tmp_path, client=client)
    urls = " ".join(p.url for p in plan)
    for ignored in ("foto_cand", "consulta_vagas", "orgaos_partidarios", "CNPJ_campanha",
                    "votacao_partido_munzona", "votacao_secao_2022_SP"):
        assert ignored not in urls


def test_plan_does_not_confuse_cand_with_cand_complementar(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2022, tmp_path, client=client)
    stems = [p.stem for p in plan]
    assert stems.count("consulta_cand_2022") == 1
    assert stems.count("consulta_cand_complementar_2022") == 1


def test_plan_fails_explicitly_when_expected_resource_disappeared_from_ckan(tmp_path):
    packages = {k: list(v) for k, v in PACKAGES.items()}
    packages["candidatos-2022"] = [r for r in packages["candidatos-2022"] if "bem_candidato" not in r["url"]]
    with client_for(make_handler(packages)) as client, pytest.raises(DownloadError, match="bem_candidato"):
        plan_tse_downloads(2022, tmp_path, client=client)


def test_plan_fails_explicitly_when_package_is_missing(tmp_path):
    packages = {k: v for k, v in PACKAGES.items() if k != "resultados-2022"}
    with client_for(make_handler(packages)) as client, pytest.raises(DownloadError, match="resultados-2022"):
        plan_tse_downloads(2022, tmp_path, client=client)


def test_plan_rejects_year_without_known_layout(tmp_path):
    with client_for(make_handler()) as client, pytest.raises(ValueError, match="2018"):
        plan_tse_downloads(2018, tmp_path, client=client)


# ------------------------------- run_tse_downloads ------------------------------- #

def test_run_downloads_and_extracts_every_planned_zip(tmp_path):
    with client_for(make_handler()) as client:
        failures = run_tse_downloads(tmp_path, [2022], client=client)
    assert failures == []
    assert (tmp_path / "tse/candidatos/consulta_cand_2022.csv").exists()
    assert (tmp_path / "tse/candidatos/consulta_cand_complementar_2022.csv").exists()
    assert (tmp_path / "tse/bens/bem_candidato_2022.csv").exists()
    assert (tmp_path / "tse/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.csv").exists()
    assert (tmp_path / "tse/redes_sociais/rede_social_candidato_2022_SP.csv").exists()
    assert (tmp_path / "tse/votacao/totalizacao/Historico_Totalizacao_Presidente_BR_1T_2022.csv").exists()
    assert (tmp_path / "tse/votacao/munzona/votacao_candidato_munzona_2022/votacao_candidato_munzona_2022.csv").exists()


def test_run_skips_already_downloaded_zips(tmp_path):
    hits = []
    with client_for(make_handler(hits=hits)) as client:
        run_tse_downloads(tmp_path, [2022], client=client)
    first = [h for h in hits if "cdn.tse.jus.br" in h]
    hits.clear()
    with client_for(make_handler(hits=hits)) as client:
        failures = run_tse_downloads(tmp_path, [2022], client=client)
    assert failures == []
    assert first and not [h for h in hits if "cdn.tse.jus.br" in h]


def test_run_one_failing_download_does_not_stop_the_others(tmp_path):
    bad = f"{CDN}/bem_candidato/bem_candidato_2022.zip"
    with client_for(make_handler(fail_urls=(bad,))) as client:
        failures = run_tse_downloads(tmp_path, [2022], client=client)
    assert len(failures) == 1 and "bem_candidato" in str(failures[0])
    assert not (tmp_path / "tse/bens/bem_candidato_2022.csv").exists()
    assert (tmp_path / "tse/candidatos/consulta_cand_2022.csv").exists()


def test_run_reports_plan_failure_instead_of_raising(tmp_path):
    packages = {k: v for k, v in PACKAGES.items() if k != "resultados-2022"}
    with client_for(make_handler(packages)) as client:
        failures = run_tse_downloads(tmp_path, [2022], client=client)
    assert failures and all(isinstance(f, DownloadError) for f in failures)


# ------------------------------- 2026 ------------------------------- #

def test_plan_2026_maps_candidates_and_finance_to_the_same_directories(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2026, tmp_path, client=client)
    got = dests(plan)
    t = tmp_path.as_posix()
    assert ("consulta_cand_2026.zip", f"{t}/tse/candidatos") in got
    assert ("consulta_cand_complementar_2026.zip", f"{t}/tse/candidatos") in got
    assert ("bem_candidato_2026.zip", f"{t}/tse/bens") in got
    assert ("consulta_coligacao_2026.zip", f"{t}/tse/coligacoes") in got
    assert ("motivo_cassacao_2026.zip", f"{t}/tse/cassacao") in got
    assert ("prestacao_de_contas_eleitorais_candidatos_2026.zip", f"{t}/tse/prestacao_contas") in got


def test_plan_2026_social_networks_is_a_single_zip_without_uf(tmp_path):
    with client_for(make_handler()) as client:
        plan = plan_tse_downloads(2026, tmp_path, client=client)
    redes = [p.url for p in plan if p.dest_dir == tmp_path / "tse" / "redes_sociais"]
    assert redes == [f"{CDN}/consulta_cand/rede_social_candidato_2026.zip"]


def test_plan_2026_results_not_published_yet_is_a_warning_not_a_failure(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="ETL.TSE"), client_for(make_handler()) as client:
        plan = plan_tse_downloads(2026, tmp_path, client=client)
    assert not [p for p in plan if "/votacao/" in p.dest_dir.as_posix()]
    text = caplog.text
    assert "ainda não publicado" in text and "votacao_candidato_munzona_2026" in text


def test_plan_2026_downloads_results_as_soon_as_they_are_published(tmp_path):
    packages = {k: list(v) for k, v in PACKAGES.items()}
    packages["resultados-2026"] += [
        res("Votação nominal por município e zona",
            f"{CDN}/votacao_candidato_munzona/votacao_candidato_munzona_2026.zip"),
        res("Detalhe da apuração por seção eleitoral",
            f"{CDN}/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip"),
    ]
    with client_for(make_handler(packages)) as client:
        plan = plan_tse_downloads(2026, tmp_path, client=client)
    got = dests(plan)
    t = tmp_path.as_posix()
    assert ("votacao_candidato_munzona_2026.zip",
            f"{t}/tse/votacao/munzona/votacao_candidato_munzona_2026") in got
    assert ("detalhe_votacao_secao_2026.zip", f"{t}/tse/votacao/secao/detalhe_votacao_secao_2026") in got


def test_plan_2026_missing_required_resource_is_still_an_error(tmp_path):
    packages = {k: list(v) for k, v in PACKAGES.items()}
    packages["candidatos-2026"] = [r for r in packages["candidatos-2026"] if "bem_candidato" not in r["url"]]
    with client_for(make_handler(packages)) as client, pytest.raises(DownloadError, match="bem_candidato"):
        plan_tse_downloads(2026, tmp_path, client=client)


def test_plan_2022_missing_results_is_still_an_error(tmp_path):
    packages = {k: list(v) for k, v in PACKAGES.items()}
    packages["resultados-2022"] = [r for r in packages["resultados-2022"] if "munzona" not in r["url"]]
    with client_for(make_handler(packages)) as client, pytest.raises(DownloadError, match="munzona"):
        plan_tse_downloads(2022, tmp_path, client=client)


def test_run_2022_and_2026_side_by_side_without_name_collisions(tmp_path):
    with client_for(make_handler()) as client:
        failures = run_tse_downloads(tmp_path, [2022, 2026], client=client)
    assert failures == []
    for name in ("consulta_cand_2022", "consulta_cand_2026", "consulta_cand_complementar_2022",
                 "consulta_cand_complementar_2026"):
        assert (tmp_path / "tse/candidatos" / f"{name}.csv").exists()
    assert (tmp_path / "tse/redes_sociais/rede_social_candidato_2026.csv").exists()
    assert (tmp_path / "tse/redes_sociais/rede_social_candidato_2022_SP.csv").exists()


# ------------------------------- configuração vinda do manifesto ------------------------------- #

def test_plan_uses_package_ids_and_rules_from_the_given_manifest(tmp_path):
    manifest = {
        "version": 1, "sources": [],
        "tse": {
            "packages": {"2030": {"candidatos": "candidatos-2030"}},
            "rules": [{"package": "candidatos", "pattern": "consulta_cand_{a}", "dest": "tse/outro"}],
            "pending_ok": {},
        },
    }
    packages = {"candidatos-2030": [res("Candidatos", f"{CDN}/consulta_cand/consulta_cand_2030.zip")]}
    with client_for(make_handler(packages)) as client:
        plan = plan_tse_downloads(2030, tmp_path, client=client, manifest=manifest)
    assert [(p.stem, p.dest_dir) for p in plan] == [("consulta_cand_2030", tmp_path / "tse" / "outro")]


def test_plan_year_missing_in_manifest_is_rejected(tmp_path):
    manifest = {"version": 1, "sources": [], "tse": {"packages": {}, "rules": [], "pending_ok": {}}}
    with client_for(make_handler()) as client, pytest.raises(ValueError, match="2022"):
        plan_tse_downloads(2022, tmp_path, client=client, manifest=manifest)

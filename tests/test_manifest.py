"""Manifesto declarativo das fontes de dados: carga, validação e expansão por ano."""

import copy
import json

import pytest

from src.etl.manifest import ManifestError, Source, expand_sources, load_manifest, tse_config, validate_manifest


def base():
    return {
        "version": 1,
        "sources": [
            {"id": "camara-deputados", "kind": "file", "url": "https://x.gov.br/deputados.csv",
             "dest": "camara/cadastro/deputados.csv", "desc": "Câmara - Cadastro"},
            {"id": "camara-ceap", "kind": "zip_csv", "anos": [2025, 2026],
             "url": "https://x.gov.br/Ano-{ano}.csv.zip", "dest": "camara/ceap", "prefix": "Ano-{ano}",
             "desc": "CEAP {ano}"},
        ],
        "tse": {"packages": {}, "rules": [], "pending_ok": {}},
    }


# ------------------------------- manifesto real ------------------------------- #

def test_real_manifest_loads_and_has_unique_ids():
    manifest = load_manifest()
    sources = expand_sources(manifest)
    ids = [s.id for s in sources]
    assert manifest["version"] == 1
    assert len(ids) == len(set(ids)) > 20


def test_real_manifest_urls_are_https_and_destinations_are_relative():
    for s in expand_sources(load_manifest()):
        assert s.url.startswith("https://"), s.id
        assert not s.dest.startswith("/") and ".." not in s.dest.split("/"), s.id


def test_real_manifest_covers_camara_and_senado_years_2022_to_2026():
    by_id = {s.id: s for s in expand_sources(load_manifest())}
    for ano in range(2022, 2027):
        for fonte in ("camara-ceap", "camara-votacoes", "camara-votacoes-votos", "camara-proposicoes",
                      "camara-proposicoes-autores", "senado-ceaps", "senado-materias"):
            assert f"{fonte}-{ano}" in by_id, f"{fonte}-{ano}"
    assert "camara-deputados" in by_id and "senado-senadores" in by_id


def test_real_manifest_senado_materias_uses_the_processo_service_into_the_dir_the_etl_reads():
    s = {s.id: s for s in expand_sources(load_manifest())}["senado-materias-2024"]
    assert s.url == "https://legis.senado.leg.br/dadosabertos/processo.csv?ano=2024"
    assert s.dest == "senado/materias/materias-2024.csv"
    assert s.refresh == "always"  # serviço dinâmico, sem ETag nem Last-Modified


def test_real_manifest_destinations_match_what_build_parquet_reads():
    dests = {s.dest for s in expand_sources(load_manifest())}
    assert "camara/cadastro/deputados.csv" in dests
    assert "senado/cadastro/senadores.csv" in dests
    assert any(d.startswith("camara/ceap") for d in dests)
    assert any(d.startswith("camara/proposicoes/") for d in dests)
    assert any(d.startswith("senado/ceaps/") for d in dests)


# ------------------------------- expansão ------------------------------- #

def test_expand_file_source_without_years():
    sources = expand_sources(base())
    s = next(s for s in sources if s.id == "camara-deputados")
    assert s == Source(id="camara-deputados", kind="file", url="https://x.gov.br/deputados.csv",
                       dest="camara/cadastro/deputados.csv", desc="Câmara - Cadastro", prefix=None,
                       sha256=None, refresh="validators", ano=None)


def test_expand_zip_source_per_year_formats_every_field():
    sources = [s for s in expand_sources(base()) if s.kind == "zip_csv"]
    assert [s.id for s in sources] == ["camara-ceap-2025", "camara-ceap-2026"]
    assert sources[1].url == "https://x.gov.br/Ano-2026.csv.zip"
    assert sources[1].prefix == "Ano-2026" and sources[1].desc == "CEAP 2026" and sources[1].ano == 2026
    assert sources[1].dest == "camara/ceap"


# ------------------------------- validação ------------------------------- #

def bad(mutate):
    m = copy.deepcopy(base())
    mutate(m)
    return m


@pytest.mark.parametrize("mutate, match", [
    (lambda m: m["sources"].append(copy.deepcopy(m["sources"][0])), "duplicad"),
    (lambda m: m["sources"][0].update(kind="ftp"), "kind"),
    (lambda m: m["sources"][0].pop("url"), "url"),
    (lambda m: m["sources"][0].update(url="http://inseguro.gov.br/a.csv"), "https"),
    (lambda m: m["sources"][0].update(dest="/etc/passwd"), "dest"),
    (lambda m: m["sources"][0].update(dest="../fora/a.csv"), "dest"),
    (lambda m: m["sources"][1].update(anos=[]), "anos"),
    (lambda m: m["sources"][0].update(anos=[2024]), "{ano}"),
    (lambda m: m["sources"][1].pop("prefix"), "prefix"),
    (lambda m: m["sources"][0].update(sha256="nao-e-hex"), "sha256"),
    (lambda m: m["sources"][0].update(refresh="às vezes"), "refresh"),
    (lambda m: m.update(version=2), "version"),
    (lambda m: m["sources"][0].pop("id"), "id"),
])
def test_invalid_manifest_is_explicit_error(mutate, match):
    with pytest.raises(ManifestError, match=match):
        validate_manifest(bad(mutate))


def test_valid_sha256_is_accepted():
    m = base()
    m["sources"][0]["sha256"] = "a" * 64
    assert expand_sources(m)[0].sha256 == "a" * 64


def test_load_manifest_from_custom_path_and_invalid_json(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(base()), encoding="utf-8")
    assert load_manifest(p)["version"] == 1
    p.write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ManifestError, match="JSON"):
        load_manifest(p)
    with pytest.raises(ManifestError, match="não encontrado"):
        load_manifest(tmp_path / "inexistente.json")


# ------------------------------- TSE ------------------------------- #

def test_tse_config_of_real_manifest_matches_the_layout_the_etl_reads():
    cfg = tse_config(load_manifest())
    assert cfg.packages[2022]["resultados"] == "resultados-2022"
    assert cfg.packages[2026]["candidatos"] == "candidatos-2026"
    assert cfg.pending_ok == {2026: {"resultados"}}
    dests = {r.dest for r in cfg.rules}
    assert {"tse/candidatos", "tse/bens", "tse/prestacao_contas", "tse/redes_sociais",
            "tse/votacao/totalizacao"} <= dests
    assert any(r.dest == "tse/votacao/munzona/votacao_candidato_munzona_{a}" for r in cfg.rules)


def test_tse_rule_with_unknown_package_is_invalid():
    m = base()
    m["tse"] = {"packages": {"2022": {"candidatos": "candidatos-2022"}},
                "rules": [{"package": "resultados", "pattern": "x_{a}", "dest": "tse/x"}], "pending_ok": {}}
    with pytest.raises(ManifestError, match="resultados"):
        validate_manifest(m)


def test_tse_rule_with_invalid_regex_is_invalid():
    m = base()
    m["tse"] = {"packages": {"2022": {"candidatos": "candidatos-2022"}},
                "rules": [{"package": "candidatos", "pattern": "(sem_fechar", "dest": "tse/x"}], "pending_ok": {}}
    with pytest.raises(ManifestError, match="regex"):
        validate_manifest(m)


# ------------------------------- triggers_build ------------------------------- #

def test_triggers_build_defaults_to_true_and_can_be_disabled():
    m = base()
    assert all(s.triggers_build for s in expand_sources(m))
    m["sources"][0]["triggers_build"] = False
    by_id = {s.id: s for s in expand_sources(m)}
    assert by_id["camara-deputados"].triggers_build is False and by_id["camara-ceap-2025"].triggers_build is True


def test_triggers_build_must_be_a_boolean():
    m = base()
    m["sources"][0]["triggers_build"] = "nao"
    with pytest.raises(ManifestError, match="triggers_build"):
        validate_manifest(m)


def test_real_manifest_senado_never_triggers_a_rebuild_but_camara_does():
    for s in expand_sources(load_manifest()):
        origin = s.id.split("-", 1)[0]
        assert s.triggers_build is (origin != "senado"), s.id

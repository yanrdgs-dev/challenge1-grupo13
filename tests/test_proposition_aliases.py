"""Nome popular de proposição ("PEC da escala 6x1") → identificação oficial (sigla, número e ano).

A ementa da PEC 221/2019 fala em 'jornada de trabalho de 36 horas semanais', sem '6x1': o apelido só existe na
imprensa. Uma base curada e versionada liga o apelido à proposição, e o resolvedor continua sendo quem confirma o ID.
"""

import json
from pathlib import Path

import pytest

from src.tools.proposition_aliases import ALIASES_FILE, find_alias, load_aliases


@pytest.mark.parametrize("text, expected", [
    ("Quantos votos teve a PEC da escala 6x1?", ("PEC", 221, 2019)),
    ("O fim da escala 6x1 foi aprovado pelo Senado?", ("PEC", 221, 2019)),
    ("A PEC do fim da jornada 6x1 teve só um voto contra.", ("PEC", 221, 2019)),
    ("A PEC DA ESCALA 6 X 1 foi aprovada?", ("PEC", 221, 2019)),
    ("A PEC da Reforma Tributária foi aprovada em 2023?", ("PEC", 45, 2019)),
    ("O PL das Fake News foi aprovado?", ("PL", 2630, 2020)),
    ("A Lei das Fake News passou na Câmara?", ("PL", 2630, 2020)),
])
def test_find_alias_maps_the_popular_name_to_the_official_identification(text, expected):
    alias = find_alias(text)
    assert alias is not None
    assert (alias["sigla_tipo"], alias["numero"], alias["ano"]) == expected


@pytest.mark.parametrize("text", [
    "Quem mais gastou a cota parlamentar em 2023?",
    "A PEC 45/2019 foi aprovada?",                                    # número já citado: não precisa de apelido
    "Há jornada de trabalho de oito horas na CLT?",                   # 'jornada' sozinha não é o apelido
    "A escala de plantão dos médicos mudou em 2024.",
    "",
])
def test_find_alias_returns_none_when_no_popular_name_is_cited(text):
    assert find_alias(text) is None


def test_two_different_propositions_in_the_same_text_are_ambiguous_and_resolve_to_none():
    assert find_alias("A PEC da escala 6x1 e a Reforma Tributária foram aprovadas?") is None


def test_alias_file_is_valid_curated_and_has_no_alias_shared_by_two_propositions():
    entries = load_aliases()
    assert entries and Path(ALIASES_FILE).exists()
    seen = {}
    for entry in entries:
        assert entry["sigla_tipo"] and isinstance(entry["numero"], int) and isinstance(entry["ano"], int)
        assert entry["apelidos"] and entry.get("descricao")
        for apelido in entry["apelidos"]:
            assert seen.setdefault(apelido.lower(), entry["id"]) == entry["id"], f"apelido repetido: {apelido}"


def test_alias_file_is_plain_json_that_people_can_extend():
    data = json.loads(Path(ALIASES_FILE).read_text(encoding="utf-8"))
    assert isinstance(data, list) and all({"id", "apelidos", "sigla_tipo", "numero", "ano"} <= set(e) for e in data)

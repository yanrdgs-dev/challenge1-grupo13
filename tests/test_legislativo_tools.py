"""Testes unitários para o Grupo 4: Tools do Legislativo e Tramitação de Proposições.

Cobre a especificação da tool get_proposition_tramitation_history (seção 4.1 de
docs/tools_specification.md) e validações associadas à claim 18 de golden_dataset_v1.json.
Atende estritamente às regras 7, 8 e 10 de AGENTS.md (TDD, suíte completa de testes).
"""

from pathlib import Path
from typing import Any, Dict
import polars as pl
import pytest

# A importação da tool deve existir no módulo src.tools.legislativo_tools
from src.tools.legislativo_tools import (
    get_proposition_tramitation_history,
    is_thematic_commission,
    check_bill_apensamentos,
)


@pytest.fixture
def mock_camara_proposicoes_dir(tmp_path: Path) -> Path:
    """Cria arquivos Parquet de teste simulando a base de proposições e tramitações da Câmara."""
    camara_dir = tmp_path / "camara"
    camara_dir.mkdir(parents=True, exist_ok=True)

    # 1. Proposições da Câmara (PL aprovado passando por comissão, PL apensado, etc.)
    df_props = pl.DataFrame({
        "id": ["1001", "1002", "1003"],
        "siglaTipo": ["PL", "PL", "PEC"],
        "numero": [1234, 5678, 45],
        "ano": [2023, 2023, 2024],
        "ementa": [
            "Dispõe sobre regulamentação de tecnologia.",
            "Altera regras de trânsito.",
            "Reforma tributária nacional.",
        ],
        "ultimoStatus_dataHora": ["2023-11-20T14:30:00", "2023-08-15T10:00:00", "2024-05-10T16:00:00"],
        "ultimoStatus_siglaOrgao": ["PLEN", "CCJC", "PLEN"],
        "ultimoStatus_descricaoTramitacao": ["Aprovação em Plenário", "Parecer de Comissão", "Promulgação"],
        "ultimoStatus_descricaoSituacao": ["Transformado em Norma Jurídica", "Em tramitação", "Aprovada"],
        "ultimoStatus_despacho": ["Aprovado com parecer favorável", "Distribuído à comissão", "Promulgada"],
        "uriPropPrincipal": [None, "https://dadosabertos.camara.leg.br/api/v2/proposicoes/9999", None],
        "idPropPrincipal": [None, "9999", None],
        "urlInteiroTeor": [
            "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=1001",
            "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=1002",
            "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=1003",
        ],
    })
    props_file = camara_dir / "proposicoes.parquet"
    df_props.write_parquet(props_file)

    # 2. Histórico detalhado de tramitações (para verificar passagem por comissões temáticas)
    df_tramitacoes = pl.DataFrame({
        "idProposicao": ["1001", "1001", "1001", "1002", "1003"],
        "dataHora": [
            "2023-03-10T09:00:00",
            "2023-06-15T14:00:00",
            "2023-11-20T14:30:00",
            "2023-08-15T10:00:00",
            "2024-05-10T16:00:00",
        ],
        "siglaOrgao": ["CCJC", "CFT", "PLEN", "CCJC", "PLEN"],
        "descricaoTramitacao": [
            "Parecer favorável aprovado na CCJC",
            "Parecer pela adequação financeira e orçamentária",
            "Votação final e aprovação em Plenário",
            "Distribuição à CCJC",
            "Aprovação em dois turnos no Plenário",
        ],
        "despacho": [
            "Aprovado por unanimidade na comissão temática",
            "Aprovado o parecer na comissão de finanças",
            "Matéria aprovada pelo Plenário",
            "Aguardando designação de relator",
            "Aprovada a redação final",
        ],
    })
    tramitacoes_file = camara_dir / "proposicoes_tramitacoes.parquet"
    df_tramitacoes.write_parquet(tramitacoes_file)

    return tmp_path


@pytest.fixture
def mock_senado_materias_dir(tmp_path: Path) -> Path:
    """Cria arquivos Parquet de teste simulando as matérias do Senado."""
    senado_dir = tmp_path / "senado"
    senado_dir.mkdir(parents=True, exist_ok=True)

    df_senado = pl.DataFrame({
        "codigo": ["2001", "2002"],
        "identificacao": ["PL 500/2023", "PEC 10/2024"],
        "ementa": ["Estabelece marco regulatório setorial.", "Altera dispositivo constitucional."],
        "autoria": ["Senador Teste", "Senadora Exemplo"],
        "situacaoAtual": ["Aprovada com parecer na CCJ", "Pronta para deliberação na CAE"],
        "localAtual": ["CCJ", "CAE"],
        "tramitando": ["Não", "Sim"],
        "normaGerada": ["Lei nº 14.999/2023", None],
        "urlDocumento": ["https://legis.senado.leg.br/doc/2001", "https://legis.senado.leg.br/doc/2002"],
        "proposicaoPrincipal": [None, None],
    })
    materias_file = senado_dir / "materias.parquet"
    df_senado.write_parquet(materias_file)

    return tmp_path


# ---------------------------------------------------------------------------
# Testes do Caminho Feliz (Happy Path)
# ---------------------------------------------------------------------------

def test_get_proposition_tramitation_history_camara_happy_path(mock_camara_proposicoes_dir: Path):
    """Valida retorno do histórico de tramitação na Câmara com passagens por comissões temáticas."""
    result = get_proposition_tramitation_history(
        casa="camara",
        id_proposicao="1001",
        data_dir=mock_camara_proposicoes_dir,
    )

    assert result["encontrado"] is True
    assert result["id_proposicao"] == "1001"
    assert result["casa"] == "camara"
    assert isinstance(result["tramitacao"], list)
    assert len(result["tramitacao"]) == 3

    # Verifica o formato dos passos de tramitação: [{data, orgao, despacho}]
    first_step = result["tramitacao"][0]
    assert "data" in first_step
    assert "orgao" in first_step
    assert "despacho" in first_step
    assert first_step["orgao"] == "CCJC"

    # Confirma que a matéria não está apensada
    assert result["proposicao_principal"] is None
    assert result["apensada"] is False

    # Confirma detecção de passagem por comissões temáticas (CCJC e CFT)
    assert result["passou_comissao_tematica"] is True
    assert "CCJC" in result["comissoes_tematicas"]
    assert "CFT" in result["comissoes_tematicas"]


def test_get_proposition_tramitation_history_camara_apensada(mock_camara_proposicoes_dir: Path):
    """Valida detecção de apensamento a proposição principal."""
    result = get_proposition_tramitation_history(
        casa="camara",
        id_proposicao="1002",
        data_dir=mock_camara_proposicoes_dir,
    )

    assert result["encontrado"] is True
    assert result["id_proposicao"] == "1002"
    assert result["proposicao_principal"] is not None
    assert result["apensada"] is True
    assert "9999" in str(result["proposicao_principal"])


def test_get_proposition_tramitation_history_senado_happy_path(mock_senado_materias_dir: Path):
    """Valida consulta de tramitação no Senado com órgão temático (CCJ)."""
    result = get_proposition_tramitation_history(
        casa="senado",
        id_proposicao="2001",
        data_dir=mock_senado_materias_dir,
    )

    assert result["encontrado"] is True
    assert result["id_proposicao"] == "2001"
    assert result["casa"] == "senado"
    assert len(result["tramitacao"]) >= 1
    assert result["passou_comissao_tematica"] is True
    assert "CCJ" in result["comissoes_tematicas"]


# ---------------------------------------------------------------------------
# Testes de Entidade Não Encontrada e Validações de Entrada
# ---------------------------------------------------------------------------

def test_get_proposition_tramitation_history_not_found(mock_camara_proposicoes_dir: Path):
    """Valida comportamento seguro quando a proposição não é encontrada na base local."""
    result = get_proposition_tramitation_history(
        casa="camara",
        id_proposicao="9999999",
        data_dir=mock_camara_proposicoes_dir,
    )

    assert result["encontrado"] is False
    assert result["id_proposicao"] == "9999999"
    assert result["tramitacao"] == []
    assert result["proposicao_principal"] is None
    assert result["passou_comissao_tematica"] is False


def test_get_proposition_tramitation_history_invalid_casa(mock_camara_proposicoes_dir: Path):
    """Valida erro ao informar casa legislativa não suportada."""
    with pytest.raises(ValueError, match="Casa.*inválida"):
        get_proposition_tramitation_history(
            casa="stf",
            id_proposicao="1001",
            data_dir=mock_camara_proposicoes_dir,
        )


def test_get_proposition_tramitation_history_empty_id(mock_camara_proposicoes_dir: Path):
    """Valida erro ao passar id_proposicao vazio ou nulo."""
    with pytest.raises(ValueError, match="id_proposicao"):
        get_proposition_tramitation_history(
            casa="camara",
            id_proposicao="",
            data_dir=mock_camara_proposicoes_dir,
        )


# ---------------------------------------------------------------------------
# Testes de Funções Auxiliares: Comissões Temáticas e Apensamentos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "orgao,expected",
    [
        ("CCJC", True),
        ("CFT", True),
        ("CSAUDE", True),
        ("CE", True),
        ("COMISSÃO ESPECIAL", True),
        ("CCJ", True),
        ("CAE", True),
        ("PLEN", False),
        ("PLENARIO", False),
        ("MESA", False),
        ("SECOM", False),
        ("", False),
        (None, False),
    ],
)
def test_is_thematic_commission(orgao: Any, expected: bool):
    """Valida identificador de órgãos/comissões temáticas contra órgãos administrativos/plenário."""
    assert is_thematic_commission(orgao) == expected


def test_check_bill_apensamentos_helper(mock_camara_proposicoes_dir: Path):
    """Valida a tool auxiliar check_bill_apensamentos."""
    res_indep = check_bill_apensamentos(
        id_proposicao="1001",
        casa="camara",
        data_dir=mock_camara_proposicoes_dir,
    )
    assert res_indep["apensada"] is False
    assert res_indep["proposicao_principal"] is None

    res_apensada = check_bill_apensamentos(
        id_proposicao="1002",
        casa="camara",
        data_dir=mock_camara_proposicoes_dir,
    )
    assert res_apensada["apensada"] is True
    assert "9999" in str(res_apensada["proposicao_principal"])


# ---------------------------------------------------------------------------
# Validação Específica para a Claim 18 do Golden Dataset v1
# ---------------------------------------------------------------------------

def test_golden_dataset_claim_18_verification(mock_camara_proposicoes_dir: Path):
    """Valida que a tool fornece a evidência empírica para refutar a Claim 18.

    Claim 18: 'Nenhum projeto de lei aprovado na Câmara dos Deputados passa por votação nas comissões temáticas.'
    Expected Verdict: FALSO.
    A tool deve comprovar que o PL aprovado (1001) tramitou e teve parecer aprovado em comissões temáticas (CCJC/CFT).
    """
    history = get_proposition_tramitation_history(
        casa="camara",
        id_proposicao="1001",
        data_dir=mock_camara_proposicoes_dir,
    )

    # 1. Prova que o projeto foi localizado
    assert history["encontrado"] is True

    # 2. Prova documental de que passou por comissões temáticas antes do plenário
    assert history["passou_comissao_tematica"] is True
    comissoes = history["comissoes_tematicas"]
    assert len(comissoes) > 0
    assert "CCJC" in comissoes

    # 3. Permite ao Agente Sintetizador refutar categoricamente a claim
    comissao_steps = [s for s in history["tramitacao"] if is_thematic_commission(s.get("orgao"))]
    assert len(comissao_steps) >= 1
    assert any("parecer" in s.get("despacho", "").lower() for s in comissao_steps)

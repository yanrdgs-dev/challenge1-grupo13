"""Tools do Grupo 4: Legislativo e Tramitação de Proposições.

Implementa a tool get_proposition_tramitation_history (seção 4.1 de docs/tools_specification.md)
e utilitários analíticos sobre dados locais da Câmara dos Deputados e Senado Federal.
Atende estritamente às regras de AGENTS.md (evidência rastreável, TDD, Polars/DuckDB).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import polars as pl

logger = logging.getLogger("Tools.Legislativo")

# Órgãos administrativos, de plenário ou comissões não temáticas (exceções a ignorar)
NON_THEMATIC_ORGANS = {
    "PLEN",
    "PLENARIO",
    "PLENÁRIO",
    "MESA",
    "MESA DIRETORA",
    "SECOM",
    "SGM",
    "OUVID",
    "CODIR",
    "CORREG",
    "PRESIDENCIA",
    "PRESIDÊNCIA",
    "SECRETARIA",
    "COORDENACAO",
    "COORDENAÇÃO",
    "GABINETE",
}


def is_thematic_commission(orgao: Optional[str]) -> bool:
    """Verifica se uma sigla ou nome de órgão corresponde a uma comissão temática.

    Comissões temáticas na Câmara e no Senado são responsáveis pela deliberação
    específica de mérito (ex: CCJC, CFT, CSAUDE, CCJ, CAE). Plenário e órgãos da
    Mesa são expressamente excluídos.

    Args:
        orgao: Sigla ou descrição textual do órgão deliberativo (ex: 'CCJC', 'PLEN').

    Returns:
        True se for comissão temática ou especial; False caso contrário.
    """
    if not orgao or not isinstance(orgao, str):
        return False

    clean_org = orgao.strip().upper()
    if not clean_org or clean_org in NON_THEMATIC_ORGANS:
        return False

    # Detecção de comissões permanentes e especiais por nomenclatura ou prefixo clássico
    if "COMISS" in clean_org or "COMISSAO" in clean_org or "COMISSÃO" in clean_org:
        return True

    # Comissões temáticas clássicas da Câmara e do Senado (iniciadas por C e com 2 a 8 caracteres)
    if clean_org.startswith("C") and len(clean_org) >= 2:
        return True

    return False


def _find_parquet_files(base_path: Path, pattern: str) -> List[Path]:
    """Localiza arquivos Parquet a partir de um diretório base e padrão."""
    if not base_path.exists():
        return []

    if base_path.is_file() and base_path.suffix == ".parquet":
        return [base_path]

    # Procura arquivos correspondentes ao padrão ou subdiretórios
    direct_match = list(base_path.glob(pattern))
    if direct_match:
        return direct_match

    # Busca recursiva caso organizado em partições
    recursive_match = list(base_path.glob(f"**/{pattern}"))
    return recursive_match


def get_proposition_tramitation_history(
    casa: str,
    id_proposicao: str,
    data_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Retorna a sequência de despachos/órgãos pelos quais a proposição tramitou.

    Verifica se a matéria passou por comissões temáticas antes do plenário e se
    está apensada a outra matéria principal.

    Args:
        casa: Casa legislativa de origem ('camara' ou 'senado').
        id_proposicao: ID canônico da proposição/matéria (string ou numérico).
        data_dir: Diretório raiz onde os Parquets processados residem (padrão: data/processed).

    Returns:
        Dicionário com o histórico de tramitação, indicação de apensamento e flags analíticas:
        {
            "id_proposicao": str,
            "casa": str,
            "encontrado": bool,
            "tramitacao": [{"data": str, "orgao": str, "despacho": str}],
            "proposicao_principal": Optional[str],
            "apensada": bool,
            "passou_comissao_tematica": bool,
            "comissoes_tematicas": List[str],
            "situacao_atual": str,
        }

    Raises:
        ValueError: Se casa for inválida ou id_proposicao for vazio/nulo.
    """
    if not casa or not isinstance(casa, str):
        raise ValueError("Casa legislativa deve ser uma string informando 'camara' ou 'senado'.")

    normalized_casa = casa.strip().lower()
    if normalized_casa not in ("camara", "senado"):
        raise ValueError(f"Casa '{casa}' inválida. Use 'camara' ou 'senado'.")

    if not id_proposicao or not str(id_proposicao).strip():
        raise ValueError("id_proposicao é obrigatório e não pode ser vazio.")

    target_id = str(id_proposicao).strip()
    root_data = Path(data_dir) if data_dir else Path("data/processed")

    if normalized_casa == "camara":
        return _get_camara_tramitation(root_data, target_id)
    else:
        return _get_senado_tramitation(root_data, target_id)


def _get_camara_tramitation(root_data: Path, target_id: str) -> Dict[str, Any]:
    """Processa tramitação e dados de proposição da Câmara dos Deputados."""
    camara_dir = root_data / "camara"

    # Localizar Parquet de proposições
    prop_candidates = (
        _find_parquet_files(camara_dir, "proposicoes.parquet")
        or _find_parquet_files(camara_dir / "proposicoes", "*.parquet")
        or _find_parquet_files(camara_dir, "*proposicoes*.parquet")
    )

    if not prop_candidates:
        logger.warning("Nenhum arquivo Parquet de proposições da Câmara encontrado em '%s'", camara_dir)
        return _build_not_found_result("camara", target_id)

    # Leitura e filtro da proposição via Polars
    try:
        df_prop = pl.read_parquet(prop_candidates)
    except Exception as err:
        logger.error("Erro ao ler Parquet de proposições da Câmara: %s", err)
        return _build_not_found_result("camara", target_id)

    id_col = "id" if "id" in df_prop.columns else "idProposicao"
    if id_col not in df_prop.columns:
        return _build_not_found_result("camara", target_id)

    # Cast para string para match canônico estrito
    matched_props = df_prop.filter(pl.col(id_col).cast(pl.String) == target_id)
    if matched_props.height == 0:
        return _build_not_found_result("camara", target_id)

    prop_row = matched_props.to_dicts()[0]

    # Verificação de apensamento (uriPropPrincipal ou idPropPrincipal)
    uri_principal = prop_row.get("uriPropPrincipal")
    id_principal = prop_row.get("idPropPrincipal")
    proposicao_principal: Optional[str] = None
    if id_principal and str(id_principal).strip() not in ("", "None", "null"):
        proposicao_principal = str(id_principal).strip()
    elif uri_principal and str(uri_principal).strip() not in ("", "None", "null"):
        proposicao_principal = str(uri_principal).strip()

    apensada = proposicao_principal is not None

    # Consulta de histórico de tramitações (se tabela dedicada existir)
    tramitacoes_candidates = (
        _find_parquet_files(camara_dir, "proposicoes_tramitacoes.parquet")
        or _find_parquet_files(camara_dir / "tramitacoes", "*.parquet")
        or _find_parquet_files(camara_dir, "*tramitac*.parquet")
    )

    tramitacao_steps: List[Dict[str, Any]] = []

    if tramitacoes_candidates:
        try:
            df_tram = pl.read_parquet(tramitacoes_candidates)
            tram_id_col = "idProposicao" if "idProposicao" in df_tram.columns else "id"
            if tram_id_col in df_tram.columns:
                matched_tram = df_tram.filter(pl.col(tram_id_col).cast(pl.String) == target_id)
                if "dataHora" in matched_tram.columns:
                    matched_tram = matched_tram.sort("dataHora")

                for row in matched_tram.to_dicts():
                    tramitacao_steps.append({
                        "data": str(row.get("dataHora") or ""),
                        "orgao": str(row.get("siglaOrgao") or row.get("orgao") or ""),
                        "despacho": str(row.get("despacho") or row.get("descricaoTramitacao") or ""),
                    })
        except Exception as err:
            logger.warning("Falha ao ler tramitações detalhadas da Câmara: %s", err)

    # Se não houver histórico detalhado, extrai o último status da proposição
    if not tramitacao_steps:
        ultimo_orgao = prop_row.get("ultimoStatus_siglaOrgao") or prop_row.get("siglaOrgao") or ""
        ultimo_despacho = (
            prop_row.get("ultimoStatus_despacho")
            or prop_row.get("ultimoStatus_descricaoTramitacao")
            or ""
        )
        ultima_data = prop_row.get("ultimoStatus_dataHora") or prop_row.get("dataApresentacao") or ""
        if ultimo_orgao or ultimo_despacho:
            tramitacao_steps.append({
                "data": str(ultima_data),
                "orgao": str(ultimo_orgao),
                "despacho": str(ultimo_despacho),
            })

    # Identificar comissões temáticas visitadas
    comissoes_tematicas = _extract_thematic_commissions(tramitacao_steps)

    situacao_atual = str(
        prop_row.get("ultimoStatus_descricaoSituacao")
        or prop_row.get("situacao")
        or "Em tramitação"
    )

    return {
        "id_proposicao": target_id,
        "casa": "camara",
        "encontrado": True,
        "tramitacao": tramitacao_steps,
        "proposicao_principal": proposicao_principal,
        "apensada": apensada,
        "passou_comissao_tematica": len(comissoes_tematicas) > 0,
        "comissoes_tematicas": comissoes_tematicas,
        "situacao_atual": situacao_atual,
        "detalhes": {
            "sigla_tipo": prop_row.get("siglaTipo"),
            "numero": prop_row.get("numero"),
            "ano": prop_row.get("ano"),
            "ementa": prop_row.get("ementa"),
            "url_inteiro_teor": prop_row.get("urlInteiroTeor"),
        },
    }


def _get_senado_tramitation(root_data: Path, target_id: str) -> Dict[str, Any]:
    """Processa tramitação e dados de matéria do Senado Federal."""
    senado_dir = root_data / "senado"

    mat_candidates = (
        _find_parquet_files(senado_dir, "materias.parquet")
        or _find_parquet_files(senado_dir / "materias", "*.parquet")
        or _find_parquet_files(senado_dir, "*materia*.parquet")
    )

    if not mat_candidates:
        logger.warning("Nenhum arquivo Parquet de matérias do Senado encontrado em '%s'", senado_dir)
        return _build_not_found_result("senado", target_id)

    try:
        df_mat = pl.read_parquet(mat_candidates)
    except Exception as err:
        logger.error("Erro ao ler Parquet de matérias do Senado: %s", err)
        return _build_not_found_result("senado", target_id)

    id_col = "codigo" if "codigo" in df_mat.columns else "id"
    if id_col not in df_mat.columns:
        return _build_not_found_result("senado", target_id)

    matched_mat = df_mat.filter(pl.col(id_col).cast(pl.String) == target_id)
    if matched_mat.height == 0:
        return _build_not_found_result("senado", target_id)

    mat_row = matched_mat.to_dicts()[0]

    # Apensamento no Senado
    prop_principal = mat_row.get("proposicaoPrincipal") or mat_row.get("materiaPrincipal")
    proposicao_principal = (
        str(prop_principal).strip()
        if prop_principal and str(prop_principal).strip() not in ("", "None", "null")
        else None
    )

    local_atual = str(mat_row.get("localAtual") or mat_row.get("siglaOrgao") or "")
    situacao_atual = str(mat_row.get("situacaoAtual") or mat_row.get("descricaoSituacao") or "")

    tramitacao_steps: List[Dict[str, Any]] = [
        {
            "data": str(mat_row.get("dataUltimaAtualizacao") or ""),
            "orgao": local_atual,
            "despacho": situacao_atual,
        }
    ]

    comissoes_tematicas = _extract_thematic_commissions(tramitacao_steps)

    return {
        "id_proposicao": target_id,
        "casa": "senado",
        "encontrado": True,
        "tramitacao": tramitacao_steps,
        "proposicao_principal": proposicao_principal,
        "apensada": proposicao_principal is not None,
        "passou_comissao_tematica": len(comissoes_tematicas) > 0,
        "comissoes_tematicas": comissoes_tematicas,
        "situacao_atual": situacao_atual,
        "detalhes": {
            "identificacao": mat_row.get("identificacao"),
            "ementa": mat_row.get("ementa"),
            "autoria": mat_row.get("autoria"),
            "norma_gerada": mat_row.get("normaGerada"),
            "url_documento": mat_row.get("urlDocumento"),
        },
    }


def _extract_thematic_commissions(tramitacao_steps: List[Dict[str, Any]]) -> List[str]:
    """Extrai lista de comissões temáticas distintas a partir dos passos de tramitação."""
    comissoes: List[str] = []
    for step in tramitacao_steps:
        org = step.get("orgao")
        if org and is_thematic_commission(org) and org not in comissoes:
            comissoes.append(org)
    return comissoes


def _build_not_found_result(casa: str, target_id: str) -> Dict[str, Any]:
    """Gera estrutura padrão para entidade não encontrada."""
    return {
        "id_proposicao": target_id,
        "casa": casa,
        "encontrado": False,
        "tramitacao": [],
        "proposicao_principal": None,
        "apensada": False,
        "passou_comissao_tematica": False,
        "comissoes_tematicas": [],
        "situacao_atual": "Não encontrada",
        "mensagem": f"Proposição '{target_id}' não localizada na base local da {casa.capitalize()}.",
    }


def check_bill_apensamentos(
    id_proposicao: str,
    casa: str = "camara",
    data_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Tool auxiliar para verificar se uma proposição tramita sozinha ou apensada.

    Args:
        id_proposicao: Identificador da proposição.
        casa: Casa legislativa ('camara' ou 'senado').
        data_dir: Diretório raiz de dados.

    Returns:
        Dicionário com status de apensamento:
        {"id_proposicao": str, "casa": str, "apensada": bool, "proposicao_principal": Optional[str]}
    """
    history = get_proposition_tramitation_history(
        casa=casa,
        id_proposicao=id_proposicao,
        data_dir=data_dir,
    )
    return {
        "id_proposicao": history["id_proposicao"],
        "casa": history["casa"],
        "apensada": history["apensada"],
        "proposicao_principal": history["proposicao_principal"],
    }

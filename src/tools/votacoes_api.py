"""Módulo de tools para Votações (API ao vivo) - Parte 5 da Arquitetura de Fact-Checking.

Este módulo implementa o acesso em tempo real às APIs de Dados Abertos da
Câmara dos Deputados e do Senado Federal, com suporte a cache de sessão e retries.
Não requer nem utiliza arquivos locais ou ETL/Parquet.

Tools implementadas:
- 5.1 get_proposition_vote_result
- 5.2 get_proposition_vote_breakdown
- 5.3 get_congress_veto_sessions
- 5.4 get_plenary_attendance
"""

from typing import Any, Dict, List, Optional
import logging
import re
from src.tools.http_client import HttpClient, HttpNetworkError
from src.tools.normalizer import strip_accents as _strip_accents

logger = logging.getLogger(__name__)

# Instância padrão compartilhada com cache em memória
http_client = HttpClient(timeout=10.0, max_retries=3, retry_delay=0.5, cache_enabled=True)


# Cache de mapeamento entre código de votação do Senado e código da matéria
_senado_votacao_para_materia: Dict[str, str] = {}


# ============================================================================
# 5.1 get_proposition_vote_result
# ============================================================================


def _aprovado_camara(aprovacao: Any) -> Optional[bool]:
    """Campo oficial `aprovacao` da Câmara: 1 aprovado, 0 rejeitado, nulo/ausente indeterminado.

    O nulo aparece em votações de destaque ("Mantido o texto"): não é rejeição. O texto da descrição
    não decide, porque frases como "Não aprovado" e "Aprovado o requerimento de retirada" enganam.
    """
    if aprovacao in (1, "1", True):
        return True
    if aprovacao in (0, "0", False):
        return False
    return None


def _aprovado_senado(resultado: Any) -> Optional[bool]:
    """Resultado textual do Senado ("Aprovado", "Rejeitado"...). Qualquer outro texto é indeterminado."""
    texto = _strip_accents(str(resultado or "")).strip().lower()
    if texto.startswith(("nao aprovad", "rejeitad")):
        return False
    if texto.startswith("aprovad"):
        return True
    return None


def get_proposition_vote_result(
    id_proposicao: str,
    casa: str,
    tipo_votacao: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Consulta os eventos de votação de uma proposição na API da Câmara ou do Senado.

    Retorna lista de votações com id, data, tipo e resultado (aprovado: True, False ou None se indeterminado).
    Lista vazia indica ausência de votação (sinal para INCONCLUSIVO na claim 28).

    Args:
        id_proposicao: ID canônico da proposição resolvido previamente.
        casa: 'camara' ou 'senado'.
        tipo_votacao: Filtro opcional por tipo/descrição de votação (ex.: 'urgência', 'texto-base').

    Returns:
        Lista de dicionários: [{'id_votacao': str, 'data': str, 'tipo_votacao': str, 'aprovado': Optional[bool]}]
    """
    casa_norm = casa.lower().strip()
    if casa_norm not in ("camara", "senado"):
        raise ValueError(f"Casa inválida: '{casa}'. Valores permitidos: 'camara' ou 'senado'.")

    results: List[Dict[str, Any]] = []

    try:
        if casa_norm == "camara":
            url = f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id_proposicao}/votacoes"
            payload = http_client.get_json(url)
            itens = payload.get("dados", [])

            for item in itens:
                desc = item.get("descricao") or ""
                aprovado = _aprovado_camara(item.get("aprovacao"))

                results.append(
                    {
                        "id_votacao": str(item.get("id")),
                        "data": item.get("data"),
                        "tipo_votacao": desc,
                        "aprovado": aprovado,
                    }
                )

        elif casa_norm == "senado":
            url = f"https://legis.senado.leg.br/dadosabertos/materia/votacoes/{id_proposicao}"
            payload = http_client.get_json(url)
            materia_data = payload.get("VotacaoMateria", {}).get("Materia", {})
            votacoes_raw = materia_data.get("Votacoes", {}).get("Votacao", [])

            if isinstance(votacoes_raw, dict):
                votacoes_raw = [votacoes_raw]

            for item in votacoes_raw:
                desc = item.get("DescricaoVotacao") or ""
                aprovado = _aprovado_senado(item.get("DescricaoResultado") or item.get("Resultado"))
                data_sessao = item.get("SessaoPlenaria", {}).get("DataSessao")
                cod_sessao_vot = str(item.get("CodigoSessaoVotacao"))

                # Registra mapeamento para que get_proposition_vote_breakdown encontre a matéria
                _senado_votacao_para_materia[cod_sessao_vot] = str(id_proposicao)

                results.append(
                    {
                        "id_votacao": cod_sessao_vot,
                        "data": data_sessao,
                        "tipo_votacao": desc,
                        "aprovado": aprovado,
                    }
                )
    except HttpNetworkError as exc:
        if "404" in str(exc):
            logger.info("Proposição %s sem votações registradas (404). Retornando [].", id_proposicao)
            return []
        raise

    # Aplicação de filtro por tipo de votação se especificado
    if tipo_votacao:
        filtro = tipo_votacao.lower().strip()
        results = [r for r in results if filtro in r["tipo_votacao"].lower()]

    return results


# ============================================================================
# 5.2 get_proposition_vote_breakdown
# ============================================================================


def _classificar_voto(rotulo: str) -> str:
    """Opção de voto a partir do rótulo da API. Rótulo desconhecido vira 'outros' (nunca some da contagem)."""
    tipo = _strip_accents(rotulo).lower().strip()
    if any(t in tipo for t in ["ausente", "faltou", "nao compareceu", "nao votou"]):
        return "ausente"
    if "sim" in tipo:
        return "sim"
    if "nao" in tipo:
        return "nao"
    if "absten" in tipo:
        return "abstencao"
    if "obstru" in tipo:
        return "obstrucao"
    return "outros"


def get_proposition_vote_breakdown(id_votacao: str, casa: str) -> Dict[str, Any]:
    """Retorna a contagem de votos por opção para a votação nominal informada.

    Args:
        id_votacao: ID da votação obtido previamente via get_proposition_vote_result.
                    No Senado, aceita formato '{id_materia}_{id_votacao}' ou '{id_votacao}'.
        casa: 'camara' ou 'senado'.

    Returns:
        Dicionário: {'sim', 'nao', 'abstencao', 'obstrucao', 'ausente', 'outros': int,
        'outros_detalhe': {rótulo: contagem}, 'total': int}. As opções somam sempre o total.
        'outros' reúne o que a API registra fora dessas opções (ex.: voto do presidente "Artigo 17" na
        Câmara; "AP", "P-NRV" e "Presidente (art. 51 RISF)" no Senado) sem reinterpretá-lo.
    """
    casa_norm = casa.lower().strip()
    if casa_norm not in ("camara", "senado"):
        raise ValueError(f"Casa inválida: '{casa}'. Valores permitidos: 'camara' ou 'senado'.")

    contagem = {"sim": 0, "nao": 0, "abstencao": 0, "obstrucao": 0, "ausente": 0, "outros": 0}
    outros_detalhe: Dict[str, int] = {}
    rotulos: List[str] = []

    try:
        if casa_norm == "camara":
            url = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}/votos"
            payload = http_client.get_json(url)
            votos = payload.get("dados", [])

            rotulos = [str(v.get("tipoVoto") or "").strip() for v in votos]

        elif casa_norm == "senado":
            # Se contiver underline, extrai id_materia
            if "_" in id_votacao:
                id_materia, cod_vot = id_votacao.split("_", 1)
            elif id_votacao in _senado_votacao_para_materia:
                id_materia = _senado_votacao_para_materia[id_votacao]
                cod_vot = id_votacao
            else:
                id_materia, cod_vot = id_votacao, id_votacao

            url = f"https://legis.senado.leg.br/dadosabertos/materia/votacoes/{id_materia}"
            payload = http_client.get_json(url)
            votacoes_raw = (
                payload.get("VotacaoMateria", {})
                .get("Materia", {})
                .get("Votacoes", {})
                .get("Votacao", [])
            )

            if isinstance(votacoes_raw, dict):
                votacoes_raw = [votacoes_raw]

            target_votacao = None
            for v in votacoes_raw:
                if str(v.get("CodigoSessaoVotacao")) == str(cod_vot) or len(votacoes_raw) == 1:
                    target_votacao = v
                    break

            votos_list = []
            if target_votacao:
                raw_votos = target_votacao.get("Votos", {}).get("VotoParlamentar", [])
                if isinstance(raw_votos, dict):
                    votos_list = [raw_votos]
                elif isinstance(raw_votos, list):
                    votos_list = raw_votos

            rotulos = [str(v.get("SiglaVoto") or "").strip() for v in votos_list]
    except HttpNetworkError as exc:
        if "404" in str(exc):
            logger.info("Votação %s não encontrada (404). Retornando contagem zerada.", id_votacao)
            return {**contagem, "outros_detalhe": {}, "total": 0}
        raise

    for rotulo in rotulos:
        opcao = _classificar_voto(rotulo)
        contagem[opcao] += 1
        if opcao == "outros":
            chave = rotulo or "(sem rótulo)"
            outros_detalhe[chave] = outros_detalhe.get(chave, 0) + 1

    return {**contagem, "outros_detalhe": outros_detalhe, "total": len(rotulos)}


# ============================================================================
# 5.3 get_congress_veto_sessions
# ============================================================================


def get_congress_veto_sessions(
    ano: int,
    codigo_veto: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista os vetos presidenciais de um ano e os resultados em Sessão Conjunta do Congresso.

    Permite obter a listagem de vetos do ano ou o detalhamento nominal por dispositivo.

    Args:
        ano: Ano de referência do veto.
        codigo_veto: Código específico do veto (Veto.Codigo), quando já conhecido.

    Returns:
        Lista de dicionários: [{
            'codigo_veto': str,
            'numero': str,
            'ano': int,
            'em_tramitacao': bool,
            'data_sessao_conjunta': Optional[str],
            'dispositivos': [{'descricao': str, 'situacao': str, 'tipo_votacao': str}],
            'url_pdf_resultado': Optional[str]
        }]
    """
    results: List[Dict[str, Any]] = []

    if codigo_veto:
        url = f"https://legis.senado.leg.br/dadosabertos/plenario/resultado/veto/{codigo_veto}"
        payload = http_client.get_json(url)
        veto_item = payload.get("ResultadoVetoItemCN", {}).get("Veto", {})

        if not veto_item:
            return []

        materia = veto_item.get("Materia", {})
        numero = str(materia.get("Numero") or veto_item.get("Numero") or "")
        ano_val = int(materia.get("Ano") or ano)
        em_tramitacao = materia.get("EmTramitacao") == "Sim"

        disps_raw = veto_item.get("Dispositivos", {}).get("Dispositivo", [])
        if isinstance(disps_raw, dict):
            disps_raw = [disps_raw]

        dispositivos = []
        data_sessao = None
        for d in disps_raw:
            dispositivos.append(
                {
                    "descricao": d.get("Descricao"),
                    "situacao": d.get("Situacao"),
                    "tipo_votacao": d.get("TipoVotacao"),
                }
            )
            if not data_sessao and d.get("DataSessao"):
                data_sessao = d.get("DataSessao")

        pdf_list = (
            veto_item.get("PdfsResultadoVotacao", {})
            .get("PdfResultadoVotacao", [])
        )
        if isinstance(pdf_list, dict):
            pdf_list = [pdf_list]

        url_pdf = pdf_list[0].get("URL") if pdf_list else None

        results.append(
            {
                "codigo_veto": str(codigo_veto),
                "numero": numero,
                "ano": ano_val,
                "em_tramitacao": em_tramitacao,
                "data_sessao_conjunta": data_sessao,
                "dispositivos": dispositivos,
                "url_pdf_resultado": url_pdf,
            }
        )

    else:
        url = f"https://legis.senado.leg.br/dadosabertos/materia/vetos/{ano}"
        payload = http_client.get_json(url)
        vetos_raw = payload.get("Vetos", {}).get("Veto", [])

        if isinstance(vetos_raw, dict):
            vetos_raw = [vetos_raw]

        for item in vetos_raw:
            cod = str(item.get("Codigo"))
            materia = item.get("Materia", {})
            num = str(materia.get("Numero", ""))
            ano_val = int(materia.get("Ano", ano))
            em_tram = materia.get("EmTramitacao") == "Sim"

            results.append(
                {
                    "codigo_veto": cod,
                    "numero": num,
                    "ano": ano_val,
                    "em_tramitacao": em_tram,
                    "data_sessao_conjunta": None,
                    "dispositivos": [],
                    "url_pdf_resultado": None,
                }
            )

    return results


# ============================================================================
# 5.4 get_plenary_attendance
# ============================================================================


OBSERVACAO_AUSENCIA_INFERIDA = (
    "Ausências inferidas, não registradas: são os deputados do quadro em exercício na data da consulta "
    "que não aparecem na lista de presença da sessão. Suplentes e licenciados, ou quem tomou posse ou saiu "
    "depois da sessão, podem distorcer o resultado; não é registro oficial de falta."
)


def get_plenary_attendance(
    casa: str,
    periodo: str,
    id_evento: Optional[str] = None,
    parlamentar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta presença e infere ausências de parlamentares em sessões deliberativas.

    Na Câmara:
    - Obtém a lista de deputados presentes no evento deliberativo especificado.
    - Infere ausentes comparando com o quadro de deputados em exercício.
    - Permite filtrar por um parlamentar específico (parlamentar_id).

    No Senado:
    - Retorna indicação estruturada da limitação documental da API de Dados Abertos
      (que não expõe endpoint individual de frequência fora de votações nominais).

    Args:
        casa: 'camara' ou 'senado'.
        periodo: Intervalo de datas (ex.: '2024-06-01:2024-06-30' ou '2024-06-05').
        id_evento: ID da sessão deliberativa (obrigatório/descoberto na Câmara).
        parlamentar_id: ID canônico do parlamentar para filtragem pontual.

    Returns:
        Dicionário: {
            'id_evento': Optional[str],
            'data': Optional[str],
            'presentes': [{'id_deputado': str, 'nome': str, 'uf': str, 'partido': str}],
            'ausentes_inferidos': [{'id_deputado': str, 'nome': str, 'uf': str, 'partido': str}],
            'observacao': Optional[str]
        }
    """
    casa_norm = casa.lower().strip()
    if casa_norm == "senado":
        return {
            "id_evento": None,
            "data": None,
            "presentes": [],
            "ausentes_inferidos": [],
            "observacao": (
                "A API de Dados Abertos do Senado Federal (v3/api-docs) não expõe "
                "endpoint dedicado de registro de presença individual em plenário "
                "fora do contexto de votações nominais."
            ),
        }

    if casa_norm != "camara":
        raise ValueError(f"Casa inválida: '{casa}'. Valores permitidos: 'camara' ou 'senado'.")

    # Localização do id_evento caso não informado diretamente
    evento_id_final = id_evento
    data_evento = None

    if not evento_id_final:
        # Extrai datas do período
        datas = re.findall(r"\d{4}-\d{2}-\d{2}", periodo)
        dt_inicio = datas[0] if datas else periodo.split(":")[0]
        dt_fim = datas[-1] if datas else dt_inicio

        eventos_url = "https://dadosabertos.camara.leg.br/api/v2/eventos"
        eventos_payload = http_client.get_json(
            eventos_url,
            params={
                "codTipoEvento": 110,  # Sessão Deliberativa
                "dataInicio": dt_inicio,
                "dataFim": dt_fim,
            },
        )
        eventos_list = eventos_payload.get("dados", [])

        # Prioriza sessões plenárias (órgão PLEN)
        target_evento = None
        for ev in eventos_list:
            orgaos = ev.get("orgaos", [])
            if any(o.get("sigla") == "PLEN" for o in orgaos):
                target_evento = ev
                break
        if not target_evento and eventos_list:
            target_evento = eventos_list[0]

        if target_evento:
            evento_id_final = str(target_evento.get("id"))
            data_evento = str(target_evento.get("dataHoraInicio", ""))[:10]
        else:
            return {
                "id_evento": None,
                "data": None,
                "presentes": [],
                "ausentes_inferidos": [],
                "observacao": f"Nenhuma sessão deliberativa encontrada para o período '{periodo}'.",
            }
    else:
        # Se id_evento foi fornecido diretamente, tenta recuperar a data da sessão
        try:
            ev_detalhe = http_client.get_json(f"https://dadosabertos.camara.leg.br/api/v2/eventos/{evento_id_final}")
            data_raw = ev_detalhe.get("dados", {}).get("dataHoraInicio", "")
            data_evento = str(data_raw)[:10] if data_raw else None
        except Exception:
            data_evento = None

    # 1. Consulta deputados que registraram presença no evento
    presentes_url = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{evento_id_final}/deputados"
    presentes_payload = http_client.get_json(presentes_url)
    presentes_raw = presentes_payload.get("dados", [])

    presentes: List[Dict[str, Any]] = [
        {
            "id_deputado": str(d.get("id")),
            "nome": d.get("nome"),
            "uf": d.get("siglaUf"),
            "partido": d.get("siglaPartido"),
        }
        for d in presentes_raw
    ]

    # 2. Consulta quadro total de deputados em exercício para inferir faltas
    deputados_url = "https://dadosabertos.camara.leg.br/api/v2/deputados"
    deputados_payload = http_client.get_json(deputados_url, params={"itens": 1000})
    deputados_total = deputados_payload.get("dados", [])

    ids_presentes = {p["id_deputado"] for p in presentes}

    ausentes_inferidos: List[Dict[str, Any]] = [
        {
            "id_deputado": str(dep.get("id")),
            "nome": dep.get("nome"),
            "uf": dep.get("siglaUf"),
            "partido": dep.get("siglaPartido"),
        }
        for dep in deputados_total
        if str(dep.get("id")) not in ids_presentes
    ]

    # 3. Filtragem pontual por parlamentar_id se solicitado
    if parlamentar_id:
        p_id_str = str(parlamentar_id).strip()
        presentes = [p for p in presentes if p["id_deputado"] == p_id_str]
        ausentes_inferidos = [a for a in ausentes_inferidos if a["id_deputado"] == p_id_str]

    return {
        "id_evento": evento_id_final,
        "data": data_evento,
        "presentes": presentes,
        "ausentes_inferidos": ausentes_inferidos,
        "observacao": OBSERVACAO_AUSENCIA_INFERIDA,
    }

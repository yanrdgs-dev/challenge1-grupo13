"""Nó Agregador de Veredito da Matéria (Article Aggregator).

Atende aos critérios da Task 4.4:
- Módulo implementado em src/agents/nodes/article_aggregator.py.
- Regra de agregação de status do artigo (classificação como VERDADEIRO, ENGANOSO, FALSO ou INCONCLUSIVO).
- Geração de resumo executivo em 2 a 3 parágrafos explicando os pontos confirmados e os desmentidos.
- Inclusão de percentual de confiabilidade calculado com base na proporção das afirmações analisadas.
"""

import logging
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from src.core.llm_client import LLMClient

logger = logging.getLogger("Agents.Nodes.ArticleAggregator")

ARTICLE_AGGREGATOR_SYSTEM_PROMPT = """Você é um editor sênior de fact-checking jornalístico.
Sua missão é produzir um resumo executivo estritamente técnico, neutro e impessoal sobre a confiabilidade global de uma matéria jornalística, avaliando o conjunto de alegações atômicas auditadas contra bases de dados públicas oficiais.

REGRAS DE FORMATAÇÃO E ESTRUTURA:
1. O texto DEVE conter EXATAMENTE 2 a 3 parágrafos (separados por uma linha em branco dupla).
2. Parágrafo 1: Apresente o resultado global da apuração, o total de alegações analisadas e a classificação editorial do artigo (VERDADEIRO, ENGANOSO, FALSO ou INCONCLUSIVO).
3. Parágrafo 2: Destaque com clareza os pontos que foram confirmados por dados públicos oficiais (se houver).
4. Parágrafo 3: Destaque os pontos que foram desmentidos ou distorcidos pelas evidências oficiais (se houver), ou comente sobre alegações vagas/inconclusivas.
5. Seja rigorosamente neutro, objetivo e baseado exclusivamente nas evidências relatadas.
"""


class ArticleAggregationResult(BaseModel):
    """Resultado executivo consolidado da confiabilidade de uma matéria jornalística."""

    overall_status: str = Field(
        ...,
        description="Classificação global da matéria (VERDADEIRO, ENGANOSO, FALSO, INCONCLUSIVO).",
    )
    reliability_score: float = Field(
        ...,
        description="Percentual de confiabilidade (0.0 a 100.0) baseado na proporção de alegações confirmadas.",
    )
    executive_summary: str = Field(
        ...,
        description="Síntese executiva da matéria em 2 a 3 parágrafos.",
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métricas quantitativas da análise (total, verdadeiras, falsas, inconclusivas).",
    )
    confirmed_points: List[str] = Field(
        default_factory=list,
        description="Lista de alegações confirmadas como verdadeiras.",
    )
    refuted_points: List[str] = Field(
        default_factory=list,
        description="Lista de alegações desmentidas ou comprovadas falsas.",
    )
    inconclusive_points: List[str] = Field(
        default_factory=list,
        description="Lista de alegações subespecificadas ou inconclusivas.",
    )


def _build_deterministic_summary(
    overall_status: str,
    reliability_score: float,
    confirmed_points: List[str],
    refuted_points: List[str],
    inconclusive_points: List[str],
    article_title: Optional[str] = None,
) -> str:
    """Gera síntese executiva determinística com exatamente 2 a 3 parágrafos."""
    total = len(confirmed_points) + len(refuted_points) + len(inconclusive_points)
    title_suffix = f" intitulada \"{article_title}\"" if article_title else ""

    if total == 0:
        return (
            f"A análise da matéria jornalística{title_suffix} não identificou nenhuma alegação factual atômica verificável contra bases de dados oficiais.\n\n"
            "Diante da ausência de dados passíveis de auditoria pública direta, o conteúdo é classificado como inconclusivo para fins de checagem automatizada."
        )

    # Parágrafo 1: Visão Geral e Veredito Global
    p1 = (
        f"A auditoria factual da matéria jornalística{title_suffix} analisou {total} afirmações centrais contra os registros oficiais do Congresso Nacional e órgãos públicos. "
        f"A publicação foi classificada globalmente como {overall_status}, registrando um índice de confiabilidade de {reliability_score}% com base na proporção das declarações sustentadas por evidências públicas."
    )

    # Parágrafo 2: Pontos Confirmados
    if confirmed_points:
        points_str = "; ".join(f"\"{p}\"" for p in confirmed_points[:3])
        p2 = (
            f"Entre os pontos confirmados pelas bases públicas oficiais, verificou-se a procedência de: {points_str}. "
            f"Tais afirmações encontram respaldo documental direto nos dados abertos governamentais."
        )
    else:
        p2 = (
            "Nenhuma das afirmações analisadas na matéria obteve confirmação perante as bases de dados e registros normativos oficiais consultados."
        )

    # Parágrafo 3: Pontos Desmentidos e Inconclusivos
    if refuted_points:
        refuted_str = "; ".join(f"\"{p}\"" for p in refuted_points[:3])
        p3 = (
            f"Em contrapartida, foram desmentidas alegações centrais veiculadas no texto, notadamente: {refuted_str}. "
            f"Essas declarações contrariam expressamente a legislação vigente ou os registros transacionais dos portais de transparência, comprometendo a precisão factual da reportagem."
        )
    elif inconclusive_points:
        p3 = (
            f"Adicionalmente, {len(inconclusive_points)} alegação(ões) foi(ram) classificada(s) como inconclusiva(s) por falta de parâmetros objetivos e ancoragem factual suficiente nos registros disponíveis."
        )
    else:
        p3 = (
            "Não foram identificadas divergências, distorções ou contradições factuais em relação aos dados públicos auditados ao longo da matéria."
        )

    return f"{p1}\n\n{p2}\n\n{p3}"


class ArticleAggregator:
    """Componente responsável pela agregação de vereditos e síntese de confiabilidade de notícias."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Inicializa o agregador com cliente LLM opcional."""
        self.llm_client = llm_client

    def aggregate(
        self,
        claims: List[Any],
        article_title: Optional[str] = None,
    ) -> ArticleAggregationResult:
        """Processa as alegações verificadas de uma matéria e devolve o veredito executivo agregado.

        Args:
            claims: Lista de alegações atômicas verificadas (dict ou objetos Pydantic).
            article_title: Título opcional da matéria para contextualização do resumo.

        Returns:
            ArticleAggregationResult com métricas, status e resumo executivo.
        """
        confirmed_points: List[str] = []
        refuted_points: List[str] = []
        inconclusive_points: List[str] = []

        for item in claims:
            # Suporte para dicionários e objetos
            claim_text = item.get("claim", "") if isinstance(item, dict) else getattr(item, "claim", str(item))
            verdict = (
                item.get("verdict", "INCONCLUSIVO")
                if isinstance(item, dict)
                else getattr(item, "verdict", "INCONCLUSIVO")
            ).upper()

            if "VERDADEIRO" in verdict:
                confirmed_points.append(claim_text)
            elif "FALSO" in verdict:
                refuted_points.append(claim_text)
            else:
                inconclusive_points.append(claim_text)

        total_claims = len(confirmed_points) + len(refuted_points) + len(inconclusive_points)
        true_count = len(confirmed_points)
        false_count = len(refuted_points)
        inconclusive_count = len(inconclusive_points)

        # Regra de classificação de status global
        if total_claims == 0:
            overall_status = "INCONCLUSIVO"
            reliability_score = 0.0
        elif false_count > 0:
            if true_count > 0:
                overall_status = "ENGANOSO"
            else:
                overall_status = "FALSO"
            reliability_score = round((true_count / total_claims) * 100, 1)
        elif true_count > 0:
            overall_status = "VERDADEIRO"
            reliability_score = round((true_count / total_claims) * 100, 1)
        else:
            overall_status = "INCONCLUSIVO"
            reliability_score = 0.0

        metrics = {
            "total_claims": total_claims,
            "true_claims": true_count,
            "false_claims": false_count,
            "inconclusive_claims": inconclusive_count,
            "reliability_percentage": reliability_score,
        }

        # Tentativa de síntese via LLM caso disponível
        executive_summary: Optional[str] = None
        if self.llm_client is not None and total_claims > 0:
            try:
                prompt_content = (
                    f"MATÉRIA: \"{article_title or 'Notícia analisada'}\"\n"
                    f"STATUS GLOBAL CALCULADO: {overall_status} (Confiabilidade: {reliability_score}%)\n"
                    f"PONTOS CONFIRMADOS: {confirmed_points}\n"
                    f"PONTOS DESMENTIDOS: {refuted_points}\n"
                    f"PONTOS INCONCLUSIVOS: {inconclusive_points}\n\n"
                    "Gere a síntese executiva de exatamente 2 a 3 parágrafos:"
                )
                full_prompt = f"{ARTICLE_AGGREGATOR_SYSTEM_PROMPT}\n\n{prompt_content}"
                raw_llm = self.llm_client.generate(full_prompt).strip()
                paragraphs = [p.strip() for p in raw_llm.split("\n\n") if p.strip()]
                if 2 <= len(paragraphs) <= 3:
                    executive_summary = "\n\n".join(paragraphs)
                else:
                    logger.info("Resposta do LLM não conteve entre 2 e 3 parágrafos. Usando fallback estruturado.")
            except Exception as e:
                logger.warning("Falha na geração de resumo via LLM: %s. Utilizando gerador determinístico.", e)

        if not executive_summary:
            executive_summary = _build_deterministic_summary(
                overall_status=overall_status,
                reliability_score=reliability_score,
                confirmed_points=confirmed_points,
                refuted_points=refuted_points,
                inconclusive_points=inconclusive_points,
                article_title=article_title,
            )

        return ArticleAggregationResult(
            overall_status=overall_status,
            reliability_score=reliability_score,
            executive_summary=executive_summary,
            metrics=metrics,
            confirmed_points=confirmed_points,
            refuted_points=refuted_points,
            inconclusive_points=inconclusive_points,
        )


def article_aggregator_node(
    claims: Optional[List[Union[Dict[str, Any], Any]]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    article_title: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
) -> ArticleAggregationResult:
    """Nó do agente responsável por agregar o veredito final e confiabilidade de uma reportagem.

    Compatível com chamadas isoladas por lista de claims ou dicionários de estado de pipeline.

    Args:
        claims: Lista opcional de alegações auditadas.
        state: Dicionário opcional de estado do pipeline.
        article_title: Título opcional da matéria jornalística.
        llm_client: Instância opcional de LLMClient.

    Returns:
        Instância de ArticleAggregationResult com métricas, status e resumo executivo.
    """
    target_claims: List[Any] = []
    title: Optional[str] = article_title

    if state is not None and isinstance(state, dict):
        if not title:
            title = state.get("title")
        raw_state_claims = state.get("claims") or state.get("atomic_claims") or []
        if isinstance(raw_state_claims, list):
            target_claims = raw_state_claims
    elif claims is not None and isinstance(claims, list):
        target_claims = claims

    aggregator = ArticleAggregator(llm_client=llm_client)
    result = aggregator.aggregate(claims=target_claims, article_title=title)

    # Se a chamada foi realizada com dicionário de estado, enriquece o estado
    if state is not None and isinstance(state, dict):
        state["article_aggregation"] = result.model_dump()
        state["overall_status"] = result.overall_status
        state["reliability_score"] = result.reliability_score
        state["executive_summary"] = result.executive_summary

    return result

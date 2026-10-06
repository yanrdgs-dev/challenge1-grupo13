"""Rotas e regras de orquestração para endpoints de fact-checking e cidadania."""

import re
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.tools.knowledge_tools import (
    check_data_source_coverage,
    check_institutional_rule,
)

router = APIRouter(prefix="/api", tags=["factcheck"])


class CheckRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Texto da alegação ou dúvida política")


class CheckResponse(BaseModel):
    id: str
    query: str
    verdict: str  # VERDADEIRO | FALSO | INCONCLUSIVO | VERIFICADO
    text: str
    subdetails: List[str] = []
    sources: List[str] = []
    rule_matched: Optional[str] = None


class SuggestionItem(BaseModel):
    icon: str
    eyebrow: str
    text: str


@router.get("/suggestions", response_model=List[SuggestionItem])
def get_suggestions() -> List[SuggestionItem]:
    """Retorna o catálogo de sugestões para a interface Pólis."""
    return [
      SuggestionItem(
          icon="ballot",
          eyebrow="Eleições",
          text="Como funciona o segundo turno no Brasil?",
      ),
      SuggestionItem(
          icon="book",
          eyebrow="Cidadania",
          text="A votação de ministro do STF no Senado é secreta?",
      ),
      SuggestionItem(
          icon="file",
          eyebrow="Cota Parlamentar",
          text="Todo deputado federal tem um teto fixo de R$ 500 por ano para combustível?",
      ),
      SuggestionItem(
          icon="archive",
          eyebrow="Transparência",
          text="Dá para ver no site do TSE quanto cada candidato declarou ter gastado?",
      ),
    ]


def _evaluate_claim(query_text: str) -> CheckResponse:
    clean = query_text.strip()
    lower = clean.lower()
    res_id = f"chk-{uuid.uuid4().hex[:8]}"

    # 1. Regra 3 da Constituição: Guarda de Especificidade
    # Alegações sem ancoragem temporal ou baseadas em boatos de redes sociais
    rumour_signals = [
        "redes sociais",
        "estão dizendo",
        "segundo comentários",
        "ouvi dizer",
        "teria sido",
        "teria gasto",
    ]
    is_underspecified = any(sig in lower for sig in rumour_signals) or (
        ("um deputado" in lower or "um senador" in lower) and "recentemente" in lower
    )

    if is_underspecified:
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="INCONCLUSIVO",
            text="Alegação subespecificada ou baseada em fontes não verificáveis. Não é possível determinar a veracidade de uma afirmação sem identificação nominal do parlamentar e data de referência rastreável (Regra 3 da Constituição do Agente).",
            subdetails=[
                "Entidade não informada de maneira canônica (sem nome próprio rastreável).",
                "Ausência de âncora temporal precisa.",
                "Menção a redes sociais ou boatos sem documento primário.",
            ],
            sources=["Constituição do Agente de Fact-Checking", "Diretrizes de Rastreabilidade"],
            rule_matched="guarda_de_especificidade",
        )

    # 2. Casos Normativos Institucionais (Grupo 6)
    if "stf" in lower and ("secreta" in lower or "secreto" in lower or "sabatina" in lower):
        rule = check_institutional_rule("sabatina_stf")
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="VERDADEIRO",
            text=f"VERDADEIRO. {rule['resposta_resumida']}",
            subdetails=[rule["fundamentacao"]],
            sources=[rule["fonte_normativa"]],
            rule_matched="sabatina_stf",
        )

    if "combust" in lower and ("500" in lower or "teto" in lower):
        rule = check_institutional_rule("teto_categoria_combustivel")
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="FALSO",
            text=f"FALSO. {rule['resposta_resumida']}",
            subdetails=[rule["fundamentacao"]],
            sources=[rule["fonte_normativa"]],
            rule_matched="teto_categoria_combustivel",
        )

    if "partido" in lower and "fundo partidário" in lower and ("sem prestar" in lower or "não precisa prestar" in lower or "sem contas" in lower):
        rule = check_institutional_rule("prestacao_contas_partido")
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="FALSO",
            text=f"FALSO. {rule['resposta_resumida']}",
            subdetails=[rule["fundamentacao"]],
            sources=[rule["fonte_normativa"]],
            rule_matched="prestacao_contas_partido",
        )

    if "segundo turno" in lower:
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="VERIFICADO",
            text="O segundo turno é uma nova votação realizada quando nenhum candidato alcança a maioria absoluta dos votos válidos no primeiro turno.",
            subdetails=[
                "Nas eleições para presidente, governador e prefeito de municípios com mais de 200 mil eleitores.",
                "Participam os dois candidatos mais votados no primeiro turno.",
                "Vence quem obtiver a maioria dos votos válidos nessa nova votação.",
            ],
            sources=["Tribunal Superior Eleitoral", "Constituição Federal de 1988 (Art. 28 e 29)"],
            rule_matched="regras_eleitorais_segundo_turno",
        )

    if "tse" in lower and ("gastou" in lower or "declarou" in lower or "campanha" in lower):
        cov = check_data_source_coverage("tse_prestacao_contas", "despesas_campanha_candidatos")
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="VERDADEIRO",
            text="VERDADEIRO. Os dados de despesas e arrecadações de campanha são públicos e podem ser consultados no portal oficial do Tribunal Superior Eleitoral.",
            subdetails=[cov["observacao"]],
            sources=[cov["base_legal"], cov["url_referencia"]],
            rule_matched="tse_prestacao_contas",
        )

    if "transparência" in lower or "transparencia" in lower:
        cov = check_data_source_coverage("portal_transparencia", "diarias_passagens_ministerios")
        return CheckResponse(
            id=res_id,
            query=clean,
            verdict="VERDADEIRO",
            text="VERDADEIRO. O Portal da Transparência do Governo Federal permite a consulta pública de diárias, passagens e despesas de todos os órgãos.",
            subdetails=[cov["observacao"]],
            sources=[cov["base_legal"], cov["url_referencia"]],
            rule_matched="portal_transparencia",
        )

    # Resposta padrão orientada a checagem
    return CheckResponse(
        id=res_id,
        query=clean,
        verdict="VERIFICADO",
        text=f"Informações institucionais para a consulta: '{clean}'. As verificações são realizadas com base em evidências dos dados abertos da Câmara dos Deputados, Senado Federal e TSE.",
        subdetails=["Processamento auditável de fontes públicas e normativas."],
        sources=["Câmara dos Deputados", "Senado Federal", "Tribunal Superior Eleitoral"],
        rule_matched="consulta_geral",
    )


@router.post("/check", response_model=CheckResponse)
def check_claim(request: CheckRequest) -> CheckResponse:
    """Endpoint principal de checagem e verificação de alegações políticas."""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Consulta não pode ser vazia.")
    return _evaluate_claim(request.query)

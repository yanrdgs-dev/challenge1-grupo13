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

from src.guardrails.service import FactCheckingGuardrails

router = APIRouter(prefix="/api", tags=["factcheck"])
guardrails_service = FactCheckingGuardrails()


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
    audit_passed: bool = True
    audit_note: Optional[str] = None


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


@router.post("/check", response_model=CheckResponse)
def check_claim(request: CheckRequest) -> CheckResponse:
    """Endpoint principal de checagem blindado com NeMo Guardrails."""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Consulta não pode ser vazia.")

    result = guardrails_service.evaluate(request.query)
    return CheckResponse(
        id=result.id,
        query=result.query,
        verdict=result.verdict,
        text=result.text,
        subdetails=result.subdetails,
        sources=result.sources,
        rule_matched=result.rule_matched,
        audit_passed=result.audit_passed,
        audit_note=result.audit_note,
    )


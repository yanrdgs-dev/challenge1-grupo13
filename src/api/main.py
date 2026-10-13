"""Aplicação FastAPI para a API de Fact-Checking Político."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.factcheck import router as factcheck_router
from src.api.routes.ingestion import router as ingestion_router

app = FastAPI(
    title="Pólis Fact-Checking API",
    description="API do Agente de Fact-Checking Político com evidências oficiais e rastreáveis.",
    version="1.0.0",
)

# Habilita CORS para conexão fluida com a interface Vite
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(factcheck_router)
app.include_router(ingestion_router)


@app.get("/api/health")
def health_check():
    """Endpoint de monitoramento de integridade e saúde da aplicação."""
    return {
        "status": "ok",
        "service": "polis-fact-checking-api",
        "version": "1.0.0",
        "tools_available": [
            "check_institutional_rule",
            "check_data_source_coverage",
            "get_proposition_tramitation_history",
            "check_bill_apensamentos",
        ],
    }

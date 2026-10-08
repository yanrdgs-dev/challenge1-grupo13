"""
src/ingestion/extractors.py

Módulo de extração de dados via Web Scraping e download estruturado dos portais:
1. Dados Abertos - Câmara dos Deputados
2. Dados Abertos - Senado Federal
3. Dados Abertos - Tribunal Superior Eleitoral (TSE)
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any 


# ----------------------------------------------------------------------
# 1. SCRAPING / EXTRAÇÃO: DADOS ABERTOS - CÂMARA DOS DEPUTADOS
# ----------------------------------------------------------------------
def scrape_dados_abertos_camara(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Coleta dados diretamente do portal de Dados Abertos da Câmara.
    Extrai informações de proposições e ementas legislativas.
    """
    url = "https://dadosabertos.camara.leg.br/api/v2/proposicoes"
    params = {
        "ordem": "DESC",
        "ordenarPor": "id",
        "itens": limit
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        data = response.json()
        proposicoes = []
        for item in data.get("dados", []):
            proposicoes.append({
                "id_fonte": f"CAMARA_{item['id']}",
                "casa": "Camara dos Deputados",
                "tipo": item["siglaTipo"],
                "numero": item["numero"],
                "ano": item["ano"],
                "texto_ementa": item["ementa"],
                "url": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={item['id']}"
            })
        return proposicoes
    return []


# ----------------------------------------------------------------------
# 2. SCRAPING / EXTRAÇÃO: DADOS ABERTOS - SENADO FEDERAL
# ----------------------------------------------------------------------
def scrape_dados_abertos_senado(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Coleta dados do portal de Dados Abertos do Senado Federal.
    Extrai matérias, projetos e ementas dos senadores.
    """
    url = "https://legis.senado.leg.br/dadosabertos/materia/atualizadas"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    materias_formatadas = []
    
    if response.status_code == 200:
        try:
            data = response.json()
            # Navega na estrutura de resposta do Senado
            lista_materias = data.get("ListaMateriasAtualizadas", {}).get("Materias", {}).get("Materia", [])
            
            # Limita a quantidade para o lote
            for item in lista_materias[:limit]:
                identificacao = item.get("IdentificacaoMateria", {})
                materias_formatadas.append({
                    "id_fonte": f"SENADO_{identificacao.get('CodigoMateria')}",
                    "casa": "Senado Federal",
                    "tipo": identificacao.get("SiglaSubtipoMateria"),
                    "numero": identificacao.get("NumeroMateria"),
                    "ano": identificacao.get("AnoMateria"),
                    "texto_ementa": item.get("EmentaMateria", ""),
                    "url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{identificacao.get('CodigoMateria')}"
                })
        except Exception as e:
            print(f"Erro ao processar dados do Senado: {e}")
            
    return materias_formatadas


# ----------------------------------------------------------------------
# 3. SCRAPING / EXTRAÇÃO: DADOS ABERTOS - TSE (TRIBUNAL SUPERIOR ELEITORAL)
# ----------------------------------------------------------------------
def scrape_dados_abertos_tse() -> List[Dict[str, Any]]:
    """
    Realiza o scraping na página principal do Repositório de Dados Abertos do TSE
    para mapear e baixar os conjuntos de dados de Candidatos e Eleições.
    """
    portal_url = "https://dadosabertos.tse.jus.br/dataset"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    candidatos_data = []
    
    try:
        response = requests.get(portal_url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Procura os cards/links de conjuntos de dados no portal CKAN do TSE
            datasets = soup.find_all("li", class_="dataset-item")
            
            for ds in datasets[:10]: # Exemplo pegando os primeiros datasets
                title_elem = ds.find("h2", class_="dataset-heading")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.find("a")["href"] if title_elem.find("a") else ""
                    
                    candidatos_data.append({
                        "id_fonte": f"TSE_{len(candidatos_data)+1}",
                        "fonte": "TSE - Dados Abertos",
                        "titulo_conjunto": title,
                        "url_conjunto": f"https://dadosabertos.tse.jus.br{link}" if link.startswith("/") else link
                    })
    except Exception as e:
        print(f"Erro no scraping do portal do TSE: {e}")
        
    return candidatos_data


# ----------------------------------------------------------------------
# EXECUÇÃO DE TESTE / PIPELINE DE EXTRAÇÃO
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("=== COLETANDO DADOS ABERTOS: CÂMARA DOS DEPUTADOS ===")
    dados_camara = scrape_dados_abertos_camara(limit=3)
    for d in dados_camara:
        print(f"[{d['casa']}] {d['tipo']} {d['numero']}/{d['ano']} -> {d['texto_ementa'][:80]}...")

    print("\n=== COLETANDO DADOS ABERTOS: SENADO FEDERAL ===")
    dados_senado = scrape_dados_abertos_senado(limit=3)
    for d in dados_senado:
        print(f"[{d['casa']}] {d['tipo']} {d['numero']}/{d['ano']} -> {d['texto_ementa'][:80]}...")

    print("\n=== COLETANDO DADOS ABERTOS: TSE ===")
    dados_tse = scrape_dados_abertos_tse()
    for d in dados_tse[:3]:
        print(f"[{d['fonte']}] Dataset: {d['titulo_conjunto']} -> URL: {d['url_conjunto']}")

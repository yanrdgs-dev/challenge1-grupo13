import os
import sys
import time
import zipfile
import urllib.request
import ssl
from pathlib import Path

# Configura contexto SSL permissivo para conexões públicas
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def download_file(url: str, dest_path: Path, desc: str) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > 1000:
        print(f"[PULANDO] {desc} já existe ({dest_path.stat().st_size / 1024:.1f} KB).")
        return True

    print(f"[BAIXANDO] {desc} de {url}...")
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        start = time.time()
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            content = resp.read()
            with open(dest_path, "wb") as f:
                f.write(content)
        elapsed = time.time() - start
        print(f"✓ Concluído: {desc} ({len(content) / 1024 / 1024:.2f} MB em {elapsed:.1f}s)")
        return True
    except Exception as e:
        print(f"✗ Erro ao baixar {desc}: {e}")
        return False

def download_and_extract_zip(url: str, extract_dir: Path, expected_file_prefix: str, desc: str) -> bool:
    extract_dir.mkdir(parents=True, exist_ok=True)
    zip_temp = extract_dir / "temp.zip"
    
    # Se já temos o arquivo descompactado no diretório
    existing = list(extract_dir.glob(f"{expected_file_prefix}*.csv"))
    if existing and existing[0].stat().st_size > 1000:
        print(f"[PULANDO] {desc} já descompactado ({existing[0].name}).")
        return True

    print(f"[BAIXANDO ZIP] {desc}...")
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        start = time.time()
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            content = resp.read()
            with open(zip_temp, "wb") as f:
                f.write(content)
        
        with zipfile.ZipFile(zip_temp, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        zip_temp.unlink(missing_ok=True)
        elapsed = time.time() - start
        print(f"✓ Descompactado com sucesso: {desc} em {elapsed:.1f}s")
        return True
    except Exception as e:
        print(f"✗ Falha em {desc}: {e}")
        zip_temp.unlink(missing_ok=True)
        return False

def main():
    print("=" * 65)
    print(" INICIANDO DOWNLOAD AUTOMATIZADO DAS BASES PÚBLICAS (CÂMARA & SENADO)")
    print("=" * 65)

    base_dir = Path("datasets")

    # 1. CÂMARA DOS DEPUTADOS - CEAP (Cotas 2022 a 2026)
    ceap_dir = base_dir / "camara" / "ceap"
    for ano in [2022, 2023, 2024, 2025, 2026]:
        url = f"https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
        download_and_extract_zip(url, ceap_dir, f"Ano-{ano}", f"Câmara CEAP {ano}")

    # 2. CÂMARA DOS DEPUTADOS - Deputados (Cadastro)
    dep_path = base_dir / "camara" / "cadastro" / "deputados.csv"
    download_file("https://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv", dep_path, "Câmara - Cadastro Deputados")

    # 3. CÂMARA DOS DEPUTADOS - Votações e Votos (2024)
    vot_dir = base_dir / "camara" / "votacoes"
    download_file("https://dadosabertos.camara.leg.br/arquivos/votacoes/csv/votacoes-2024.csv", vot_dir / "votacoes-2024.csv", "Câmara - Votações 2024")
    download_file("https://dadosabertos.camara.leg.br/arquivos/votacoesVotos/csv/votacoesVotos-2024.csv", vot_dir / "votacoesVotos-2024.csv", "Câmara - Votações Votos 2024")

    # 4. CÂMARA DOS DEPUTADOS - Proposições e Autores (2024)
    prop_dir = base_dir / "camara" / "proposicoes"
    download_file("https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-2024.csv", prop_dir / "proposicoes-2024.csv", "Câmara - Proposições 2024")

    prop_aut_dir = base_dir / "camara" / "proposicoes_autores"
    download_file("https://dadosabertos.camara.leg.br/arquivos/proposicoesAutores/csv/proposicoesAutores-2024.csv", prop_aut_dir / "proposicoesAutores-2024.csv", "Câmara - Proposições Autores 2024")

    # 5. SENADO FEDERAL - Cadastro de Senadores
    sen_path = base_dir / "senado" / "cadastro" / "senadores.csv"
    download_file("https://legis.senado.leg.br/dadosabertos/senador/lista/atual.csv", sen_path, "Senado - Cadastro Senadores")

    # 6. SENADO FEDERAL - CEAPS (Cota dos Senadores 2022 a 2026)
    sen_ceaps_dir = base_dir / "senado" / "ceaps"
    for ano in [2022, 2023, 2024, 2025, 2026]:
        url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}/csv"
        dest = sen_ceaps_dir / f"ceaps_{ano}.csv"
        download_file(url, dest, f"Senado CEAPS {ano}")

    print("\n" + "=" * 65)
    print(" DOWNLOAD DAS BASES PÚBLICAS CONCLUÍDO COM SUCESSO!")
    print("=" * 65)

if __name__ == "__main__":
    main()

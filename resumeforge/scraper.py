import os
import re
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from pathlib import Path


def prepare_url(url: str) -> str:
    """
    Identifica a plataforma e prepara a URL.
    Se for LinkedIn, converte para a página de visualização pública (essencial para evitar o 404).
    """
    if "linkedin.com" in url:
        # Captura o ID numérico da vaga na URL do LinkedIn
        match = re.search(r'(?:jobs/view/|jobId=|currentJobId=)(\d+)', url)
        if match:
            job_id = match.group(1)
            # Retorna a URL de visualização pública padrão (muito mais segura contra bloqueios)
            return f"https://www.linkedin.com/jobs/view/{job_id}"
            
    return url


def scrape_job_url(url: str) -> str:
    """Acessa a vaga de forma resiliente usando a API do Scrape.do com a URL pública corrigida."""
    token = os.getenv("SCRAPEDO_TOKEN")
    
    if not token:
        print("Aviso: Chave SCRAPEDO_TOKEN não encontrada no .env. Usando requisição direta.")
        return scrape_job_direct_fallback(url)

    target_url = prepare_url(url)
    print(f"Buscando vaga via Scrape.do em: {target_url}")

    # CONFIGURAÇÃO DE SUCESSO PARA O LINKEDIN:
    # - super=true: Ativa proxies residenciais para passar pelo bloqueio
    # - render=true: Necessário para a página pública padrão carregar todo o conteúdo via JS
    api_url = f"https://api.scrape.do?token={token}&url={quote(target_url)}&super=true&render=true"

    try:
        # Timeout ligeiramente maior porque proxies residenciais e renderização JS levam mais tempo
        response = requests.get(api_url, timeout=45)
        
        if response.status_code != 200:
            print(f"Erro na API Scrape.do (Status {response.status_code}): {response.text}")
            return ""

        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Extração do Título da Vaga
        titulo = ""
        seletores_titulo = [
            '.top-card-layout__title',                      # LinkedIn Público
            'h1.top-card-layout__title',
            '.job-details-jobs-unified-top-card__job-title', # LinkedIn Logado
            'h1'                                            # Fallback genérico
        ]
        for seletor in seletores_titulo:
            elemento_titulo = soup.select_one(seletor)
            if elemento_titulo:
                texto = elemento_titulo.get_text()
                if texto.strip() and "linkedin" not in texto.lower():
                    titulo = texto.strip()
                    break

        # 2. Extração do Conteúdo (Sobre a Vaga)
        sobre_vaga = ""
        seletores_sobre = [
            '.description__text',                           # LinkedIn Público (Classe principal)
            '.show-more-less-html__markup',                  # Conteúdo interno da descrição
            '#job-details',                                 # LinkedIn Logado
            '.jobs-description'
        ]
        for seletor in seletores_sobre:
            elemento_sobre = soup.select_one(seletor)
            if elemento_sobre:
                sobre_vaga = str(elemento_sobre)
                break

        # Se falhar nos seletores específicos, limpa e retorna a página inteira
        if not titulo and not sobre_vaga:
            print("Seletores falharam. Retornando fallback de texto limpo.")
            return clean_html(html_content)

        sobre_vaga_limpo = clean_html(sobre_vaga) if sobre_vaga else ""
        titulo_final = titulo if titulo else "Título não identificado"

        return f"VAGA: {titulo_final}\n\nSOBRE A VAGA:\n{sobre_vaga_limpo}"

    except Exception as e:
        print(f"Erro na raspagem com Scrape.do: {e}")
        return ""


def scrape_job_direct_fallback(url: str) -> str:
    """Fallback simples se você estiver sem créditos ou sem token."""
    try:
        target_url = prepare_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(target_url, headers=headers, timeout=15)
        return clean_html(response.text)
    except Exception as e:
        print(f"Erro no fallback direto: {e}")
        return ""

def clean_html(html: str) -> str:
    """Remove tags inúteis e corta propagandas/termos de privacidade do final para acelerar a IA."""
    if not html:
        return ""
    soup = BeautifulSoup(html, 'html.parser')

    # 1. Remove elementos visuais e interativos que não trazem conteúdo real da vaga
    for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript', 'button', 'svg', 'form']):
        tag.decompose()

    # 2. Extrai o texto limpo
    text = soup.get_text(separator='\n', strip=True)
    
    # 3. Organiza quebras de linhas
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    texto_limpo = '\n'.join(lines)

    # 4. CORTE DE RUÍDO (A mágica da velocidade):
    # Identifica onde começam os textos institucionais ou avisos de privacidade e corta dali para baixo.
    padroes_de_corte = [
        r"(?i)how\s+jobgether\s+works",
        r"(?i)why\s+apply\s+through",
        r"(?i)data\s+privacy\s+notice",
        r"(?i)sobre\s+o\s+jobgether",
        r"(?i)politica\s+de\s+privacidade"
    ]
    
    for padrao in padroes_de_corte:
        match = re.search(padrao, texto_limpo)
        if match:
            # Corta o texto exatamente onde o padrão foi encontrado
            texto_limpo = texto_limpo[:match.start()].strip()
            break # Interrompe no primeiro corte identificado

    return texto_limpo

def read_job_from_file(filepath: str) -> str:
    """Lê descrição da vaga de um arquivo de texto local."""
    return Path(filepath).read_text(encoding='utf-8')


def scrape_job(url: str) -> str:
    """Wrapper síncrono para scrape_job_url."""
    return scrape_job_url(url)
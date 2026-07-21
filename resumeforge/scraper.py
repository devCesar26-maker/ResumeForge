import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path


def prepare_url(url: str) -> str:
    """
    Identifica se é uma URL do LinkedIn e a converte para a versão
    de visualização pública estática (ideal para requisições diretas).
    """
    if "linkedin.com" in url:
        match = re.search(r'(?:jobs/view/|jobId=|currentJobId=)(\d+)', url)
        if match:
            job_id = match.group(1)
            return f"https://www.linkedin.com/jobs/view/{job_id}"
            
    return url


def clean_html(html: str) -> str:
    """
    Remove scripts, estilos, navegações e aplica cortes para eliminar 
    recomendações de vagas similares e links de rodapé.
    """
    if not html:
        return ""
        
    soup = BeautifulSoup(html, 'html.parser')

    # 1. Remove elementos visuais e de navegação indesejados
    for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript', 'button', 'svg', 'form']):
        tag.decompose()

    # 2. Extrai o texto limpo
    text = soup.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    texto_limpo = '\n'.join(lines)

    # 3. CORTE DE RUÍDO (Remove tudo a partir de seções de vagas recomendadas):
    padroes_de_corte = [
        r"(?i)similar\s+jobs",
        r"(?i)people\s+also\s+viewed",
        r"(?i)similar\s+searches",
        r"(?i)referrals\s+increase\s+your\s+chances",
        r"(?i)explore\s+top\s+content\s+on\s+linkedin",
        r"(?i)how\s+jobgether\s+works",
        r"(?i)data\s+privacy\s+notice"
    ]
    
    for padrao in padroes_de_corte:
        match = re.search(padrao, texto_limpo)
        if match:
            texto_limpo = texto_limpo[:match.start()].strip()
            break

    return texto_limpo


def scrape_job_url(url: str) -> str:
    """
    Faz a requisição HTTP direta com BeautifulSoup para raspar
    somente os dados do cargo e da descrição.
    """
    target_url = prepare_url(url)
    print(f"Buscando vaga diretamente em: {target_url}")

    # Simula um navegador real para evitar bloqueios simples (403/429)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7"
    }

    try:
        response = requests.get(target_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"[Scraper Error] O site retornou o status: {response.status_code}")
            return ""

        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Extração isolada do Título da Vaga
        titulo = ""
        seletores_titulo = [
            '.top-card-layout__title',
            'h1.top-card-layout__title',
            'h1'
        ]
        for seletor in seletores_titulo:
            elemento = soup.select_one(seletor)
            if elemento:
                texto = elemento.get_text().strip()
                if texto and "linkedin" not in texto.lower():
                    titulo = texto
                    break

        # 2. Extração isolada da Descrição (Sem recomendações da lateral/rodapé)
        sobre_vaga = ""
        seletores_sobre = [
            '.description__text',                           # Padrão da página pública do LinkedIn
            '.show-more-less-html__markup',                 # Bloco interno da vaga
            '#job-details'                                  # Layout alternativo
        ]
        for seletor in seletores_sobre:
            elemento = soup.select_one(seletor)
            if elemento:
                sobre_vaga = clean_html(str(elemento))
                break

        # Fallback: Se não encontrar pela classe CSS exata, limpa a página inteira e aplica o corte
        if not sobre_vaga:
            sobre_vaga = clean_html(response.text)

        titulo_final = titulo if titulo else "Título não identificado"

        return f"VAGA: {titulo_final}\n\nSOBRE A VAGA:\n{sobre_vaga}"

    except requests.RequestException as e:
        print(f"[Scraper Error] Falha de conexão: {e}")
        return ""


def read_job_from_file(filepath: str) -> str:
    """Lê a descrição da vaga de um arquivo de texto local."""
    return Path(filepath).read_text(encoding='utf-8')


def scrape_job(url: str) -> str:
    """Wrapper síncrono da função de raspagem."""
    return scrape_job_url(url)



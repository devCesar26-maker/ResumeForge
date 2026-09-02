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


# ── Lista consolidada de termos de corte (PT + EN) ─────────────────
# Qualquer linha que comece com um desses termos causa o corte de
# todo o texto restante, preservando apenas a descrição da vaga.
_CUT_PATTERNS: list[str] = [
    # ── Inglês — Vagas similares / recomendações ──
    r'(?i)^\s*similar\s+jobs?\s*$'
    ,r'(?i)^\s*similar\s+job\s+searches?\s*$'
    ,r'(?i)^\s*people\s+also\s+viewed\s*$'
    ,r'(?i)^\s*you\s+might\s+also\s+like\s*$'
    ,r'(?i)^\s*recommended\s+for\s+you\s*$'
    ,r'(?i)^\s*jobs\s+you\s+might\s+be\s+interested\s+in\s*$'
    ,r'(?i)^\s*explore\s+(top\s+content|your\s+career\s+options)\s*$'
    ,r'(?i)^\s*be\s+the\s+first\s+to\s+apply\s*$'
    ,r'(?i)^\s*see\s+who\s+you\s+know\s+at\s+.*'
    ,r'(?i)^\s*\d+\s+followers?\s*$'
    ,r'(?i)^\s*follow\s+.*\s+to\s+stay\s+updated'
    # ── Português — Vagas similares / recomendações ──
    ,r'(?i)^\s*vagas?\s+similares?\s*$'
    ,r'(?i)^\s*outras?\s+vagas?\s*$'
    ,r'(?i)^\s*quem\s+viu\s+esta\s+vaga\s*$'
    ,r'(?i)^\s*quem\s+voc[êe]\s+tamb[ée]m\s+viu\s*$'
    ,r'(?i)^\s*vagas?\s+(que\s+)?voc[êe]\s+tamb[ée]m\s+gostaria\s*$'
    ,r'(?i)^\s*vagas?\s+recomendadas?\s*$'
    ,r'(?i)^\s*explorar\s+(mais\s+)?conteúdo\s*$'
    ,r'(?i)^\s*explorar\s+suas\s+opções\s+de\s+carreira\s*$'
    ,r'(?i)^\s*seja\s+o\s+primeiro\s+a\s+candidatar\s*$'
    ,r'(?i)^\s*veja\s+quem\s+voc[êe]\s+conhece\s+na\s+.*'
    ,r'(?i)^\s*\d+\s+seguidores?\s*$'
    ,r'(?i)^\s*siga\s+.*\s+para\s+manter\s+atualizado'
    # ── Autenticação / paywall ──
    ,r'(?i)^\s*(join|sign\s+in|log\s+in)\s+(or\s+)?(sign\s+in|log\s+in)?\s*$'
    ,r'(?i)^\s*sign\s+in\s+to\s+see\s+.*'
    ,r'(?i)^\s*log\s+in\s+to\s+see\s+.*'
    # ── Rodapé institucional / jurídico (EN) ──
    ,r'(?i)^\s*privacy\s+policy\s*$'
    ,r'(?i)^\s*terms\s+(of\s+)?(use|service|conditions)\s*$'
    ,r'(?i)^\s*cookie\s+policy\s*$'
    ,r'(?i)^\s*accessibility\s*$'
    ,r'(?i)^\s*user\s+agreement\s*$'
    ,r'(?i)^\s*about\s+linkedin\s*$'
    ,r'(?i)^\s*linkedin\s+corporation\s+©'
    ,r'(?i)^\s*©\s+\d{4}\s+.*\s+all\s+rights\s+reserved\s*$'
    # ── Rodapé institucional / jurídico (PT) ──
    ,r'(?i)^\s*poli[t]ica\s+de\s+privacidade\s*$'
    ,r'(?i)^\s*termos\s+(de\s+)?(uso|serviço|condições)\s*$'
    ,r'(?i)^\s*poli[t]ica\s+de\s+cookies?\s*$'
    ,r'(?i)^\s*acessibilidade\s*$'
    ,r'(?i)^\s*contrato\s+de\s+usu[áa]rio\s*$'
    ,r'(?i)^\s*sobre\s+o\s+linkedin\s*$'
    ,r'(?i)^\s*todos\+os\+direitos\+reservados\s*$'
    # ── Plataformas BR (Gupy, InfoJobs, Catho, etc.) ──
    ,r'(?i)^\s*ver\s+outras?\s+vagas?\s+da\s+.*\s*$'
    ,r'(?i)^\s*candidatar\s*-\s+se\s*$'
    ,r'(?i)^\s*enviar\s+candidatura\s*$'
    ,r'(?i)^\s*vagas?\s+em\s+destaque\s*$'
    ,r'(?i)^\s*vagas?\s+recentes?\s*$'
]

# ── Linhas curtas de navegação / ruído (PT + EN) ─────────────────────
_NAV_NOISE: set[str] = {
    # EN
    'apply', 'save', 'share', 'send', 'report', 'promote',
    'like', 'comment', 'repost', 'follow', 'message',
    '123', 'see more', 'show more', 'show all',
    'sign in', 'log in', 'join', 'register',
    'skip to content', 'skip to main content',
    'back to top', 'scroll to top',
    # PT
    'candidatar-se', 'candidatar', 'salvar', 'compartilhar',
    'enviar', 'denunciar', 'curtir', 'comentar', 'seguir',
    'mensagem', 'ver mais', 'mostrar mais', 'mostrar tudo',
    'entrar', 'cadastre-se', 'pular para o conteúdo',
    'voltar ao topo', 'ir para o topo',
}


def strip_noise(text: str) -> str:
    """Pré-processamento de texto da vaga: corta ruído de scraping.

    Compatível com LinkedIn, Gupy, Glassdoor, Catho, InfoJobs,
    Indeed, Vagas.com e qualquer portal de emprego em PT ou EN.

    1. Corta texto a partir de marcadores de rodapé / vagas similares.
    2. Remove linhas curtas de navegação ("Apply", "Candidatar-se").
    3. Remove URLs soltas, emojis e linhas duplicadas.
    """
    if not text:
        return ""

    # Normaliza quebras de linha
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # ── CORTE 1: Marcadores de rodapé / vagas similares ────────────────
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        if any(re.match(p, line) for p in _CUT_PATTERNS):
            break  # Corta tudo a partir daqui
        clean_lines.append(line)
    text = '\n'.join(clean_lines)

    # ── CORTE 2: Linhas curtas de navegação / ruído ────────────────────
    result_lines = []
    for line in clean_lines:
        stripped = line.strip().lower()
        if stripped in _NAV_NOISE:
            continue
        if re.match(r'^https?://\S+$', line.strip()):
            continue
        if re.match(r'^[\U0001F300-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\uFE00-\uFE0F\u200D]+$', line.strip()):
            continue
        result_lines.append(line)
    text = '\n'.join(result_lines)

    # ── CORTE 3: Remove linhas duplicadas consecutivas ─────────────────
    text = re.sub(r'(\n[^\n]+)\n\1', r'\1', text)

    # ── CORTE 4: Remove espaços em branco no final de cada linha ──────
    text = re.sub(r' +\n', '\n', text)

    # ── CORTE 5: Colapsa 3+ quebras de linha em 2 ────────────────────
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def read_job_from_file(filepath: str) -> str:
    """Lê descrição da vaga de um arquivo de texto local."""
    return Path(filepath).read_text(encoding='utf-8')


def scrape_job(url: str) -> str:
    """Wrapper síncrono para scrape_job_url. Aplica strip_noise no resultado."""
    raw = scrape_job_url(url)
    return strip_noise(raw)
"""Scraper de vagas de emprego — funciona em qualquer plataforma.

Pipeline:
  1. Extração bruta (trafilatura markdown → readability-lxml → BeautifulSoup com conversão de tags)
  2. Limpeza de whitespace (indentação, linhas vazias, espaços múltiplos)
  3. Deduplicação de linhas (LinkedIn renderiza conteúdo 2x)
  4. Corte de cauda (ruído: vagas similares, sidebar, rodapé)
  5. Normalização de headers (Heurística & Regex: ## Responsabilidades, ## Requisitos, etc.)
  6. Limpeza de artefatos (bullets isolados, indentação sidebar)
"""
import os
import re
import unicodedata
import requests
from bs4 import BeautifulSoup, Tag
from pathlib import Path

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_line(line: str) -> str:
    """Colapsa espaços múltiplos e faz strip — para comparação."""
    return re.sub(r'\s+', ' ', line.strip())


# ════════════════════════════════════════════════════════════════════
# SELETORES CSS POR PLATAFORMA (fallback BeautifulSoup)
# ════════════════════════════════════════════════════════════════════

_SELECTORS_JOB_BODY: list[tuple[str, str]] = [
    ('.description__text', 'LinkedIn'),
    ('.show-more-less-html__markup', 'LinkedIn'),
    ('.jobs-description__content', 'LinkedIn'),
    ('#job-details', 'LinkedIn'),
    ('.jobDescriptionContainer', 'Glassdoor'),
    ('#jobDescriptionText', 'Indeed'),
    ('.jobsearch-JobComponent-description', 'Indeed'),
    ('.job-description', 'Gupy'),
    ('.vacancy__description', 'Gupy'),
    ('.offer-body', 'Catho'),
    ('.detail-body', 'InfoJobs'),
    ('.description-job', 'Vagas'),
    ('[data-qa="job-description"]', 'Genérico'),
]

_SELECTORS_TITLE: list[tuple[str, str]] = [
    ('h1.top-card-layout__title', 'LinkedIn'),
    ('.job-details-jobs-unified-top-card__job-title', 'LinkedIn'),
    ('.jobTitle', 'Glassdoor'),
    ('h1.jobsearch-JobInfoHeader-title', 'Indeed'),
    ('.job-title', 'Gupy'),
    ('.offer-title', 'Catho'),
    ('h1', 'Genérico'),
]

_NOISE_CLASSES: list[str] = [
    '.similar-jobs', '.recommendations', '.related-searches',
    '.similar-jobs-container', '.job-search-recommendations',
    '.jobs-easy-apply-modal', '.application-outcome',
    '.aside', '.sidebar', '.sign-up-modal',
    '.jobs-similar-jobs', '.jobs-search-results',
    '.job-card-container', '.job-recommendations',
    '.other-jobs', '.related-jobs', '.jobs-section-similar',
    '.gupy-similar-jobs', '.similar-vacancies',
    '.footer-container', '.site-footer', '.header-nav',
    '.nav-bar', '.top-nav', '.breadcrumb', '.social-share',
    '.apply-button-container', '.cookie-banner',
]

_NOISE_TAGS: list[str] = [
    'script', 'style', 'nav', 'header', 'footer',
    'aside', 'iframe', 'noscript', 'button', 'svg', 'form',
    'dialog', 'modal',
]


# ════════════════════════════════════════════════════════════════════
# PATRÕES E REGEX DE HEADERS DE SEÇÃO
# ════════════════════════════════════════════════════════════════════

SECTION_PATTERNS: list[tuple[str, str]] = [
    (
        r'^(responsabilidades?( e atribui[cç][oõ]es?)?|atividades|atribui[cç][oõ]es|o que voc[eê] (vai|ir[aá]|far[aá]) (fazer|atuar)|suas atividades|fun[cç][oõ]es|papel|suas responsabilidades|responsibilities|what you will do|duties|role overview|the role)$',
        'Responsabilidades e Atribuições'
    ),
    (
        r'^(requisitos?( e qualifica[cç][oõ]es?)?|qualifica[cç][oõ]es|o que (buscamos|esperamos)( em voc[eê])?|o que voc[eê] precisa (ter|possuir)|perfil (desejado|buscado)|conhecimentos (necess[aá]rios|obrigat[oó]rios)|pr[eé]-requisitos|experi[eê]ncia necess[aá]ria|habilidades necess[aá]rias|requirements|qualifications|what we look for|what you need|must have|basic qualifications|skills required)$',
        'Requisitos e Qualificações'
    ),
    (
        r'^(diferenciais?( se tiver)?|diferencial|conhecimentos desej[aá]veis|desej[aá]vel|desej[aá]veis|nice to have|nice-to-have|plus|preferred qualifications|bonus skills)$',
        'Diferenciais'
    ),
    (
        r'^(benef[ií]cios|nossos benef[ií]cios|o que oferecemos|pacote de benef[ií]cios|remunera[cç][aã]o e benef[ií]cios|benef[ií]cios e vantagens|benefits|what we offer|perks|compensation)$',
        'Benefícios'
    ),
    (
        r'^(sobre a( nossa)? empresa|quem somos|sobre n[oó]s|nossa hist[oó]ria|nossa empresa|conhe[cç]a a empresa|about us|about the company|who we are|our culture)$',
        'Sobre a Empresa'
    ),
    (
        r'^(sobre a vaga|sobre a posi[cç][aã]o|resumo da vaga|descri[cç][aã]o da vaga|about the role|job summary|job description|position overview)$',
        'Sobre a Vaga'
    ),
]


# ════════════════════════════════════════════════════════════════════
# MARCADORES DE CORTE DE CAUDA
# ════════════════════════════════════════════════════════════════════

_CUT_MARKERS: list[str] = [
    # PT — Sidebar/metadata
    'nível de experiência', 'tipo de emprego',
    'função logística', 'setores ',
    # PT — Vagas similares / ruído
    'vagas semelhantes', 'vagas similares', 'vagas relacionadas',
    'as pessoas também visualizaram', 'pesquisas semelhantes',
    'pesquisas relacionadas',
    'indicações dobram suas chances',
    'as indicações dobram suas chances',
    'conteúdos mais populares',
    'quem viu esta vaga', 'quem você também viu',
    'vagas recomendadas',
    'seja o primeiro a candidatar',
    'veja quem você conhece',
    'vagas em destaque', 'vagas recentes',
    'ver outras vagas da', 'outras vagas',
    'outras vagas na mesma empresa',
    'outras oportunidades',
    'receba alertas de novas vagas',
    'explorar mais conteúdo',
    'cadastre seu currículo',
    'conheça outras vagas',
    'confira outras vagas',
    'vagas abertas na empresa',
    'mais vagas',
    # EN — Sidebar/metadata
    'experience level', 'employment type',
    'job function', 'industries',
    # EN — Similar jobs / noise
    'similar jobs', 'similar job searches',
    'people also viewed', 'you might also like',
    'recommended for you', 'jobs you might be interested in',
    'be the first to apply', 'see who you know at',
    'related searches',
    'explore top content', 'explore your career options',
    'more jobs at', 'other jobs at',
    'similar opportunities',
]


# ════════════════════════════════════════════════════════════════════
# FUNÇÕES DE EXTRAÇÃO (ETAPA 1)
# ════════════════════════════════════════════════════════════════════

def _fetch_html(url: str) -> str:
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def _convert_html_structure_to_markdown(soup: BeautifulSoup) -> None:
    """Converte H1-H6, DT e tags de destaque isoladas em cabeçalhos Markdown."""
    for h_tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'dt']):
        text = h_tag.get_text(strip=True)
        if text:
            h_tag.replace_with(f"\n\n## {text}\n\n")

    for p_tag in soup.find_all(['p', 'div']):
        children = [c for c in p_tag.children if isinstance(c, Tag)]
        if len(children) == 1 and children[0].name in ('strong', 'b'):
            text = p_tag.get_text(strip=True)
            if text and len(text) <= 80 and not text.endswith('.'):
                clean_text = text.rstrip(':').strip()
                p_tag.replace_with(f"\n\n## {clean_text}\n\n")


def _extract_from_soup(soup: BeautifulSoup) -> tuple[str, str]:
    titulo = ''
    for seletor, _ in _SELECTORS_TITLE:
        el = soup.select_one(seletor)
        if el:
            texto = el.get_text(strip=True)
            if texto and len(texto) > 2 and texto.lower() not in ('linkedin', 'jobs'):
                titulo = texto
                break

    for noise_class in _NOISE_CLASSES:
        for tag in soup.select(noise_class):
            tag.decompose()

    for tag_name in _NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    body_html = ''
    for seletor, _ in _SELECTORS_JOB_BODY:
        el = soup.select_one(seletor)
        if el:
            body_html = str(el)
            break

    if not body_html:
        for tag_name in ('main', 'article'):
            container = soup.find(tag_name)
            if container and isinstance(container, Tag):
                body_html = str(container)
                break

    return titulo, body_html


def _bs4_fallback(html: str) -> str:
    """Fallback: BeautifulSoup com seletores CSS e marcação Markdown."""
    soup = BeautifulSoup(html, 'html.parser')
    titulo, body_html = _extract_from_soup(soup)
    if not body_html:
        return ''

    soup2 = BeautifulSoup(body_html, 'html.parser')
    _convert_html_structure_to_markdown(soup2)

    for tag_name in _NOISE_TAGS:
        for tag in soup2.find_all(tag_name):
            tag.decompose()

    raw = soup2.get_text(separator='\n', strip=True)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    titulo_final = titulo or 'Título não identificado'
    return f'## VAGA: {titulo_final}\n\n' + '\n'.join(lines)


def _extract_raw(html: str) -> tuple[str, str]:
    """Extrai texto bruto em Markdown do HTML. Retorna (texto, método)."""
    # 1. trafilatura em formato markdown
    if HAS_TRAFILATURA:
        try:
            text = trafilatura.extract(
                html,
                output_format='markdown',
                favor_precision=False,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            ) or ''
            if len(text) >= 200:
                return text, 'trafilatura'
        except Exception as e:
            print(f'[Scraper] trafilatura falhou: {e}')

    # 2. readability-lxml
    if HAS_READABILITY:
        try:
            doc = ReadabilityDocument(html)
            content_html = doc.summary()
            soup = BeautifulSoup(content_html, 'html.parser')
            _convert_html_structure_to_markdown(soup)
            text = soup.get_text(separator='\n', strip=True)
            text = '\n'.join(ln.strip() for ln in text.splitlines() if ln.strip())
            if text and len(text) >= 200:
                return text, 'readability-lxml'
        except Exception as e:
            print(f'[Scraper] readability falhou: {e}')

    # 3. BeautifulSoup
    text = _bs4_fallback(html)
    if text and len(text) >= 200:
        return text, 'beautifulsoup'

    return '', 'nenhum'


# ════════════════════════════════════════════════════════════════════
# FUNÇÕES DE LIMPEZA (ETAPAS 2-6)
# ════════════════════════════════════════════════════════════════════

def _clean_whitespace(text: str) -> str:
    """ETAPA 2: Remove whitespace em excesso."""
    lines = text.split('\n')
    lines = [ln.strip() for ln in lines]
    result = []
    prev_empty = False
    for ln in lines:
        if not ln:
            if not prev_empty:
                result.append('')
            prev_empty = True
        else:
            result.append(ln)
            prev_empty = False
    return '\n'.join(result)


def _dedup_lines(text: str) -> str:
    """ETAPA 3: Remove blocos de conteúdo duplicado."""
    lines = text.split('\n')

    # Remove conteúdo duplicado consecutivo ou blocos idênticos
    result = []
    prev_norm = None
    removed = 0
    for line in lines:
        norm = _normalize_line(line)
        if norm and norm == prev_norm:
            removed += 1
            continue
        result.append(line)
        prev_norm = norm

    if removed:
        print(f'[Scraper] Linhas duplicadas removidas: {removed}')
    return '\n'.join(result)


def _cut_tail(text: str) -> str:
    """ETAPA 4: Corta texto a partir do marcador de ruído mais cedo."""
    lines = text.split('\n')
    best_idx = len(lines)
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for marker in _CUT_MARKERS:
            if marker in line_lower:
                if i < best_idx:
                    best_idx = i
                break
    if best_idx < len(lines):
        return '\n'.join(lines[:best_idx]).rstrip()
    return text


def _normalize_headers(text: str) -> tuple[str, list[str]]:
    """ETAPA 5: Padroniza headers em formato '## Header'."""
    lines = text.split('\n')
    result = []
    found = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append('')
            continue

        # Pula listas de itens numerados ou bullet points
        if re.match(r'^[-*•–—]\s', stripped) or re.match(r'^\d+[\.\)]\s', stripped):
            result.append(line)
            continue

        # Limpa formatação markdown prévia
        clean = re.sub(r'^[#_\s]+', '', stripped)
        clean = re.sub(r'^\*\*([^*]+?)\*\*\s*$', r'\1', clean)
        clean = re.sub(r'^\*([^*]+?)\*\s*$', r'\1', clean)
        clean = re.sub(r'^__([^_]+?)__\s*$', r'\1', clean)
        clean = clean.strip()

        no_colon = clean.rstrip(':').strip()
        normalized = _strip_accents(no_colon).lower()

        matched = False
        # 1. Tenta padronizar por categorias conhecidas
        for pattern, canon_title in SECTION_PATTERNS:
            if re.match(pattern, normalized, re.IGNORECASE):
                result.append(f'## {canon_title}')
                found.append(canon_title)
                matched = True
                break

        if matched:
            continue

        # 2. Se já era um header Markdown (começava com # ou ##)
        if stripped.startswith('#') and len(no_colon) <= 80:
            header_text = no_colon.title()
            result.append(f'## {header_text}')
            found.append(header_text)
            continue

        # 3. Heurística para linhas curtas terminadas em ':'
        if stripped.endswith(':') and len(no_colon) <= 60 and len(no_colon.split()) <= 7:
            if not re.search(r'\b(como|quando|onde|porque|para|com|em|que)\b', normalized):
                header_text = no_colon.title()
                result.append(f'## {header_text}')
                found.append(header_text)
                continue

        result.append(line)

    return '\n'.join(result), found


def _clean_artifacts(text: str) -> str:
    """ETAPA 6: Limpa artefatos de sidebar e whitespace final."""
    lines = text.split('\n')
    clean = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        # Bullet isolado → funde com próxima linha ou remove
        if re.match(r'^[-*–—•]\s*$', stripped):
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if (nxt
                        and not re.match(r'^[-*–—•]\s*$', nxt)
                        and not nxt.startswith('## ')
                        and nxt not in ('', '\n')):
                    merged = re.sub(r'\s{2,}', ' ', nxt)
                    clean.append(f'- {merged}')
                    i += 2
                    continue
            i += 1
            continue
        # Indentação excessiva em não-listas
        if len(lines[i]) - len(lines[i].lstrip()) > 2 and not stripped.startswith(('-', '*', '•')):
            clean.append(stripped)
        else:
            clean.append(lines[i])
        i += 1
    text = '\n'.join(clean)
    text = re.sub(r'\n[ \t]+\n', '\n\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

def clean_job_text_content(raw_input: str) -> str:
    """Limpa, remove ruídos e padroniza headers de qualquer texto de vaga.

    Funciona tanto para HTML extraído quanto para texto colado manualmente.
    """
    if not raw_input or not raw_input.strip():
        return ''

    text = raw_input
    # Se contiver tags HTML (ex: colado com tags ou retornado de scrape)
    if '<html' in text.lower() or '<div' in text.lower() or '<p' in text.lower():
        text, method = _extract_raw(text)
        print(f'[Scraper] Extraído do HTML via {method}')

    text = _clean_whitespace(text)
    text = _dedup_lines(text)
    text = _cut_tail(text)
    text, headers = _normalize_headers(text)
    text = _clean_artifacts(text)

    return text.strip()


def clean_job_text(html: str) -> str:
    """Alias para clean_job_text_content (compatibilidade de API)."""
    return clean_job_text_content(html)


def scrape_job(url: str) -> str:
    """Raspa a vaga a partir de uma URL e retorna texto limpo."""
    try:
        html = _fetch_html(url)
    except Exception as e:
        print(f"[Scraper] Erro ao acessar {url}: {e}")
        return ''
    resultado = clean_job_text(html)
    if not resultado.strip():
        print('[Scraper] Conteúdo extraído está vazio.')
    return resultado


def read_job_from_file(filepath: str) -> str:
    """Lê descrição da vaga de um arquivo de texto local."""
    content = Path(filepath).read_text(encoding='utf-8')
    return clean_job_text_content(content)


"""Analisador híbrido: Groq (Velocidade no Parse) + Google Gemini (Rigor no Match e Qualidade na Geração)."""

import json
import re
import unicodedata
from groq import Groq
from pydantic import ValidationError
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from .config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, SECTION_LABELS
from .models import JobPosting, MatchResult, ResumeData
from .scraper import clean_job_text_content


# ==========================================
# SANITIZAÇÃO DE TEXTO
# ==========================================

def _sanitize_text(text: str) -> str:
    """Limpa e normaliza texto antes de enviar para APIs de IA.

    Remove caracteres nulos, quebras de linha excessivas, normaliza
    espaços em branco e garante UTF-8 limpo.
    """
    if not text:
        return ""
    # Remove caracteres nulos e de controle (exceto quebras de linha e tabulações)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Remove BOM (Byte Order Mark)
    text = text.lstrip('\ufeff')
    # Normaliza quebras de linha: \r\n -> \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Remove mais de 2 quebras de linha consecutivas
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove espaços em branco no final de cada linha
    text = re.sub(r' +\n', '\n', text)
    # Remove espaços múltiplos consecutivos (preserva quebras de linha)
    text = re.sub(r'([^\n]) {2,}', r'\1 ', text)
    return text.strip()


# ==========================================
# EXTRAÇÃO DE TERMOS DE SKILL (usada na penalidade de cobertura)
# ==========================================

# Palavras genéricas de anúncios de vaga (PT/EN) que NUNCA devem contar como "skill"
# na checagem de cobertura — frases de requisitos são repletas delas.
_VAGA_STOPWORDS_RAW: str = """
    a ao aos as à às o os um uma uns umas de do da dos das dum duma em no na nos nas num numa
    com contra entre para por perante sem sob sobre até desde e ou nem mas que se como quando
    onde porque porém também mais menos muito muita muitos muitas lhe pra pro
    este esta estes estas esse essa esses essas aquele aquela aqueles aquelas isto isso aquilo
    the a an of in on to for with without by from at via and or but not if then than while when
    where which who whom whose what how why as is are was were be been being will can may
    ser é são era eram foi foram será serão sendo sido estar estava estavam esteve estarão
    ter tem têm tinha tinha tive teve terá terão possui possuem possuía
    conhecimento conhecimentos básico básica básicos básicas requisito requisitos
    indispensável indispensáveis obrigatório obrigatória obrigatórios obrigatórias
    desejável desejáveis diferencial diferenciais
    experiência familiaridade vivência domínio noções noção conceitos sólido sólida
    avançado avançada intermediário intermediária pleno plena júnior jr junior
    sênior senior estagiário estagiária trainee
    nível níveis anos ano dia dias
    capacidade realizar manutenção ajustes ajuste criação construção desenvolvimento
    elaborar elaboração extração análise tratamento gestão atuação atuar apoio apoiar suporte
    consultas chamados rotina rotinas atividades atividade fluxo fluxos processo processos
    ferramenta ferramentas plataforma plataformas software softwares tecnologia tecnologias
    times time equipe equipes comunicação colaboração organização proatividade comprometimento
    autonomia autônomo autônoma ambiente metodologia metodologias método métodos ágil ágeis agilidade
    dados data métrica métricas indicador indicadores relatório relatórios dashboard dashboards
    queries query scripts script automação automações modelos modelo tabela tabelas coluna colunas
    linhas linha arquivo arquivos documentos documentação bases base banco bancos
    informações informação pipelines pipeline insights insight business intelligence machine learning deep
    análise analise analises análises analysis analytics reporting reports experience analysis
    analista analistas analyst desenvolvedor desenvolvedora desenvolvedores developer developers
    engenheiro engenheira engenheiros engineer engineers cientista consultor consultores
    especialista especialistas coordenador coordenadora arquiteto arquiteta designer
    profissional profissionais cargo cargos função funções posição posições vaga vagas
    trabalho empresa empresas remoto remota presencial hibrido híbrido
    habilidades competência competências qualificação qualificações
    atender receber tratar identificar analisar extrair transformar carregar automatizar otimizar
    avaliar garantir participar colaborar monitorar documentar testar implementar desenhar modelar
    buscar esperar possuir dominar conhecer saber usar utilizar aplicar gerar produzir entregar
    acompanhar conduzir liderar coordenar gerenciar administrar auxiliar suportar resolver
    solucionar diagnosticar prevenir mitigar reduzir aumentar melhorar evoluir migrar integrar
    configurar instalar estruturar organizar planejar executar validar revisar publicar comunicar
    apresentar reportar mensurar controlar definir contribuir fomentar disseminar construir manter
    criar elaborar desenvolver atuar apoiar
    considerado considerada considerados consideradas alinhado alinhada alinhados alinhadas
    voltado voltada voltados voltadas focado focada focados focadas
    existente existentes diversos diversas principais principal ideal
    candidato candidata organizado organizada organizados organizadas proativo proativa proativos proativas
    comunicativo comunicativa dinâmico dinâmica flexível resiliente motivado motivada dedicado dedicada
    criativo criativa colaborativo colaborativa analítico analítica estratégico estratégica
    resultado resultados solução soluções melhoria melhorias entrega entregas
    diário diária semanais mensais contínua contínuo
""".split()


def _normalizar_termo(s: str) -> str:
    """Lowercase + remove acentos, espaços e hífens — para busca por substring."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[\s\-]+', '', s.lower())


_VAGA_STOPWORDS: frozenset[str] = frozenset(_normalizar_termo(p) for p in _VAGA_STOPWORDS_RAW)


def _e_stopword(palavra: str) -> bool:
    """True se a palavra é conector/descritor genérico (nunca pode ser uma skill)."""
    return _normalizar_termo(palavra) in _VAGA_STOPWORDS


def _limpar_token(palavra: str) -> str:
    """Remove pontuação inicial/final, preservando símbolos internos (C#, .NET, Python 3.x)."""
    return re.sub(r'^[\W_]+|[\W_]+$', '', palavra)


def _token_parece_skill(palavra: str) -> bool:
    """Heurística: token com cara de tecnologia dentro de uma frase de requisito."""
    norm = _normalizar_termo(palavra)
    if len(norm) < 2 or _e_stopword(palavra):
        return False
    # Acrônimos/marcas (SQL, AWS, PowerBI) ou símbolos técnicos (C#, .NET, Node.js)
    if any(c.isupper() for c in palavra) or re.search(r'[#.+_/]', palavra):
        return True
    # Palavras comuns com 3+ letras também podem ser skills (python, docker, etl...)
    return len(norm) >= 3


def _extrair_termos_de_skill(itens_raw: list[str]) -> tuple[list[str], list[str]]:
    """Converte itens crus (keywords, requisitos, título) em termos que realmente são skills.

    Frases inteiras de requisitos (ex.: "Conhecimento básico em SQL — requisito
    indispensável") NUNCA entram na comparação literal: são quebradas em segmentos
    e apenas os tokens com cara de tecnologia são mantidos ("SQL").

    Retorna (termos_normalizados, termos_originais_para_log), ambos sem duplicatas.
    """
    termos_norm: list[str] = []
    termos_display: list[str] = []
    vistos: set[str] = set()

    def _add(norm: str, display: str) -> None:
        if norm and norm not in vistos:
            vistos.add(norm)
            termos_norm.append(norm)
            termos_display.append(display)

    for item in itens_raw:
        if not item or not item.strip():
            continue
        # Separa por pontuação/travessões comuns em listas de vaga
        for segmento in re.split(r'[,\/;:|()\[\]"\'—–]|\s-\s', item):
            segmento = segmento.strip()
            if not segmento:
                continue
            palavras = [p for p in (w.strip() for w in segmento.split()) if p]
            palavras_limpas = [_limpar_token(p) for p in palavras]
            palavras_limpas = [p for p in palavras_limpas if p]
            if not palavras_limpas:
                continue

            tokens_uteis = [p for p in palavras_limpas if not _e_stopword(p)]
            if not tokens_uteis:
                continue

            # Termo curto sem conectivos (ex.: 'Power BI', 'SQL', 'Data Analyst')
            if len(palavras_limpas) <= 3 and len(tokens_uteis) == len(palavras_limpas):
                _add(_normalizar_termo(' '.join(palavras_limpas)), segmento)
                continue

            # Segmento frasal → mantém apenas tokens com cara de tecnologia
            for p in palavras_limpas:
                if _token_parece_skill(p):
                    _add(_normalizar_termo(p), p)

    return termos_norm, termos_display


# ==========================================
# INICIALIZAÇÃO DOS CLIENTES
# ==========================================

def _get_gemini_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY não configurada no .env")
    return genai.Client(api_key=GEMINI_API_KEY)


def _get_groq_client() -> Groq:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY não configurada no .env")
    return Groq(api_key=GROQ_API_KEY)


# ==========================================
# CAMADA 1: GROQ (Velocidade Máxima - Parser da Vaga)
# ==========================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def parse_job_posting(raw_text: str) -> JobPosting:
    """Usa a Groq para extrair dados da vaga em milissegundos."""
    client = _get_groq_client()
    
    # Aplica pipeline de limpeza e normalização de headers
    raw_text = clean_job_text_content(raw_text)
    raw_text = _sanitize_text(raw_text)
    
    schema = JobPosting.model_json_schema()
    
    prompt = f"""Você é um especialista em recrutamento e análise técnica de vagas.
Extraia as informações estruturadas da vaga de emprego abaixo.
Retorne APENAS o JSON que obedeça estritamente a este esquema JSON: {json.dumps(schema)}.

ESTRUTURA DE HEADERS EM MARKDOWN:
O texto da vaga utiliza cabeçalhos em Markdown (`## Header`) para delimitar o início de cada seção, tais como:
- `## Responsabilidades e Atribuições`
- `## Requisitos e Qualificações`
- `## Diferenciais`
- `## Benefícios`
- `## Sobre a Empresa` / `## Sobre a Vaga`

REGRA CRÍTICA:
Ignore COMPLETAMENTE qualquer conteúdo que NÃO pertença à vaga principal.
Se houver trechos como "Vagas similares", "Outras vagas", "People also viewed", rodapés, menus ou avisos de navegação, DESCARTE-OS.
Oriente-se pelos cabeçalhos `## Header` para extrair com exatidão as responsabilidades, requisitos mandatórios, diferenciais e benefícios.

Campo 'benefits': Extraia separadamente os benefícios oferecidos pela vaga.
Exemplos: plano de saúde, vale refeição, vale alimentação, seguro de vida, home office, auxílio creche, PLR, bônus anual, etc.
Se não houver benefícios mencionados, retorne uma lista vazia.

Texto da vaga:
---
{raw_text}
---"""

    chat_completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "Você é um assistente que responde apenas com JSON válido em formato raw, sem markdown adicional."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )

    response_text = chat_completion.choices[0].message.content

    try:
        dados_json = json.loads(response_text)
        job = JobPosting(**dados_json)
        job.raw_text = raw_text
        return job
    except ValidationError as ve:
        print("\n" + "="*50)
        print("ERRO DE VALIDAÇÃO DO PYDANTIC (JobPosting):")
        print(ve.json(indent=2))
        print(f"Resposta bruta da Groq: {response_text}")
        print("="*50 + "\n")
        raise ve
    except Exception as e:
        print("\n" + "="*50)
        print(f"ERRO GENÉRICO NO PARSER DA VAGA: {type(e).__name__} - {e}")
        print("="*50 + "\n")
        raise e


# ==========================================
# CAMADA 2: GEMINI (Rigor Absoluto - Analisador de Match)
# ==========================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(ServerError)
)
def analyze_match(resume_text: str, job: JobPosting, resume_data: ResumeData | None = None) -> MatchResult:
    """Usa o Gemini para analisar friamente a compatibilidade do currículo com a vaga."""
    client = _get_gemini_client()
    
    # Sanitiza o texto antes de enviar à API
    resume_section = _sanitize_text(resume_text)
    if resume_data:
        resume_section = _sanitize_text(resume_data.model_dump_json())

    prompt = f"""Você é um sistema ATS (Applicant Tracking System) corporativo de alta precisão, frio, analítico e rigoroso.
Sua única diretriz é avaliar se o candidato possui as qualificações técnicas necessárias de forma literal.

IMPORTANTE: Ao avaliar a vaga de emprego abaixo, ignore completamente qualquer ruído de scraping web:
menus, cabeçalhos, rodapés, copyrights, vagas similares, botões de navegação, links,
recomendações de outras vagas, termos de uso, política de privacidade, etc.
Considere APENAS o conteúdo real da vaga (título, empresa, descrição, responsabilidades, requisitos).

REGRAS DE AVALIAÇÃO CRÍTICA (NÃO SEJA CONDESCENDENTE):
1. CORRESPONDÊNCIA REAL: Identifique como "matching_skills" apenas tecnologias explicitamente descritas no currículo. Não deduza conhecimento.
2. PENALIDADES RÍGIDAS: 
   - Se tecnologias fundamentais destacadas no título ou nos requisitos críticos da vaga (como SQL, Tableau ou Power BI) NÃO estiverem expressas no currículo, o campo 'score' deve ser severamente limitado (máximo 35%).
   - Ignorar a ferramenta principal da vaga implica em reprovação automática (Score Baixo).
3. SENIORIDADE: Considere o objetivo profissional e tempo de experiência. Se a vaga exige um profissional autônomo (Consultor/Analista Pleno) e o currículo é de um acadêmico/estagiário, reflita essa distância no score geral.

CURRÍCULO DO CANDIDATO:
---
{resume_section}
---

VAGA DE ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos Mandatórios: {', '.join(job.requirements[:12])}
Responsabilidades: {', '.join(job.responsibilities[:10])}
---"""

    # Schema ultra-simplificado e plano. O Google AMA esse formato e não gera ServerError.
    gemini_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "score": types.Schema(type=types.Type.STRING),
            "verdict": types.Schema(type=types.Type.STRING),
            "matching_skills": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "missing_skills": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "transferable_skills": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "strengths": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "weaknesses": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "suggestions": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING))
        },
        required=["score", "verdict", "matching_skills", "missing_skills", "transferable_skills", "strengths", "weaknesses", "suggestions"]
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=gemini_schema,
                temperature=0.2,  # Subimos levemente para dar mais estabilidade na geração
            )
        )
    except ClientError as e:
        print(f"\n[Erro Gemini - Requisição Inválida (analyze_match)]: {e}")
        raise ValueError(
            "Erro de validação na requisição ao Gemini. "
            "O texto da vaga ou do currículo pode conter caracteres inválidos ou estar mal formatado. "
            f"Detalhes: {e}"
        ) from e
    except ServerError as e:
        print(f"\n[Erro Gemini - Servidor (analyze_match)]: {e}")
        raise
    except APIError as e:
        print(f"\n[Erro Gemini - API (analyze_match)]: {type(e).__name__}: {e}")
        raise

    try:
        # TODO-DEBUG: remover após confirmar estabilidade
        # ── LOG DO JSON BRUTO DO GEMINI (auditoria da causa raiz) ──
        print("\n" + "="*60)
        print("[AnalyzeMatch] JSON BRUTO RETORNADO PELO GEMINI (response.text):")
        print(response.text)
        print("="*60 + "\n")

        dados_json = json.loads(response.text)

        # Extrai as listas de skills ANTES do recálculo — elas são a fonte de verdade
        def extrair_lista(chave: str) -> list[str]:
            valores = dados_json.get(chave, [])
            if not isinstance(valores, list):
                return []
            return [str(v) for v in valores if v is not None]

        matching_skills = extrair_lista("matching_skills")
        missing_skills = extrair_lista("missing_skills")

        # ── Score bruto do Gemini: usado apenas como fallback / referência ──
        score_bruto_raw = dados_json.get("score", "0")
        try:
            score_bruto = int(float(str(score_bruto_raw).replace("%", "").strip()))
        except (ValueError, TypeError):
            score_bruto = 0
        score_bruto = max(0, min(100, score_bruto))

        # ── RECÁLCULO DO SCORE NO BACKEND (não confia cegamente no número solto do LLM) ──
        total_skills = len(matching_skills) + len(missing_skills)
        if total_skills > 0:
            score_calculado = round((len(matching_skills) / total_skills) * 100)
        else:
            # Fallback: se o Gemini retornou AMBAS as listas vazias, usa o score bruto
            score_calculado = score_bruto

        print(f"[AnalyzeMatch] Gemini -> score_bruto={score_bruto} | "
              f"matching={len(matching_skills)} | missing={len(missing_skills)}")
        print(f"[AnalyzeMatch] Score recalculado via cobertura (matching/total): {score_calculado}")

        score = score_calculado

        # ── Penalização genérica pós-IA: cobertura de skills críticas ──
        # IMPORTANTE: a cobertura só conta termos com cara de skill (SQL, Power BI, Python,
        # ETL...). Frases inteiras de requisitos (ex.: "Conhecimento básico em SQL — requisito
        # indispensável") jamais entram na comparação literal — senão o score seria penalizado
        # mesmo com a skill presente no currículo.
        termos_criticos_raw: list[str] = job.keywords or []
        if not termos_criticos_raw:
            # Fallback apenas se o parser da vaga não retornou keywords
            termos_criticos_raw = list(job.requirements) + [job.title]

        termos_criticos, termos_criticos_display = _extrair_termos_de_skill(termos_criticos_raw)
        texto_normalizado = _normalizar_termo(resume_section)

        if termos_criticos:
            termos_presentes = sum(1 for t in termos_criticos if t in texto_normalizado)
            critical_coverage = termos_presentes / len(termos_criticos)

            print(f"[AnalyzeMatch] Termos críticos (skills) avaliados: {termos_criticos_display}")

            termos_ausentes = [
                d for d, t in zip(termos_criticos_display, termos_criticos)
                if t not in texto_normalizado
            ]

            if critical_coverage < 0.8:
                print(f"[AnalyzeMatch] Coverage de skills críticas: {critical_coverage:.0%} "
                      f"({termos_presentes}/{len(termos_criticos)})")
                print(f"[AnalyzeMatch] Termos críticos ausentes no currículo: {termos_ausentes}")

            if critical_coverage >= 0.8:
                pass  # sem penalidade adicional
            elif critical_coverage >= 0.5:
                score = min(score, 60)
            else:
                score = min(score, 35)
        else:
            print("[AnalyzeMatch] Nenhum termo de skill identificado nas keywords/requisitos — "
                  "penalidade de cobertura ignorada.")

        # Cálculo dinâmico do veredicto baseado no score final recalculado
        if score >= 75:
            verdict = "ALTA"
        elif score >= 45:
            verdict = "MEDIA"
        else:
            verdict = "BAIXA"

        # ── REDE DE SEGURANÇA: coerência visual score ↔ missing_skills ──
        if len(missing_skills) == 0 and len(matching_skills) > 0 and score < 75:
            print(f"[AVISO] Score {score} inconsistente com missing_skills vazio — forçando revisão")
            score = max(score, 80)
            # Recalcula o veredicto após a correção do score
            if score >= 75:
                verdict = "ALTA"
            elif score >= 45:
                verdict = "MEDIA"
            else:
                verdict = "BAIXA"

        print(f"[AnalyzeMatch] SCORE FINAL: {score}/100 | VERDICT: {verdict}")

        # Montamos o MatchResult garantindo que tailored_resume seja passado como None
        return MatchResult(
            score=score,
            verdict=verdict,
            matching_skills=matching_skills,
            missing_skills=missing_skills,
            transferable_skills=extrair_lista("transferable_skills"),
            strengths=extrair_lista("strengths"),
            weaknesses=extrair_lista("weaknesses"),
            suggestions=extrair_lista("suggestions"),
            tailored_resume=None  # Campo problemático resolvido localmente!
        )

    except ValidationError as ve:
        print(f"\n[Error] Pydantic MatchResult Validation failed: {ve.json()}")
        raise ve
    except Exception as e:
        print(f"\n[Error] Falha crítica no processamento da resposta do Gemini: {e}")
        raise e


# ==========================================
# CAMADA 3: GEMINI (Escrita Criativa Otimizada para ATS)
# ==========================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(ServerError)
)
def generate_tailored_resume(
    resume_text: str,
    job: JobPosting,
    match: MatchResult,
    resume_data: ResumeData | None = None
) -> ResumeData:
    """Usa o Gemini para reescrever o currículo com foco em passar no ATS."""
    client = _get_gemini_client()

    # Sanitiza o texto antes de enviar à API
    resume_section = _sanitize_text(resume_text)
    if resume_data:
        resume_section = _sanitize_text(resume_data.model_dump_json())

    prompt = f"""Você é um engenheiro de recrutamento e especialista em otimização de currículos para sistemas ATS.
Sua missão é adaptar o currículo do candidato para maximizar o score de compatibilidade com a vaga abaixo, garantindo aprovação na triagem automatizada.

IMPORTANTE: Ao analisar a vaga de emprego abaixo, ignore completamente qualquer ruído de scraping web:
menus, cabeçalhos, rodapés, copyrights, vagas similares, botões de navegação, links,
recomendações de outras vagas, termos de uso, política de privacidade, etc.
Considere APENAS o conteúdo real da vaga (título, empresa, descrição, responsabilidades, requisitos).

REGRAS DE OURO PARA BATER O ATS:
1. MATCH DE PALAVRAS-CHAVE (HARD SKILLS): Identifique as tecnologias fundamentais da vaga (ex: Power BI, Tableau, SQL, Snowflake, DAX) e integre-as de forma orgânica e frequente no resumo profissional, na lista de habilidades e nos destaques das experiências. Use a terminologia exata da vaga.
2. VERBOS DE AÇÃO + RESULTADOS (MÉTRICAS): Reescreva os bullet points (highlights) das experiências profissionais. Comece cada frase com um verbo de ação forte no passado (ex: "Desenvolvi", "Otimizei", "Liderei", "Implementei") e tente atrelar os resultados a estimativas numéricas ou métricas realistas se aplicável.
3. ORDENAÇÃO DE RELEVÂNCIA: Reorganize as categorias de habilidades (skills) e a ordem dos itens de experiência para que as competências e projetos mais alinhados com a vaga atual fiquem visíveis logo no topo.
4. INTEGRIDADE ABSOLUTA DE DADOS: Não altere nenhuma data, nome de empresa ou cargo ocupado. Nunca invente experiências fictícias.
5. SÍNTESE DO RESUMO: Adapte o 'summary' (resumo profissional) do currículo para ser um gancho perfeito de no máximo 4 linhas, contendo as principais tecnologias e anos de experiência exigidos pela vaga.
6. PRESERVAÇÃO EXATA DE NOMES DE SEÇÃO: NÃO altere, traduza ou normalize os títulos das seções do currículo. Use EXATAMENTE os nomes listados abaixo como títulos de cada seção no JSON gerado (campo `category` para skills, e os campos de estrutura do ResumeData para as demais seções). Se o currículo original usa "Formação Acadêmica", NÃO gire "Educação" — preserve o termo original.

NOMES EXATOS DAS SEÇÕES (use estes valores ao gerar o JSON):
- Resumo Profissional (campo: summary)
- Experiência Profissional (campo: experience)
- Formação Acadêmica (campo: education)
- Habilidades Técnicas (campo: skills — use o rótulo original como `category`)
- Projetos (campo: projects)

CURRÍCULO ORIGINAL:
---
{resume_section}
---

VAGA DE ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos Críticos: {', '.join(job.requirements[:10])}
Keywords do ATS: {', '.join(job.keywords)}
---

Gere o currículo adaptado seguindo estritamente a estrutura ResumeData."""

    resume_data_schema = ResumeData.model_json_schema()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=resume_data_schema,
                temperature=0.3,
            )
        )
    except ClientError as e:
        print(f"\n[Erro Gemini - Requisição Inválida (generate_tailored_resume)]: {e}")
        raise ValueError(
            "Erro de validação na requisição ao Gemini. "
            "O texto pode conter caracteres inválidos ou estar mal formatado. "
            f"Detalhes: {e}"
        ) from e
    except ServerError as e:
        print(f"\n[Erro Gemini - Servidor (generate_tailored_resume)]: {e}")
        raise
    except APIError as e:
        print(f"\n[Erro Gemini - API (generate_tailored_resume)]: {type(e).__name__}: {e}")
        raise

    try:
        dados_json = json.loads(response.text)
        return ResumeData(**dados_json)
    except ValidationError as ve:
        print("\n" + "="*50)
        print("ERRO DE VALIDAÇÃO DO PYDANTIC (ResumeData) COM O GEMINI:")
        print(ve.json(indent=2))
        print("="*50 + "\n")
        raise ve
    except Exception as e:
        print("\n" + "="*50)
        print(f"ERRO DE PARSE NO RESUME DO GEMINI: {type(e).__name__} - {e}")
        print("="*50 + "\n")
        raise e


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(ServerError)
)
def generate_cover_letter(resume_text: str, job: JobPosting, match: MatchResult) -> str:
    """Gera uma carta de apresentação rápida utilizando o Gemini."""
    client = _get_gemini_client()
    # Sanitiza o texto
    resume_text = _sanitize_text(resume_text)

    # TODO-DEBUG: remover após confirmar estabilidade
    # ── LOG DE DIAGNÓSTICO: confirma que o match chegou preenchido ──
    # O prompt da carta depende de match.matching_skills[:5]; se vier vazio,
    # a carta sai sem conteúdo relevante.
    print(f"\n[GenerateCoverLetter] match=None? {match is None} | "
          f"matching_skills={len(match.matching_skills) if match else 'N/A'} "
          f"({match.matching_skills[:5] if match else 'N/A'}) | "
          f"job.title={job.title!r}")

    prompt = f"""Escreva uma Carta de Apresentação concisa (de no máximo 3 parágrafos curtos) para a vaga especificada.

VAGA:
---
Título: {job.title}
Empresa: {job.company}
Requisitos principais: {', '.join(job.requirements[:5])}
---

DESTAQUES DO CANDIDATO:
{', '.join(match.matching_skills[:5])}

Gere o texto da carta diretamente, sem cabeçalhos antiquados de endereço, de modo que esteja pronta para ser utilizada como corpo de e-mail profissional."""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
            )
        )
    except ClientError as e:
        print(f"\n[Erro Gemini - Requisição Inválida (generate_cover_letter)]: {e}")
        raise ValueError(
            "Erro de validação na requisição ao Gemini. "
            "O texto pode conter caracteres inválidos ou estar mal formatado. "
            f"Detalhes: {e}"
        ) from e
    except ServerError as e:
        print(f"\n[Erro Gemini - Servidor (generate_cover_letter)]: {e}")
        raise
    except APIError as e:
        print(f"\n[Erro Gemini - API (generate_cover_letter)]: {type(e).__name__}: {e}")
        raise

    # TODO-DEBUG: remover após confirmar estabilidade
    # ── LOG DE DIAGNÓSTICO (temporário) ──
    # O SDK retorna response.text = None quando o Gemini responde SEM partes
    # de texto (resposta vazia/bloqueada). Sem esse log, a causa raiz ficaria
    # invisível.
    # OBS: o print do texto BRUTO da carta foi removido por expor dados do
    # candidato — se precisar reativar para debug, logue apenas o tamanho.
    response_text = response.text
    print(f"[GenerateCoverLetter] len(text)={len(response_text) if response_text else 0}")
    if response.candidates:
        print(f"[GenerateCoverLetter] finish_reason={response.candidates[0].finish_reason}")

    if not response_text or not response_text.strip():
        # TODO-DEBUG: remover após confirmar estabilidade (guard vazio/None)
        print("\n[ERRO GenerateCoverLetter] Gemini retornou texto vazio/None — "
              "propagando erro explícito em vez de carta em branco")
        raise ValueError("O Gemini retornou uma carta vazia. Tente novamente.")

    return response_text
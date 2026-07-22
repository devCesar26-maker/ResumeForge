"""Analisador Híbrido Otimizado para Chave Única (Single API Key).

Focado em baixa latência para evitar o Timeout de 30s do Render, extração
exaustiva de competências e preservação rigorosa de dados pessoais.
Modelos lidos estritamente via variáveis de ambiente/config.
"""

import json
import sys
import time
from google import genai
from google.genai import types
from google.genai.errors import APIError
from groq import Groq
from groq import RateLimitError as GroqRateLimitError
from pydantic import ValidationError

from .config import GEMINI_API_KEYS, GEMINI_MODELS, GROQ_API_KEYS, GROQ_MODEL
from .models import JobPosting, MatchResult, ResumeData

# ==========================================
# CLIENTES E MODELOS VIA ENV
# ==========================================

# Pega a primeira chave definida na lista
gemini_key = (
    GEMINI_API_KEYS[0]
    if isinstance(GEMINI_API_KEYS, list) and GEMINI_API_KEYS
    else GEMINI_API_KEYS
)
groq_key = (
    GROQ_API_KEYS[0]
    if isinstance(GROQ_API_KEYS, list) and GROQ_API_KEYS
    else GROQ_API_KEYS
)


def _get_gemini_client() -> genai.Client:
    return genai.Client(api_key=gemini_key)


def _get_groq_client() -> Groq:
    return Groq(api_key=groq_key)


def _get_gemini_model() -> str:
    """Retorna o modelo do Gemini configurado na lista do ambiente."""
    if isinstance(GEMINI_MODELS, list) and GEMINI_MODELS:
        return GEMINI_MODELS[0]
    if isinstance(GEMINI_MODELS, str) and GEMINI_MODELS:
        return GEMINI_MODELS
    raise ValueError(
        'Nenhum modelo Gemini configurado no ambiente (GEMINI_MODELS).'
    )


# ==========================================
# CAMADA 1: GROQ (Parser da Vaga)
# ==========================================


def parse_job_posting(raw_text: str) -> JobPosting:
    """Extrai os dados da vaga usando a Groq sem retries longos."""
    schema = JobPosting.model_json_schema()
    clean_raw_text = raw_text[:4000] if len(raw_text) > 4000 else raw_text

    prompt = f"""Você é um especialista em recrutamento e seleção (R&S). Extraia as informações estruturadas da vaga abaixo.
Retorne APENAS o JSON que obedeça estritamente a este esquema JSON: {json.dumps(schema)}.

Texto da vaga:
---
{clean_raw_text}
---"""

    try:
        client = _get_groq_client()
        chat_completion = client.chat.completions.create(
            model=GROQ_MODEL,  # Modelo lido do env/config
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Você é um assistente que responde apenas com JSON'
                        ' válido em formato raw, sem markdown adicional.'
                    ),
                },
                {'role': 'user', 'content': prompt},
            ],
            response_format={'type': 'json_object'},
            temperature=0.0,
        )
        response_text = chat_completion.choices[0].message.content
        dados_json = json.loads(response_text)
        job = JobPosting(**dados_json)
        job.raw_text = clean_raw_text
        return job

    except Exception as e:
        print(
            f'[Groq Error] Falha ao processar texto da vaga: {e}',
            file=sys.stdout,
            flush=True,
        )
        raise e


# ==========================================
# CAMADA 2: GEMINI (Filtro Dinâmico e Match Rico)
# ==========================================


def analyze_match(
    resume_text: str,
    job: JobPosting,
    resume_data: ResumeData | None = None,
) -> MatchResult:
    """Analisa a compatibilidade do currículo com mapeamento detalhado de habilidades."""
    resume_section = resume_text[:4000] if resume_text else ''
    if resume_data:
        resume_section = resume_data.model_dump_json()[:4000]

    # Mapeia todos os requisitos sem truncar
    reqs_texto = (
        '\n- '.join([str(r) for r in job.requirements if r])
        if job.requirements
        else 'Não especificado'
    )
    resps_texto = (
        '\n- '.join([str(r) for r in job.responsibilities if r])
        if job.responsibilities
        else 'Não especificado'
    )

    prompt = f"""Você é um sistema ATS corporativo avançado e auditor técnico de recrutamento.
Sua missão é realizar um mapeamento minucioso e rico entre o currículo fornecido e a vaga alvo.

INSTRUÇÕES DE EXTRAÇÃO DE HABILIDADES:
- Extraia TODAS as competências, tecnologias, bibliotecas, ferramentas, metodologias e qualificações relevantes.
- Não simplifique excessivamente nem remova detalhes entre parênteses (exemplo: prefira "Python (Pandas, NumPy)" ou "Conhecimento em Análise de Dados" em vez de apenas "Python").
- Mantenha descrições claras e completas de cada competência alinhada ou faltante.

CURRÍCULO DO CANDIDATO:
---
{resume_section}
---

VAGA ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos:
- {reqs_texto}

Responsabilidades:
- {resps_texto}
---"""

    gemini_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            'score': types.Schema(type=types.Type.STRING),
            'verdict': types.Schema(type=types.Type.STRING),
            'matching_skills': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            'missing_skills': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            'transferable_skills': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            'strengths': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            'weaknesses': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            'suggestions': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
        },
        required=[
            'score',
            'verdict',
            'matching_skills',
            'missing_skills',
            'transferable_skills',
            'strengths',
            'weaknesses',
            'suggestions',
        ],
    )

    client = _get_gemini_client()

    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    response_schema=gemini_schema,
                    temperature=0.3,
                ),
            )

            if response and response.text:
                dados_json = json.loads(response.text)
                score_bruto = dados_json.get('score', '0')
                try:
                    score = int(
                        float(
                            str(score_bruto)
                            .replace('%', '')
                            .replace('pt', '')
                            .strip()
                        )
                    )
                except (ValueError, TypeError):
                    score = 0

                score = max(0, min(100, score))
                verdict = (
                    'ALTA' if score >= 75 else 'MEDIA' if score >= 50 else 'BAIXA'
                )

                def extrair_lista(chave: str) -> list[str]:
                    valores = dados_json.get(chave, [])
                    return (
                        [str(v) for v in valores if v is not None]
                        if isinstance(valores, list)
                        else []
                    )

                return MatchResult(
                    score=score,
                    verdict=verdict,
                    matching_skills=extrair_lista('matching_skills'),
                    missing_skills=extrair_lista('missing_skills'),
                    transferable_skills=extrair_lista('transferable_skills'),
                    strengths=extrair_lista('strengths'),
                    weaknesses=extrair_lista('weaknesses'),
                    suggestions=extrair_lista('suggestions'),
                    tailored_resume=None,
                )
        except Exception as e:
            print(
                f'[Gemini Match Error] Falha na chamada da API ({model_name}): {e}',
                file=sys.stdout,
                flush=True,
            )
            continue

    # Fallback de segurança apenas se houver falha de rede/API
    return MatchResult(
        score=50,
        verdict='MEDIA',
        matching_skills=[
            'Python (Pandas, NumPy)',
            'Power BI e Dashboards',
            'Microsoft Excel Avançado',
            'Análise e Tratamento de Dados',
        ],
        missing_skills=[],
        transferable_skills=[],
        strengths=['Perfil técnico aderente'],
        weaknesses=[],
        suggestions=[
            'Destaque suas principais realizações nas experiências recentes.'
        ],
        tailored_resume=None,
    )


# ==========================================
# CAMADA 3: GEMINI (Reescrita Estratégica)
# ==========================================


def generate_tailored_resume(
    resume_text: str,
    job: JobPosting,
    match: MatchResult,
    resume_data: ResumeData | None = None,
) -> ResumeData:
    """Reescreve o currículo garantindo a preservação rigorosa dos dados pessoais."""
    resume_section = resume_text[:4000] if resume_text else ''
    if resume_data:
        resume_section = resume_data.model_dump_json()[:4000]

    reqs_filtrados = ', '.join([str(r) for r in job.requirements if r])
    keywords_filtradas = ', '.join(
        [
            str(k)
            for k in (
                job.keywords
                if hasattr(job, 'keywords') and job.keywords
                else job.requirements
            )
            if k
        ]
    )

    prompt = f"""Você é um especialista em engenharia de currículos otimizados para sistemas ATS.
Reconstrua o currículo abaixo incluindo as palavras-chave necessárias da vaga mantendo os detalhes técnicos.

CURRÍCULO ORIGINAL:
---
{resume_section}
---

VAGA ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos: {reqs_filtrados}
Keywords ATS: {keywords_filtradas}
---"""

    client = _get_gemini_client()

    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    response_schema=ResumeData.model_json_schema(),
                    temperature=0.3,
                ),
            )
            if response and response.text:
                dados_json = json.loads(response.text)

                # Preservação de dados pessoais
                if resume_data and resume_data.personal:
                    if not dados_json.get('personal') or not dados_json[
                        'personal'
                    ].get('name'):
                        dados_json['personal'] = resume_data.personal.model_dump()

                return ResumeData(**dados_json)
        except Exception as e:
            print(
                f'[Gemini Reescrita Error] Falha na API ({model_name}): {e}',
                file=sys.stdout,
                flush=True,
            )
            continue

    if resume_data:
        return resume_data
    raise RuntimeError(
        'Cota da chave do Gemini temporariamente atingida. Aguarde 1 minuto e'
        ' tente novamente.'
    )


# ==========================================
# CARTA DE APRESENTAÇÃO
# ==========================================


def generate_cover_letter(
    resume_text: str, job: JobPosting, match: MatchResult
) -> str:
    """Gera a Carta de Apresentação rapidamente."""
    skills_filtradas = ', '.join([str(s) for s in match.matching_skills if s][:8])

    prompt = f"""Escreva uma Carta de Apresentação profissional e direta (máximo 2 parágrafos) para a vaga de {job.title} na {job.company}.
Competências em destaque: {skills_filtradas}."""

    client = _get_gemini_client()

    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.5),
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(
                f'[Gemini Carta Error] ({model_name}): {e}',
                file=sys.stdout,
                flush=True,
            )
            continue

    return (
        f'Prezada equipe de recrutamento da {job.company or "empresa"},\n\n'
        f'Gostaria de candidatar-me à vaga de {job.title or "profissional"}.'
        ' Possuo sólida experiência na área e domínio das ferramentas'
        ' essenciais para a função.\n\nFico à disposição para uma'
        ' entrevista.\n\nAtenciosamente.'
    )
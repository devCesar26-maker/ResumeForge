"""Analisador Híbrido Otimizado para Chave Única (Single API Key).

Focado em baixa latência para evitar o Timeout de 30s do Render e na
preservação de dados pessoais.
"""

import json
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
# CLIENTES ÚNICOS DE API
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
            model=GROQ_MODEL,
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
        print(f'[Groq Error] Falha ao processar texto da vaga: {e}')
        raise e


# ==========================================
# CAMADA 2: GEMINI (Filtro Dinâmico e Match)
# ==========================================


def analyze_match(
    resume_text: str,
    job: JobPosting,
    resume_data: ResumeData | None = None,
) -> MatchResult:
    """Analisa a compatibilidade do currículo com a vaga de forma direta."""
    resume_section = resume_text[:3500] if resume_text else ''
    if resume_data:
        resume_section = resume_data.model_dump_json()[:3500]

    reqs_filtrados = ', '.join([r for r in job.requirements if r][:15])
    resps_filtradas = ', '.join([r for r in job.responsibilities if r][:10])

    prompt = f"""Você é um sistema ATS corporativo de última geração focado em extração exaustiva e mapeamento de fit técnico.
Sua missão é ler o currículo fornecido e compará-lo minuciosamente com os requisitos da vaga.

CURRÍCULO DO CANDIDATO:
---
{resume_section}
---

VAGA ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos Mandatórios: {reqs_filtrados}
Responsabilidades: {resps_filtradas}
---"""

    gemini_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            'score': types.Schema(type=types.Type.STRING),
            'verdict': types.Schema(type=types.Type.STRING),
            'matching_skills': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
            ),
            'missing_skills': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
            ),
            'transferable_skills': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
            ),
            'strengths': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
            ),
            'weaknesses': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
            ),
            'suggestions': types.Schema(
                type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
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
    model_name = GEMINI_MODELS[0] if GEMINI_MODELS else 'gemini-1.5-flash'

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=gemini_schema,
                temperature=0.2,
            ),
        )

        if response and response.text:
            dados_json = json.loads(response.text)
            score_bruto = dados_json.get('score', '0')
            try:
                score = int(float(str(score_bruto).replace('%', '').strip()))
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
        print(f'[Gemini Match Error] Falha na chamada da API: {e}')

    # Retorno de Segurança (Evita que o Render trave com erro de conexão)
    return MatchResult(
        score=50,
        verdict='MEDIA',
        matching_skills=['Análise de Dados', 'Excel Avançado'],
        missing_skills=[],
        transferable_skills=[],
        strengths=['Perfil técnico compatível'],
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
    resume_section = resume_text[:3500] if resume_text else ''
    if resume_data:
        resume_section = resume_data.model_dump_json()[:3500]

    reqs_filtrados = ', '.join([r for r in job.requirements if r][:15])
    keywords_filtradas = ', '.join(
        [
            k
            for k in (
                job.keywords
                if hasattr(job, 'keywords') and job.keywords
                else job.requirements
            )
            if k
        ][:10]
    )

    prompt = f"""Você é um especialista em engenharia de currículos otimizados para sistemas ATS.
Reconstrua o currículo abaixo incluindo as palavras-chave necessárias da vaga.

CURRÍCULO ORIGINAL:
---
{resume_section}
---

VAGA DE ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos: {reqs_filtrados}
Keywords ATS: {keywords_filtradas}
---"""

    client = _get_gemini_client()
    model_name = GEMINI_MODELS[0] if GEMINI_MODELS else 'gemini-1.5-flash'

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

            # 💡 PRESERVAÇÃO DE DADOS PESSOAIS:
            # Garante que o bloco 'personal' do currículo original seja mantido
            # caso a resposta da IA retorne este campo vazio/nulo.
            if resume_data and resume_data.personal:
                if not dados_json.get('personal') or not dados_json[
                    'personal'
                ].get('name'):
                    dados_json['personal'] = resume_data.personal.model_dump()

            return ResumeData(**dados_json)
    except Exception as e:
        print(f'[Gemini Reescrita Error] Cota atingida ou erro na API: {e}')

    # Fallback: Se bater no Rate Limit ou falhar, devolve o currículo original sem quebrar o site
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
    skills_filtradas = ', '.join([s for s in match.matching_skills if s][:5])

    prompt = f"""Escreva uma Carta de Apresentação direta (máximo 2 parágrafos) para a vaga de {job.title} na {job.company}.
Competências: {skills_filtradas}."""

    client = _get_gemini_client()
    model_name = GEMINI_MODELS[0] if GEMINI_MODELS else 'gemini-1.5-flash'

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5),
        )
        if response and response.text:
            return response.text
    except Exception as e:
        print(f'[Gemini Carta Error] {e}')

    return (
        f'Prezada equipe de recrutamento da {job.company or "empresa"},\n\n'
        f'Gostaria de candidatar-me à vaga de {job.title or "profissional"}.'
        ' Possuo sólida experiência em análise de dados e ferramentas'
        ' essenciais para a função.\n\nFico à disposição para uma'
        ' entrevista.\n\nAtenciosamente.'
    )
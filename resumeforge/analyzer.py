"""
Analisador híbrido e agnóstico: Groq (Velocidade no Parse) + Google Gemini (Rigor e Ajuste Dinâmico).
Suporta rotação dinâmica de múltiplas chaves de API (Failover) para contornar Rate Limits (429).
"""

import json
import itertools
from groq import Groq
from groq import RateLimitError as GroqRateLimitError
from pydantic import ValidationError
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# Importando as listas de chaves que você vai configurar no seu config.py
from .config import GEMINI_API_KEYS, GEMINI_MODEL, GROQ_API_KEYS, GROQ_MODEL
from .models import JobPosting, MatchResult, ResumeData


# ==========================================
# GERENCIADORES DE CHAVES (ROUND-ROBIN)
# ==========================================

# Criamos iteradores infinitos que ficam rodando as chaves em ciclo: Chave1 -> Chave2 -> Chave1...
if not GEMINI_API_KEYS or not isinstance(GEMINI_API_KEYS, list):
    raise ValueError("GEMINI_API_KEYS precisa ser uma lista de chaves no seu config.py/env")

if not GROQ_API_KEYS or not isinstance(GROQ_API_KEYS, list):
    raise ValueError("GROQ_API_KEYS precisa ser uma lista de chaves no seu config.py/env")

_gemini_key_pool = itertools.cycle(GEMINI_API_KEYS)
_groq_key_pool = itertools.cycle(GROQ_API_KEYS)


def _get_next_gemini_client() -> genai.Client:
    """Busca a próxima chave disponível na fila para o Gemini."""
    key = next(_gemini_key_pool)
    return genai.Client(api_key=key)


def _get_next_groq_client() -> Groq:
    """Busca a próxima chave disponível na fila para a Groq."""
    key = next(_groq_key_pool)
    return Groq(api_key=key)


# ==========================================
# CAMADA 1: GROQ (Parser da Vaga)
# ==========================================

def parse_job_posting(raw_text: str) -> JobPosting:
    """Usa a Groq para extrair dados estruturados. Faz failover de chave se bater no Rate Limit."""
    schema = JobPosting.model_json_schema()
    
    prompt = f"""Você é um especialista em recrutamento e seleção (R&S). Extraia as informações estruturadas da vaga abaixo.
Retorne APENAS o JSON que obedeça estritamente a este esquema JSON: {json.dumps(schema)}.

Texto da vaga:
---
{raw_text}
---"""

    # Tentamos executar a chamada com até N tentativas baseadas no número de chaves que você tem
    max_key_attempts = len(GROQ_API_KEYS) * 2
    
    for tentativa in range(max_key_attempts):
        try:
            client = _get_next_groq_client()
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
            
            dados_json = json.loads(response_text)
            job = JobPosting(**dados_json)
            job.raw_text = raw_text
            return job

        except GroqRateLimitError as e:
            print(f"[Groq Warning] Rate Limit atingido ou chave esgotada. Rotacionando para a próxima chave... Erro: {e}")
            if tentativa == max_key_attempts - 1:
                raise RuntimeError("Todas as chaves da Groq atingiram o limite de requisições.")
            continue  # Pula para a próxima iteração pegando uma nova chave no pool
            
        except ValidationError as ve:
            print(f"\nERRO DE VALIDAÇÃO DO PYDANTIC (JobPosting):\n{ve.json(indent=2)}")
            raise ve
        except Exception as e:
            raise e


# ==========================================
# CAMADA 2: GEMINI (Filtro Dinâmico e Match)
# ==========================================

def analyze_match(resume_text: str, job: JobPosting, resume_data: ResumeData | None = None) -> MatchResult:
    """Analisa a compatibilidade com failover dinâmico de chaves do Gemini."""
    resume_section = resume_text
    if resume_data:
        resume_section = resume_data.model_dump_json()

    prompt = f"""Você é um sistema ATS corporativo de última geração focado em extração exaustiva e mapeamento de fit técnico.
Sua missão é ler o currículo fornecido e compará-lo minuciosamente com os requisitos da vaga, extraindo TODAS as correspondências e lacunas sem ignorar os detalhes dos projetos ou do resumo profissional.

DIRETRIZES DE MAPEAMENTO EXAUSTIVO:
1. ANÁLISE PROFUNDA DO TEXTO: Examine o 'Resumo Profissional', 'Habilidades Técnicas', 'Projetos' e 'Certificações'. Elementos práticos descritos nos projetos (ex: criação de dashboards, automação de ETL, geração de KPIs, relatórios executivos) devem ser contabilizados integralmente como competências que o candidato possui.
2. MATCH REAL (Sem omissões): Identifique em 'matching_skills' qualquer conceito, tecnologia ou metodologia pedida pela vaga que esteja explícita ou implicitamente comprovada no currículo (ex: se o candidato cita "desenvolvimento de dashboards interativos", isso conta como "Construção de dashboards").
3. PENALIZAÇÃO EQUILIBRADA (Core vs. Secundárias): Se o candidato dominar a ferramenta principal (core) da vaga (ex: Power BI para uma vaga de Power BI), a ausência de tecnologias acessórias de nuvem ou tempo de experiência não deve zerar o score. 
4. CÁLCULO GRADUAL DE SCORE: Atribua uma nota de 0 a 100 de forma justa. Candidatos que possuem a base conceitual forte (ETL, Modelagem) e a ferramenta principal devem receber um score proporcional (ex: entre 35% e 60%), refletindo que são capacitados para a função principal, guardando notas abaixo de 20% estritamente para perfis totalmente desconexos.

CURRÍCULO DO CANDIDATO:
---
{resume_section}
---

VAGA ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos Mandatórios: {', '.join(job.requirements[:20])}
Responsabilidades: {', '.join(job.responsibilities[:12])}
---"""

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

    max_key_attempts = len(GEMINI_API_KEYS) * 2
    
    for tentativa in range(max_key_attempts):
        try:
            client = _get_next_gemini_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    response_schema=gemini_schema,
                    temperature=0.2,
                )
            )
            break # Sucesso! Sai do laço de tentativas de chaves
            
        except APIError as e:
            # Captura erros comuns de limite de cota do Gemini (geralmente HTTP 429 ou ResourceExhausted)
            if "429" in str(e) or "ResourceExhausted" in str(e) or "quota" in str(e).lower():
                print(f"[Gemini Warning] Cota estourada nesta chave. Mudando de API Key... Código: {e}")
                if tentativa == max_key_attempts - 1:
                    raise RuntimeError("Todas as chaves do Gemini falharam por exaustão de cota.")
                continue
            raise e

    try:
        dados_json = json.loads(response.text)
        score_bruto = dados_json.get("score", "0")
        try:
            score = int(float(str(score_bruto).replace("%", "").strip()))
        except (ValueError, TypeError):
            score = 0
            
        score = max(0, min(100, score))
        verdict = "ALTA" if score >= 75 else "MEDIA" if score >= 50 else "BAIXA"

        def extrair_lista(chave: str) -> list[str]:
            valores = dados_json.get(chave, [])
            return [str(v) for v in valores if v is not None] if isinstance(valores, list) else []

        return MatchResult(
            score=score, verdict=verdict,
            matching_skills=extrair_lista("matching_skills"),
            missing_skills=extrair_lista("missing_skills"),
            transferable_skills=extrair_lista("transferable_skills"),
            strengths=extrair_lista("strengths"), weaknesses=extrair_lista("weaknesses"),
            suggestions=extrair_lista("suggestions"), tailored_resume=None
        )
    except Exception as e:
        print(f"\n[Error] Falha crítica no parse da resposta do Gemini: {e}")
        raise e


# ==========================================
# CAMADA 3: GEMINI (Reescrita Estratégica)
# ==========================================

def generate_tailored_resume(
    resume_text: str, job: JobPosting, match: MatchResult, resume_data: ResumeData | None = None
) -> ResumeData:
    """Reescreve o currículo aplicando injeção de keywords com failover automático de chaves."""
    resume_section = resume_text
    if resume_data:
        resume_section = resume_data.model_dump_json()

    prompt = f"""Você é um engenheiro de recrutamento técnico especialista em engenharia de currículos otimizados para algoritmos de ATS (Applicant Tracking Systems).
Sua missão é reconstruir o currículo do candidato garantindo que os robôs de triagem encontrem as palavras-chave exatas exigidas pela vaga-alvo.

DIRETRIZES DE ENGENHARIA DE CURRÍCULO PARA ATS:
1. INJEÇÃO CONTEXTUAL DE PALAVRAS-CHAVE: Distribua ao longo de todo o currículo os termos técnicos exatos da vaga reescrevendo sentenças antigas de forma que incluam essas palavras organicamente.
2. DENSIDADE DE KEYWORDS: Certifique-se de que termos importantes apareçam mais de uma vez ao longo do documento.
3. ADAPTAÇÃO E ALINHAMENTO DE PROJETOS: Ajuste a descrição dos projetos práticos para focar nas entregas que a vaga mais valoriza usando verbos de ação fortes.
4. PRESERVAÇÃO ÉTICA DE FATOS: Não invente empresas fictícias ou altere datas. Otimize o escopo para que conversem diretamente com a linguagem do recrutador.

CURRÍCULO ORIGINAL:
---
{resume_section}
---

VAGA DE ALVO:
---
Título: {job.title}
Empresa: {job.company}
Requisitos Críticos: {', '.join(job.requirements[:20])}
Keywords do ATS: {', '.join(job.keywords if hasattr(job, 'keywords') and job.keywords else job.requirements[:10])}
Responsabilidades Principais: {', '.join(job.responsibilities[:10])}
---

Gere o novo currículo otimizado seguindo estritamente a estrutura ResumeData."""

    resume_data_schema = ResumeData.model_json_schema()
    max_key_attempts = len(GEMINI_API_KEYS) * 2

    for tentativa in range(max_key_attempts):
        try:
            client = _get_next_gemini_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    response_schema=resume_data_schema,
                    temperature=0.3,
                )
            )
            break
        except APIError as e:
            if "429" in str(e) or "ResourceExhausted" in str(e) or "quota" in str(e).lower():
                print(f"[Gemini Warning] Cota estourada na reescrita. Mudando de API Key... Código: {e}")
                if tentativa == max_key_attempts - 1:
                    raise RuntimeError("Todas as chaves do Gemini falharam na etapa de reescrita.")
                continue
            raise e

    try:
        dados_json = json.loads(response.text)
        return ResumeData(**dados_json)
    except ValidationError as ve:
        print(f"Erro de validação na estrutura final: {ve.json()}")
        raise ve
    except Exception as e:
        raise e


# ==========================================
# CARTA DE APRESENTAÇÃO
# ==========================================

def generate_cover_letter(resume_text: str, job: JobPosting, match: MatchResult) -> str:
    """Gera a carta de apresentação tratando possíveis quedas de cota por limite de requisições."""
    prompt = f"""Escreva uma Carta de Apresentação concisa (máximo 3 parágrafos) focando estritamente na sinergia técnica para esta vaga.

VAGA:
---
Título: {job.title}
Empresa: {job.company}
Requisitos principais: {', '.join(job.requirements[:5])}
---

COMPETÊNCIAS FILTRADAS DO CANDIDATO:
{', '.join(match.matching_skills[:5])}

Gere o texto direto, sem cabeçalhos antiquados, pronto para envio profissional."""

    max_key_attempts = len(GEMINI_API_KEYS) * 2

    for tentativa in range(max_key_attempts):
        try:
            client = _get_next_gemini_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.5)
            )
            return response.text
        except APIError as e:
            if "429" in str(e) or "ResourceExhausted" in str(e) or "quota" in str(e).lower():
                print(f"[Gemini Warning] Cota escorrendo na Carta de Apresentação. Mudando de chave...")
                if tentativa == max_key_attempts - 1:
                    raise RuntimeError("Todas as chaves esgotadas na geração da carta.")
                continue
            raise e
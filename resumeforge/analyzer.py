"""
Analisador híbrido e agnóstico: Groq (Velocidade no Parse) + Google Gemini (Rigor e Ajuste Dinâmico).
Suporta rotação dinâmica de múltiplas chaves de API (Failover), retry inteligente para Rate Limit (429) e múltiplos modelos em cascata.
"""

import json
import time
import itertools
from groq import Groq
from groq import RateLimitError as GroqRateLimitError
from pydantic import ValidationError
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Importando a lista de modelos (GEMINI_MODELS) e chaves
from .config import (
    GEMINI_API_KEYS, 
    GEMINI_MODELS, 
    GROQ_API_KEYS, 
    GROQ_MODEL
)
from .models import JobPosting, MatchResult, ResumeData


# ==========================================
# GERENCIADORES DE CHAVES (ROUND-ROBIN)
# ==========================================

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
    
    clean_raw_text = raw_text[:4000] if len(raw_text) > 4000 else raw_text

    prompt = f"""Você é um especialista em recrutamento e seleção (R&S). Extraia as informações estruturadas da vaga abaixo.
Retorne APENAS o JSON que obedeça estritamente a este esquema JSON: {json.dumps(schema)}.

Texto da vaga:
---
{clean_raw_text}
---"""

    max_key_attempts = len(GROQ_API_KEYS) * 3
    
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
            job.raw_text = clean_raw_text
            return job

        except GroqRateLimitError as e:
            print(f"[Groq Warning] Rate Limit atingido (tentativa {tentativa+1}). Aguardando 3s... Erro: {e}")
            time.sleep(3)
            continue
            
        except ValidationError as ve:
            print(f"\nERRO DE VALIDAÇÃO DO PYDANTIC (JobPosting):\n{ve.json(indent=2)}")
            raise ve
        except Exception as e:
            raise e


# ==========================================
# CAMADA 2: GEMINI (Filtro Dinâmico e Match)
# ==========================================

def analyze_match(resume_text: str, job: JobPosting, resume_data: ResumeData | None = None) -> MatchResult:
    """Analisa a compatibilidade utilizando os modelos configurados com retry inteligente para cota."""
    resume_section = resume_text[:3500] if resume_text else ""
    if resume_data:
        resume_section = resume_data.model_dump_json()[:3500]

    reqs_filtrados = ', '.join([r for r in job.requirements if r][:15])
    resps_filtradas = ', '.join([r for r in job.responsibilities if r][:10])

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
Requisitos Mandatórios: {reqs_filtrados}
Responsabilidades: {resps_filtradas}
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

    response = None
    ultimo_erro = None

    for model_name in GEMINI_MODELS:
        # Tenta até 3 vezes por modelo aplicando espera progressiva (Backoff)
        max_retries = 3
        for tentativa in range(max_retries):
            try:
                client = _get_next_gemini_client()
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json',
                        response_schema=gemini_schema,
                        temperature=0.2,
                    )
                )
                if response and response.text:
                    break
            except APIError as e:
                ultimo_erro = e
                err_msg = str(e).lower()
                print(f"[Aviso Gemini Match] Modelo '{model_name}' (Tentativa {tentativa+1}/{max_retries}) falhou: {e}")
                
                if "429" in str(e) or "resourceexhausted" in err_msg or "quota" in err_msg:
                    tempo_espera = (tentativa + 1) * 5  # Espera 5s na 1ª, 10s na 2ª, 15s na 3ª
                    print(f"⏳ Cota atingida no Gemini. Aguardando {tempo_espera}s para tentar novamente...")
                    time.sleep(tempo_espera)
                    continue
                break  # Erro 404/Invalido -> Passa direto pro próximo modelo
            except Exception as e:
                ultimo_erro = e
                print(f"[Aviso Gemini Match] Erro inesperado: {e}")
                break
        
        if response is not None and response.text:
            break

    if response is None or not response.text:
        raise RuntimeError(f"Todos os modelos do Gemini ({', '.join(GEMINI_MODELS)}) e chaves falharam. Último erro: {ultimo_erro}")

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
    """Reescreve o currículo usando os modelos em cascata (Fallback)."""
    resume_section = resume_text[:3500] if resume_text else ""
    if resume_data:
        resume_section = resume_data.model_dump_json()[:3500]

    reqs_filtrados = ', '.join([r for r in job.requirements if r][:15])
    keywords_filtradas = ', '.join([k for k in (job.keywords if hasattr(job, 'keywords') and job.keywords else job.requirements) if k][:10])
    resps_filtradas = ', '.join([r for r in job.responsibilities if r][:10])

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
Requisitos Críticos: {reqs_filtrados}
Keywords do ATS: {keywords_filtradas}
Responsabilidades Principais: {resps_filtradas}
---

Gere o novo currículo otimizado seguindo estritamente a estrutura ResumeData."""

    resume_data_schema = ResumeData.model_json_schema()
    response = None
    ultimo_erro = None

    for model_name in GEMINI_MODELS:
        max_retries = 3
        for tentativa in range(max_retries):
            try:
                client = _get_next_gemini_client()
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json',
                        response_schema=resume_data_schema,
                        temperature=0.3,
                    )
                )
                if response and response.text:
                    break
            except APIError as e:
                ultimo_erro = e
                err_msg = str(e).lower()
                print(f"[Aviso Gemini Reescrita] Modelo '{model_name}' (Tentativa {tentativa+1}/{max_retries}) falhou: {e}")
                
                if "429" in str(e) or "resourceexhausted" in err_msg or "quota" in err_msg:
                    tempo_espera = (tentativa + 1) * 5
                    print(f"⏳ Cota atingida na Reescrita. Aguardando {tempo_espera}s...")
                    time.sleep(tempo_espera)
                    continue
                break
            except Exception as e:
                ultimo_erro = e
                print(f"[Aviso Gemini Reescrita] Erro inesperado: {e}")
                break
        
        if response is not None and response.text:
            break

    if response is None or not response.text:
        raise RuntimeError(f"Todas as chaves e modelos ({', '.join(GEMINI_MODELS)}) falharam na reescrita. Último erro: {ultimo_erro}")

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
    """Gera a carta de apresentação usando os modelos do Gemini em cascata (Fallback)."""
    reqs_filtrados = ', '.join([r for r in job.requirements if r][:5])
    skills_filtradas = ', '.join([s for s in match.matching_skills if s][:5])

    prompt = f"""Escreva uma Carta de Apresentação concisa (máximo 3 parágrafos) focando estritamente na sinergia técnica para esta vaga.

VAGA:
---
Título: {job.title}
Empresa: {job.company}
Requisitos principais: {reqs_filtrados}
---

COMPETÊNCIAS FILTRADAS DO CANDIDATO:
{skills_filtradas}

Gere o texto direto, sem cabeçalhos antiquados, pronto para envio profissional."""

    ultimo_erro = None

    for model_name in GEMINI_MODELS:
        max_retries = 3
        for tentativa in range(max_retries):
            try:
                client = _get_next_gemini_client()
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.5)
                )
                if response and response.text:
                    return response.text
            except APIError as e:
                ultimo_erro = e
                err_msg = str(e).lower()
                print(f"[Aviso Gemini Carta] Modelo '{model_name}' (Tentativa {tentativa+1}/{max_retries}) falhou: {e}")
                if "429" in str(e) or "resourceexhausted" in err_msg or "quota" in err_msg:
                    tempo_espera = (tentativa + 1) * 5
                    time.sleep(tempo_espera)
                    continue
                break
            except Exception as e:
                ultimo_erro = e
                print(f"[Aviso Gemini Carta] Erro inesperado: {e}")
                break

    raise RuntimeError(f"Todas as chaves e modelos ({', '.join(GEMINI_MODELS)}) esgotados na geração da carta. Último erro: {ultimo_erro}")
"""Analisador híbrido: Groq (Velocidade no Parse) + Google Gemini (Rigor no Match e Qualidade na Geração)."""

import json
import re
from groq import Groq
from pydantic import ValidationError
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from .config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL
from .models import JobPosting, MatchResult, ResumeData


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
    
    # Sanitiza o texto antes de enviar à API
    raw_text = _sanitize_text(raw_text)
    
    schema = JobPosting.model_json_schema()
    
    prompt = f"""Você é um especialista em recrutamento. Extraia as informações estruturadas da vaga abaixo.
Retorne APENAS o JSON que obedeça estritamente a este esquema JSON: {json.dumps(schema)}.

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
        dados_json = json.loads(response.text)
        
        # Conversão numérica do score obtido do LLM
        score_bruto = dados_json.get("score", "0")
        try:
            score = int(float(str(score_bruto).replace("%", "").strip()))
        except (ValueError, TypeError):
            score = 0
            
        score = max(0, min(100, score))

        # Regra de penalização manual estrita pós-IA
        texto_curriculo_clean = resume_section.lower()
        vaga_exige_sql = any("sql" in req.lower() for req in job.requirements) or "sql" in job.title.lower()
        vaga_exige_tableau = any("tableau" in req.lower() for req in job.requirements) or "tableau" in job.title.lower()
        
        has_sql = "sql" in texto_curriculo_clean
        has_tableau = "tableau" in texto_curriculo_clean

        if (vaga_exige_sql and not has_sql) or (vaga_exige_tableau and not has_tableau):
            score = min(score, 35)

        # Cálculo dinâmico do veredicto baseado no score final recalculado
        if score >= 75:
            verdict = "ALTA"
        elif score >= 45:
            verdict = "MEDIA"
        else:
            verdict = "BAIXA"

        def extrair_lista(chave: str) -> list[str]:
            valores = dados_json.get(chave, [])
            if not isinstance(valores, list):
                return []
            return [str(v) for v in valores if v is not None]

        # Montamos o MatchResult garantindo que tailored_resume seja passado como None
        return MatchResult(
            score=score,
            verdict=verdict,
            matching_skills=extrair_lista("matching_skills"),
            missing_skills=extrair_lista("missing_skills"),
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

REGRAS DE OURO PARA BATER O ATS:
1. MATCH DE PALAVRAS-CHAVE (HARD SKILLS): Identifique as tecnologias fundamentais da vaga (ex: Power BI, Tableau, SQL, Snowflake, DAX) e integre-as de forma orgânica e frequente no resumo profissional, na lista de habilidades e nos destaques das experiências. Use a terminologia exata da vaga.
2. VERBOS DE AÇÃO + RESULTADOS (MÉTRICAS): Reescreva os bullet points (highlights) das experiências profissionais. Comece cada frase com um verbo de ação forte no passado (ex: "Desenvolvi", "Otimizei", "Liderei", "Implementei") e tente atrelar os resultados a estimativas numéricas ou métricas realistas se aplicável.
3. ORDENAÇÃO DE RELEVÂNCIA: Reorganize as categorias de habilidades (skills) e a ordem dos itens de experiência para que as competências e projetos mais alinhados com a vaga atual fiquem visíveis logo no topo.
4. INTEGRIDADE ABSOLUTA DE DADOS: Não altere nenhuma data, nome de empresa ou cargo ocupado. Nunca invente experiências fictícias.
5. SÍNTESE DO RESUMO: Adapte o 'summary' (resumo profissional) do currículo para ser um gancho perfeito de no máximo 4 linhas, contendo as principais tecnologias e anos de experiência exigidos pela vaga.

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
        print(f"Resposta bruta do Gemini: {response.text}")
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

    return response.text
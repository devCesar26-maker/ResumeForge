"""Modelos de dados Pydantic v2 para o ResumeForge.

Define todas as estruturas usadas para representar currículos,
vagas de emprego e resultados de compatibilidade.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Blocos do currículo ──────────────────────────────────────────────


class PersonalInfo(BaseModel):
    """Informações pessoais e de contato do candidato."""

    name: str
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    location: str = ""


class Experience(BaseModel):
    """Uma entrada de experiência profissional."""

    company: str
    role: str
    period: str
    location: str = ""
    highlights: list[str] = Field(default_factory=list)


class Education(BaseModel):
    """Uma entrada de formação acadêmica."""

    institution: str
    degree: str
    period: str
    details: list[str] = Field(default_factory=list)


class Project(BaseModel):
    """Um projeto pessoal ou profissional relevante."""

    name: str
    description: str
    technologies: list[str] = Field(default_factory=list)
    url: str = ""


class Language(BaseModel):
    """Idioma e nível de proficiência."""

    name: str
    level: str


class Certification(BaseModel):
    """Certificação ou curso relevante."""

    name: str
    issuer: str = ""
    date: str = ""
    url: str = ""


class SkillCategory(BaseModel):
    """Categoria de habilidades."""

    category: str
    items: list[str]


# ── Currículo completo ──────────────────────────────────────────────


class ResumeData(BaseModel):
    """Representação completa de um currículo."""

    personal: PersonalInfo
    summary: str = ""
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)


# ── Vaga de emprego ─────────────────────────────────────────────────


class JobPosting(BaseModel):
    """Dados estruturados de uma vaga de emprego."""

    title: str = "Não especificado"
    company: str = "Empresa Confidencial"
    location: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    seniority_level: str = ""
    raw_text: str = ""


# ── Resultado de compatibilidade ────────────────────────────────────


class MatchResult(BaseModel):
    """Resultado da análise de compatibilidade currículo ↔ vaga."""

    score: int = Field(default=0, ge=0, le=100, description="Pontuação de compatibilidade 0-100")
    verdict: str = Field(default="BAIXA", description="ALTA, MEDIA ou BAIXA")
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    transferable_skills: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    tailored_resume: ResumeData | None = None
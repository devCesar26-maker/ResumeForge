"""Configurações globais do ResumeForge.

Carrega variáveis de ambiente via .env e define caminhos,
chaves de API, modelos de IA e limiares padrão usados em todo o projeto.
Suporta rotação de chaves e fallback de modelos para Groq e Gemini.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Caminhos ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TEMPLATES_DIR = PROJECT_ROOT / "templates"

DATA_DIR = PROJECT_ROOT / "tmp"
UPLOAD_FOLDER = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"

DATA_DIR.mkdir(exist_ok=True, parents=True)
UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)


# ── APIs de Inteligência Artificial ──────────────────────────────────

# 1. GEMINI - Chaves de API (Suporta múltiplas chaves separadas por vírgula)
_gemini_keys_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS: list[str] = [k.strip() for k in _gemini_keys_raw.split(",") if k.strip()]

# 2. GEMINI - Lista de Modelos com Fallback (Lê GEMINI_MODEL do .env ex: gemini-2.5-flash,gemini-2.0-flash)
_gemini_models_raw = os.getenv("GEMINI_MODEL", "gemini-2.5-flash,gemini-2.0-flash")
GEMINI_MODELS: list[str] = [
    m.replace("models/", "").strip() 
    for m in _gemini_models_raw.split(",") 
    if m.strip()
]


# 3. GROQ - Chaves de API e Modelo
_groq_keys_raw = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
GROQ_API_KEYS: list[str] = [k.strip() for k in _groq_keys_raw.split(",") if k.strip()]
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()


# ── Validação Preventiva das Chaves e Modelos ────────────────────────

if not GEMINI_API_KEYS:
    print("[Aviso] Nenhuma chave configurada para o Gemini. Verifique GEMINI_API_KEYS.")
if not GEMINI_MODELS:
    GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
if not GROQ_API_KEYS:
    print("[Aviso] Nenhuma chave configurada para a Groq. Verifique GROQ_API_KEYS.")


# ── Aplicação e Execução ──────────────────────────────────────────────

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8501))
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))


# ── Limiares de Compatibilidade ──────────────────────────────────────

MATCH_THRESHOLD_LOW: int = 40
MATCH_THRESHOLD_HIGH: int = 70


# ── Caminho Padrão do Currículo Mestre ───────────────────────────────

DEFAULT_RESUME_PATH: Path = DATA_DIR / "my_resume.yaml"
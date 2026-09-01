"""Configurações globais do ResumeForge.

Carrega variáveis de ambiente via .env e define caminhos,
chaves de API e limiares padrão usados em todo o projeto.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Caminhos ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent

load_dotenv(PROJECT_ROOT / ".env")
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Garante que o diretório de saída existe
OUTPUT_DIR.mkdir(exist_ok=True)

# ── API ──────────────────────────────────────────────────────────────

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")  # O modelo mais rápido e inteligente para JSON estruturado na Groq

# ── Limiares de compatibilidade ──────────────────────────────────────

MATCH_THRESHOLD_LOW: int = 40
MATCH_THRESHOLD_HIGH: int = 70

# ── Caminho padrão do currículo ──────────────────────────────────────

DEFAULT_RESUME_PATH: Path = DATA_DIR / "my_resume.yaml"

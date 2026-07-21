"""Configurações globais do ResumeForge.

Carrega variáveis de ambiente via .env e define caminhos,
chaves de API e limiares padrão usados em todo o projeto.
Suporta fallback de chaves singulares para Groq e Gemini.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Caminhos ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
# Carrega o .env local (no Render não causará erros, pois as variáveis reais vêm do painel)
load_dotenv(PROJECT_ROOT / ".env")

TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Como não há mais variáveis de caminho no .env, definimos tudo relativo à raiz de forma direta
DATA_DIR = PROJECT_ROOT / "tmp"
UPLOAD_FOLDER = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"

# Garante que as pastas locais temporárias existam na inicialização do servidor
DATA_DIR.mkdir(exist_ok=True, parents=True)
UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

# ── APIs de Inteligência Artificial ──────────────────────────────────

# 1. GEMINI (Lê GEMINI_API_KEY do seu .env e joga na lista de rotação do backend)
_gemini_raw = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS: list[str] = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# 2. GROQ (Lê GROQ_API_KEY do seu .env)
_groq_raw = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
GROQ_API_KEYS: list[str] = [k.strip() for k in _groq_raw.split(",") if k.strip()]
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


# ── Validação Preventiva das Chaves ──────────────────────────────────

if not GEMINI_API_KEYS:
    print("[Aviso] Nenhuma chave configurada para o Gemini. Verifique GEMINI_API_KEY.")
if not GROQ_API_KEYS:
    print("[Aviso] Nenhuma chave configurada para a Groq. Verifique GROQ_API_KEY.")


# ── Aplicação e execução ──────────────────────────────────────────────

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8501))
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# Caso o MAX_CONTENT_LENGTH suma do ambiente, o padrão de 16MB é mantido de forma segura
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

# ── Limiares de compatibilidade ──────────────────────────────────────

MATCH_THRESHOLD_LOW: int = 40
MATCH_THRESHOLD_HIGH: int = 70

# ── Caminho padrão do currículo ──────────────────────────────────────

DEFAULT_RESUME_PATH: Path = DATA_DIR / "my_resume.yaml"
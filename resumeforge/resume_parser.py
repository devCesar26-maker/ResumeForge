"""Módulo de extração de texto e parse de currículos mestre em múltiplos formatos."""

import yaml
from pathlib import Path
from .models import ResumeData


def parse_resume(filepath: str | Path) -> tuple[str, ResumeData | None]:
    """Parse resume file.

    Returns:
        Tuple of (raw_text, structured_data_or_None)
        If YAML, structured_data will be a ResumeData instance.
        For other formats, structured_data will be None (Gemini will parse it).
    """
    filepath = Path(filepath)
    suffix = filepath.suffix.lower()

    if not filepath.exists():
        raise FileNotFoundError(f'Arquivo não encontrado: {filepath}')

    if suffix in ('.yaml', '.yml'):
        return _parse_yaml(filepath)
    elif suffix == '.pdf':
        return _parse_pdf(filepath), None
    elif suffix == '.docx':
        return _parse_docx(filepath), None
    elif suffix in ('.tex', '.txt', '.md'):
        return filepath.read_text(encoding='utf-8', errors='ignore'), None
    else:
        # Tenta ler como texto puro com tolerância a caracteres estranhos
        try:
            return filepath.read_text(encoding='utf-8', errors='ignore'), None
        except Exception as e:
            raise ValueError(f"Formato de arquivo não suportado ou binário inválido: {suffix}. Erro: {e}")


def _parse_yaml(filepath: Path) -> tuple[str, ResumeData]:
    raw = filepath.read_text(encoding='utf-8')
    data = yaml.safe_load(raw)
    resume = ResumeData(**data)
    return raw, resume


def _parse_pdf(filepath: Path) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise ImportError('Instale PyPDF2 para ler PDFs: pip install PyPDF2')

    reader = PdfReader(str(filepath))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return '\n'.join(text_parts)


def _parse_docx(filepath: Path) -> str:
    """Extrai texto de arquivos Word, capturando parágrafos e conteúdos dentro de tabelas."""
    try:
        from docx import Document
    except ImportError:
        raise ImportError('Instale python-docx para ler DOCX: pip install python-docx')

    doc = Document(str(filepath))
    text_parts = []

    # 1. Captura textos de parágrafos normais do documento
    for p in doc.paragraphs:
        if p.text.strip():
            text_parts.append(p.text.strip())

    # 2. Captura textos que possam estar escondidos em tabelas de formatação/layout
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                # Evita duplicar blocos de texto idênticos se houver células mescladas
                celula_texto = cell.text.strip()
                if celula_texto and celula_texto not in text_parts:
                    text_parts.append(celula_texto)

    return '\n'.join(text_parts)
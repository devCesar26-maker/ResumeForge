"""Módulo legado — geração LaTeX foi removida.

A geração de currículos agora é feita exclusivamente via
``resumeforge.word_generator`` (formato .docx).
"""

from pathlib import Path


def generate_latex(*args, **kwargs) -> Path:
    raise RuntimeError(
        "Geração LaTeX foi removida do projeto. "
        "Use resumeforge.word_generator.generate_word() em vez disso."
    )


def compile_pdf(*args, **kwargs) -> Path | None:
    raise RuntimeError(
        "Compilação LaTeX/PDF foi removida do projeto. "
        "Use resumeforge.word_generator.generate_word() em vez disso."
    )

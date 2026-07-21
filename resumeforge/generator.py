"""Gerador de currículo LaTeX a partir de dados estruturados."""

import subprocess
import shutil
import uuid  
from pathlib import Path

import jinja2

from .config import TEMPLATES_DIR, OUTPUT_DIR
from .models import ResumeData


def _get_latex_env() -> jinja2.Environment:
    """Cria ambiente Jinja2 com delimitadores compatíveis com LaTeX."""
    return jinja2.Environment(
        block_start_string="\\BLOCK{",
        block_end_string="}",
        variable_start_string="\\VAR{",
        variable_end_string="}",
        comment_start_string="\\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        line_comment_prefix="%#",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    )


def _escape_latex(text: str) -> str:
    """Escapa caracteres especiais do LaTeX de forma segura."""
    if not text:
        return ""
        
    # A barra invertida deve ser substituída PRIMEIRO, 
    # senão ela vai escapar os escapes das outras substituições subsequentes!
    text = text.replace("\\", "\\textbackslash{}")
    
    special_chars = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for char, replacement in special_chars.items():
        text = text.replace(char, replacement)
    return text


def generate_latex(
    resume: ResumeData,
    output_name: str = "resume_tailored",
) -> Path:
    """Gera arquivo ``.tex`` a partir dos dados do currículo.
    
    Adiciona um sufixo único se necessário para evitar conflitos de IO concorrentes.
    """
    env = _get_latex_env()
    template = env.get_template("resume.tex.j2")

    # Prepara dados com escaping LaTeX
    data = _prepare_data(resume)

    rendered = template.render(**data)

    # Se você for rodar em ambiente web/concorrente, é melhor usar nomes dinâmicos:
    # Exemplo: f"{output_name}_{uuid.uuid4().hex[:8]}"
    output_path = OUTPUT_DIR / f"{output_name}.tex"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    return output_path


def _prepare_data(resume: ResumeData) -> dict:
    """Prepara dados do currículo para o template, escapando caracteres LaTeX."""

    def escape_str(s: str) -> str:
        return _escape_latex(s) if s else ""

    def escape_list(lst: list[str]) -> list[str]:
        return [_escape_latex(item) for item in lst] if lst else []

    # Proteção caso links venham nulos da validação da IA
    def safe_url(url: str | None) -> str:
        return url if url else ""

    return {
        "personal": {
            "name": escape_str(resume.personal.name),
            "email": escape_str(resume.personal.email),
            "phone": escape_str(resume.personal.phone),
            "linkedin": safe_url(resume.personal.linkedin),  
            "github": safe_url(resume.personal.github),
            "portfolio": safe_url(resume.personal.portfolio),
            "location": escape_str(resume.personal.location),
        },
        "summary": escape_str(resume.summary),
        "experience": [
            {
                "company": escape_str(exp.company),
                "role": escape_str(exp.role),
                "period": escape_str(exp.period),
                "location": escape_str(exp.location),
                "highlights": escape_list(exp.highlights),
            }
            for exp in resume.experience
        ],
        "education": [
            {
                "institution": escape_str(edu.institution),
                "degree": escape_str(edu.degree),
                "period": escape_str(edu.period),
                "details": escape_list(edu.details),
            }
            for edu in resume.education
        ],
        "skills": {
            escape_str(sc.category): escape_list(sc.items)
            for sc in resume.skills
        },
        "projects": [
            {
                "name": escape_str(proj.name),
                "description": escape_str(proj.description),
                "technologies": escape_list(proj.technologies),
                "url": safe_url(proj.url),
            }
            for proj in resume.projects
        ],
        "languages": [
            {"name": escape_str(lang.name), "level": escape_str(lang.level)}
            for lang in resume.languages
        ],
        "certifications": [
            {
                "name": escape_str(cert.name),
                "issuer": escape_str(cert.issuer),
                "date": escape_str(cert.date),
                "url": safe_url(cert.url),
            }
            for cert in resume.certifications
        ],
    }


def compile_pdf(tex_path: Path) -> Path | None:
    """Compila ``.tex`` para ``.pdf`` usando ``pdflatex`` de forma segura."""
    if not shutil.which("pdflatex"):
        print("[LaTeX Error] pdflatex não está instalado ou disponível no PATH.")
        return None

    try:
        pdflatex_cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory",
            str(tex_path.parent),
            str(tex_path),
        ]

        # Primeira execução
        subprocess.run(
            pdflatex_cmd,
            capture_output=True,
            timeout=45, # Reduzido ligeiramente (60s é muito tempo travando thread)
            check=True,
        )
        # Segunda execução para resolver referências e contadores de páginas
        subprocess.run(
            pdflatex_cmd,
            capture_output=True,
            timeout=45,
            check=True,
        )

        pdf_path = tex_path.with_suffix(".pdf")
        if pdf_path.exists():
            # Limpa arquivos auxiliares de forma segura (.log, .aux, .out, etc.)
            for ext in (".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk"):
                aux_file = tex_path.with_suffix(ext)
                if aux_file.exists():
                    aux_file.unlink()
            return pdf_path
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[LaTeX Compilation Error] Falha ao compilar {tex_path.name}.")
        # Se falhar, você pode inspecionar o arquivo .log antes dele ser apagado caso queira fazer debug
        if hasattr(e, 'output') and e.output:
            print(f"Log do compilador: {e.output.decode('utf-8', errors='ignore')[:500]}")
            
    return None
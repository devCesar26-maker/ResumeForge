"""Gerador de currículo LaTeX a partir de dados estruturados."""

import subprocess
import shutil
from pathlib import Path

import jinja2

from .config import TEMPLATES_DIR, OUTPUT_DIR
from .models import ResumeData


def _get_latex_env() -> jinja2.Environment:
    """Cria ambiente Jinja2 com delimitadores compatíveis com LaTeX.

    Utiliza delimitadores customizados (``\\BLOCK{}``, ``\\VAR{}``, etc.)
    para evitar conflitos com a sintaxe nativa do LaTeX, permitindo que
    o template seja editado normalmente em qualquer editor LaTeX.

    Returns:
        Ambiente Jinja2 configurado com loader apontando para o
        diretório de templates.
    """
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
    """Escapa caracteres especiais do LaTeX.

    Converte caracteres reservados do LaTeX (``&``, ``%``, ``$``, ``#``,
    ``_``, ``{``, ``}``, ``~``, ``^``) para suas representações seguras,
    evitando erros de compilação no documento final.

    Args:
        text: Texto original a ser escapado.

    Returns:
        Texto com caracteres especiais devidamente escapados.
    """
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

    Renderiza o template ``resume.tex.j2`` com os dados fornecidos,
    aplicando escaping LaTeX em todos os campos de texto. O arquivo
    resultante é salvo no diretório de saída configurado.

    Args:
        resume: Dados estruturados do currículo.
        output_name: Nome base do arquivo de saída (sem extensão).

    Returns:
        Caminho absoluto para o arquivo ``.tex`` gerado.
    """
    env = _get_latex_env()
    template = env.get_template("resume.tex.j2")

    # Prepara dados com escaping LaTeX
    data = _prepare_data(resume)

    rendered = template.render(**data)

    output_path = OUTPUT_DIR / f"{output_name}.tex"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    return output_path


def _prepare_data(resume: ResumeData) -> dict:
    """Prepara dados do currículo para o template, escapando caracteres LaTeX.

    Percorre todos os campos do modelo ``ResumeData`` e aplica escaping
    nos valores de texto. URLs utilizadas em ``\\href`` não são escapadas
    para preservar a funcionalidade dos hyperlinks.

    Args:
        resume: Dados estruturados do currículo.

    Returns:
        Dicionário pronto para ser passado ao template Jinja2.
    """

    def escape_str(s: str) -> str:
        return _escape_latex(s) if s else ""

    def escape_list(lst: list[str]) -> list[str]:
        return [_escape_latex(item) for item in lst]

    return {
        "personal": {
            "name": escape_str(resume.personal.name),
            "email": escape_str(resume.personal.email),
            "phone": escape_str(resume.personal.phone),
            "linkedin": resume.personal.linkedin,  # URLs não precisam de escaping em \href
            "github": resume.personal.github,
            "portfolio": resume.personal.portfolio,
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
                "url": proj.url,
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
                "url": cert.url,
            }
            for cert in resume.certifications
        ],
    }


def compile_pdf(tex_path: Path) -> Path | None:
    """Compila ``.tex`` para ``.pdf`` usando ``pdflatex``.

    Executa ``pdflatex`` duas vezes para resolver referências cruzadas
    e limpa os arquivos auxiliares (``.aux``, ``.log``, ``.out``) após
    a compilação bem-sucedida.

    Args:
        tex_path: Caminho para o arquivo ``.tex`` a ser compilado.

    Returns:
        Caminho para o ``.pdf`` gerado, ou ``None`` se ``pdflatex``
        não estiver disponível ou a compilação falhar.
    """
    if not shutil.which("pdflatex"):
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
            timeout=60,
            check=True,
        )
        # Segunda execução para resolver referências cruzadas
        subprocess.run(
            pdflatex_cmd,
            capture_output=True,
            timeout=60,
            check=True,
        )

        pdf_path = tex_path.with_suffix(".pdf")
        if pdf_path.exists():
            # Limpa arquivos auxiliares
            for ext in (".aux", ".log", ".out"):
                aux_file = tex_path.with_suffix(ext)
                if aux_file.exists():
                    aux_file.unlink()
            return pdf_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    return None

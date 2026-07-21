"""Interface de Linha de Comando (CLI) para o ResumeForge."""

import os
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import DEFAULT_RESUME_PATH, DATA_DIR, OUTPUT_DIR
from .models import ResumeData, MatchResult, JobPosting
from .resume_parser import parse_resume
from .scraper import scrape_job, read_job_from_file
from .analyzer import parse_job_posting, analyze_match, generate_tailored_resume, generate_cover_letter
from .generator import generate_latex, compile_pdf

console = Console()

@click.group()
def cli():
    """ResumeForge: Automação de Currículo Adaptativo por Vaga."""
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)


def _load_resume(resume_path: Path) -> tuple[str, ResumeData | None]:
    """Carrega o currículo base."""
    if not resume_path.exists():
        console.print(f"[red]Erro:[/red] Currículo base não encontrado em {resume_path}")
        console.print(f"Coloque seu currículo nesta pasta ou use --resume para especificar outro arquivo.")
        sys.exit(1)
        
    try:
        return parse_resume(resume_path)
    except Exception as e:
        console.print(f"[red]Erro ao parsear currículo:[/red] {e}")
        sys.exit(1)


def _get_job_text(url: str, paste: bool) -> str:
    """Obtém o texto da vaga."""
    if paste:
        console.print("[cyan]Cole o texto da vaga abaixo e digite 'FIM' em uma linha vazia para encerrar:[/cyan]")
        lines = []
        try:
            while True:
                line = input()
                if line.strip().upper() == "FIM":
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        return '\n'.join(lines)
    elif url:
        if os.path.exists(url):
            return read_job_from_file(url)
        else:
            with console.status(f"[bold green]Extraindo vaga de {url}...") as status:
                return scrape_job(url)
    else:
        console.print("[red]Erro:[/red] Você deve fornecer uma URL/arquivo ou usar --paste.")
        sys.exit(1)


def _display_match_result(match: MatchResult, job: JobPosting):
    """Exibe o resultado do match no terminal de forma rica."""
    color = "green" if match.score >= 70 else "yellow" if match.score >= 40 else "red"
    
    table = Table(show_header=False, box=None)
    table.add_column("Propriedade", style="bold cyan")
    table.add_column("Valor")
    
    # Proteção caso campos venham nulos da IA
    vaga_titulo = job.title if job.title else "Não Identificado"
    vaga_empresa = job.company if job.company else "Empresa Oculta"
    
    table.add_row("Vaga", f"{vaga_titulo} na {vaga_empresa}")
    table.add_row("Score", f"[{color}]{match.score}/100 ({match.verdict})[/{color}]")
    
    console.print(Panel(table, title="Resultado da Análise", border_style="cyan"))
    
    if match.matching_skills:
        console.print("\n[bold green]✅ Habilidades Encontradas (Palavras-chave ATS):[/bold green]")
        for skill in match.matching_skills:
            console.print(f"  - {skill}")
            
    if match.missing_skills:
        console.print("\n[bold red]❌ Gaps Identificados (Requisitos não explícitos):[/bold red]")
        for skill in match.missing_skills:
            console.print(f"  - {skill}")
            
    if match.transferable_skills:
        console.print("\n[bold yellow]🔄 Competências Transversais/Aproveitáveis:[/bold yellow]")
        for skill in match.transferable_skills:
            console.print(f"  - {skill}")
            
    if match.suggestions:
        console.print("\n[bold blue]💡 Sugestões de Ajuste Tático:[/bold blue]")
        for sug in match.suggestions:
            console.print(f"  - {sug}")


@cli.command()
@click.argument('url', required=False)
@click.option('--paste', is_flag=True, help='Colar texto da vaga diretamente')
@click.option('--resume', type=click.Path(path_type=Path), default=DEFAULT_RESUME_PATH, help='Caminho para o currículo base')
def match(url: str, paste: bool, resume: Path):
    """Analisa compatibilidade entre currículo e vaga (não gera PDF)."""
    raw_resume, resume_data = _load_resume(resume)
    raw_job = _get_job_text(url, paste)
    
    with console.status("[bold green]Analisando vaga com IA..."):
        job = parse_job_posting(raw_job)
        
    with console.status("[bold green]Calculando compatibilidade..."):
        result = analyze_match(raw_resume, job, resume_data)
        
    _display_match_result(result, job)


@cli.command()
@click.argument('url', required=False)
@click.option('--paste', is_flag=True, help='Colar texto da vaga diretamente')
@click.option('--resume', type=click.Path(path_type=Path), default=DEFAULT_RESUME_PATH, help='Caminho para o currículo base')
@click.option('--force', is_flag=True, help='Forçar geração do currículo mesmo com score baixo')
def tailor(url: str, paste: bool, resume: Path, force: bool):
    """Analisa compatibilidade E gera um currículo adaptado para a vaga."""
    raw_resume, resume_data = _load_resume(resume)
    raw_job = _get_job_text(url, paste)
    
    with console.status("[bold green]Analisando vaga com IA..."):
        job = parse_job_posting(raw_job)
        
    with console.status("[bold green]Calculando compatibilidade..."):
        result = analyze_match(raw_resume, job, resume_data)
        
    _display_match_result(result, job)
    
    if result.score < 40 and not force:
        console.print("\n[bold red]⚠️ Score baixo (<40). O currículo não será gerado automaticamente para esta vaga.[/bold red]")
        console.print("Use a flag [cyan]--force[/cyan] se quiser forçar a reescrita do documento.")
        return
        
    with console.status("[bold green]Otimizando currículo e injetando termos ATS..."):
        tailored_data = generate_tailored_resume(raw_resume, job, result, resume_data)
        
    with console.status("[bold green]Redigindo Carta de Apresentação direcionada..."):
        letter_text = generate_cover_letter(raw_resume, job, result)

    with console.status("[bold green]Compilando estruturas LaTeX e gerando PDF..."):
        # Garante string válida para o nome do arquivo mesmo se a IA retornar campos vazios
        company_clean = job.company if job.company else "empresa_vaga"
        company_slug = "".join(c for c in company_clean if c.isalnum()).lower()
        output_name = f"cv_{company_slug}"
        
        tex_path = generate_latex(tailored_data, output_name)
        pdf_path = compile_pdf(tex_path)
        
        # Salva a carta de apresentação gerada
        letter_path = OUTPUT_DIR / f"carta_{company_slug}.txt"
        letter_path.write_text(letter_text, encoding="utf-8")
        
    console.print(f"\n[bold green]✅ Operação concluída com sucesso![/bold green]")
    console.print(f"Código LaTeX estruturado em: [cyan]{tex_path}[/cyan]")
    
    if pdf_path:
        console.print(f"Currículo em PDF disponível em: [cyan]{pdf_path}[/cyan]")
    else:
        console.print("[yellow]Aviso:[/yellow] O arquivo LaTeX foi criado, mas o pdflatex falhou ou não está instalado no PATH para compilar o PDF.")
        
    console.print(f"Carta de Apresentação salva em: [cyan]{letter_path}[/cyan]")


@cli.command()
@click.option('--resume', type=click.Path(path_type=Path), default=DEFAULT_RESUME_PATH, help='Caminho para o currículo base')
def build(resume: Path):
    """Gera PDF do currículo base (sem adaptação para vaga)."""
    raw_resume, resume_data = _load_resume(resume)
    
    if not resume_data:
        console.print("[red]Erro:[/red] Para fazer build do currículo base, ele precisa estar em formato YAML estruturado.")
        sys.exit(1)
        
    with console.status("[bold green]Compilando LaTeX e gerando PDF..."):
        tex_path = generate_latex(resume_data, "resume_base")
        pdf_path = compile_pdf(tex_path)
        
    console.print(f"\n[bold green]✅ Build finalizado![/bold green]")
    console.print(f"Código LaTeX gerado em: [cyan]{tex_path}[/cyan]")
    if pdf_path:
        console.print(f"PDF gerado em: [cyan]{pdf_path}[/cyan]")


if __name__ == '__main__':
    cli()
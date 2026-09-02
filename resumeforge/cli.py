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
from .analyzer import parse_job_posting, analyze_match, generate_tailored_resume
from .word_generator import generate_word

console = Console()

@click.group()
def cli():
    """ResumeForge: Automação de Currículo Adaptativo por Vaga."""
    # Garante que os diretórios existem
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
        console.print("[cyan]Cole o texto da vaga abaixo (pressione Ctrl+D quando terminar):[/cyan]")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
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
    
    table.add_row("Vaga", f"{job.title} na {job.company}")
    table.add_row("Score", f"[{color}]{match.score}/100 ({match.verdict})[/{color}]")
    
    console.print(Panel(table, title="Resultado da Análise", border_style="cyan"))
    
    if match.matching_skills:
        console.print("\n[bold green]✅ Skills Compatíveis:[/bold green]")
        for skill in match.matching_skills:
            console.print(f"  - {skill}")
            
    if match.missing_skills:
        console.print("\n[bold red]❌ Skills Faltantes:[/bold red]")
        for skill in match.missing_skills:
            console.print(f"  - {skill}")
            
    if match.transferable_skills:
        console.print("\n[bold yellow]🔄 Skills Transferíveis:[/bold yellow]")
        for skill in match.transferable_skills:
            console.print(f"  - {skill}")
            
    if match.suggestions:
        console.print("\n[bold blue]💡 Sugestões de Melhoria:[/bold blue]")
        for sug in match.suggestions:
            console.print(f"  - {sug}")


@cli.command()
@click.argument('url', required=False)
@click.option('--paste', is_flag=True, help='Colar texto da vaga diretamente')
@click.option('--resume', type=click.Path(path_type=Path), default=DEFAULT_RESUME_PATH, help='Caminho para o currículo base')
def match(url: str, paste: bool, resume: Path):
    """Analisa compatibilidade entre currículo e vaga (sem gerar documento)."""
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
        console.print("\n[bold red]⚠️ Score baixo (<40). O currículo não será gerado.[/bold red]")
        console.print("Use a flag [cyan]--force[/cyan] se quiser gerar mesmo assim.")
        return
        
    with console.status("[bold green]Gerando currículo adaptado com IA..."):
        tailored_data = generate_tailored_resume(raw_resume, job, result, resume_data)
        
    with console.status("[bold green]Gerando currículo em Word (.docx)..."):
        company_slug = "".join(c for c in job.company if c.isalnum()).lower()
        output_name = f"cv_{company_slug}"
        
        word_path = generate_word(tailored_data, output_name)
        
    console.print(f"\n[bold green]✅ Sucesso![/bold green]")
    console.print(f"Currículo gerado em: [cyan]{word_path}[/cyan]")


@cli.command()
@click.option('--resume', type=click.Path(path_type=Path), default=DEFAULT_RESUME_PATH, help='Caminho para o currículo base')
def build(resume: Path):
    """Gera currículo base em Word (.docx) sem adaptação para vaga."""
    raw_resume, resume_data = _load_resume(resume)
    
    if not resume_data:
        console.print("[red]Erro:[/red] Para fazer build do currículo base, ele precisa estar em formato YAML estruturado.")
        sys.exit(1)
        
    with console.status("[bold green]Gerando currículo em Word (.docx)..."):
        word_path = generate_word(resume_data, "resume_base")
        
    console.print(f"\n[bold green]✅ Sucesso![/bold green]")
    console.print(f"Currículo gerado em: [cyan]{word_path}[/cyan]")


if __name__ == '__main__':
    cli()

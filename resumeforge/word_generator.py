"""Gerador de currículo Word (.docx) a partir de dados estruturados e otimizado para ATS."""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .config import OUTPUT_DIR
from .models import ResumeData


def _add_bottom_border(paragraph):
    """Adiciona uma linha divisória horizontal real abaixo do parágrafo via XML do Word."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')  # Espessura da linha
    bottom.set(qn('w:space'), '4')
    bottom.set(qn('w:color'), 'auto')
    pBdr.append(bottom)
    pPr.append(pBdr)


def _format_heading(doc, text, level=1):
    """Cria um título tratado, limpando o estilo padrão do Word e aplicando Arial."""
    # Criamos o heading sem texto para não herdar os runs padrão do Word
    heading = doc.add_heading(level=level)
    heading.paragraph_format.space_before = Pt(12)
    heading.paragraph_format.space_after = Pt(4)
    heading.paragraph_format.keep_with_next = True 
    
    # Adicionamos o texto manualmente em um run controlado por nós
    run = heading.add_run(text)
    run.font.name = 'Arial'
    run.font.bold = True
    run.font.color.rgb = None  # Mantém a cor automática preta/cinza escuro
    run.font.size = Pt(12.5) if level == 1 else Pt(11)
    
    return heading

def generate_word(resume: ResumeData, output_name: str = "resume_tailored") -> Path:
    """Gera um arquivo .docx altamente escaneável e compacto para triagens ATS."""
    doc = Document()
    
    # Configurações de estilo base (Normal)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(10.5)  # Tamanho ideal para densidade de informações
    
    # Margens estreitas (0.5 polegadas) para garantir o aproveitamento de espaço
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

    # ── Cabeçalho (Header) ──────────────────────────────────────────────
    name_para = doc.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_para.paragraph_format.space_after = Pt(2)
    
    name_run = name_para.add_run(resume.personal.name)
    name_run.bold = True
    name_run.font.size = Pt(18)

    contact_details = []
    if resume.personal.phone: contact_details.append(resume.personal.phone)
    if resume.personal.email: contact_details.append(resume.personal.email)
    if resume.personal.location: contact_details.append(resume.personal.location)
    if resume.personal.linkedin: contact_details.append(resume.personal.linkedin)
    if resume.personal.github: contact_details.append(resume.personal.github)
    
    if contact_details:
        contact_para = doc.add_paragraph(" | ".join(contact_details))
        contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        contact_para.paragraph_format.space_after = Pt(6)
        _add_bottom_border(contact_para)  # Linha divisória elegante e segura

    # ── Resumo Profissional ─────────────────────────────────────────────
    if resume.summary:
        _format_heading(doc, "Resumo Profissional", level=1)
        p = doc.add_paragraph(resume.summary)
        p.paragraph_format.space_after = Pt(6)

    # ── Experiência Profissional ───────────────────────────────────────
    if resume.experience:
        _format_heading(doc, "Experiência Profissional", level=1)
        for exp in resume.experience:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            
            p.add_run(f"{exp.role}").bold = True
            p.add_run(f" | {exp.company}")
            if exp.location:
                p.add_run(f" - {exp.location}")
            
            # Adiciona o período na mesma linha ou logo abaixo de forma compacta
            p.add_run(f" ({exp.period})").italic = True
            
            for hl in exp.highlights:
                bullet = doc.add_paragraph(hl, style='List Bullet')
                bullet.paragraph_format.space_after = Pt(2)  # Mantém os tópicos colados

    # ── Habilidades Técnicas ───────────────────────────────────────────
    if resume.skills:
        _format_heading(doc, "Habilidades Técnicas", level=1)
        for sc in resume.skills:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            p.add_run(f"{sc.category}: ").bold = True
            p.add_run(", ".join(sc.items))

    # ── Projetos Relevantes ─────────────────────────────────────────────
    if resume.projects:
        _format_heading(doc, "Projetos", level=1)
        for proj in resume.projects:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            
            p.add_run(f"{proj.name}").bold = True
            if proj.technologies:
                p.add_run(f" | {', '.join(proj.technologies)}")
            if proj.url:
                p.add_run(f" ({proj.url})")
            
            desc_bullet = doc.add_paragraph(proj.description, style='List Bullet')
            desc_bullet.paragraph_format.space_after = Pt(3)

    # ── Formação Acadêmica ────────────────────────────────────────────────────────
    if resume.education:
        _format_heading(doc, "Formação Acadêmica", level=1)
        for edu in resume.education:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            
            p.add_run(f"{edu.institution}").bold = True
            p.add_run(f" | {edu.degree}")
            p.add_run(f" ({edu.period})").italic = True
            
            for detail in edu.details:
                detail_bullet = doc.add_paragraph(detail, style='List Bullet')
                detail_bullet.paragraph_format.space_after = Pt(2)

    # ── Certificações ───────────────────────────────────────────────────
    if resume.certifications:
        _format_heading(doc, "Certificações", level=1)
        for cert in resume.certifications:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.add_run(f"{cert.name}").bold = True
            if cert.issuer:
                p.add_run(f" - {cert.issuer}")
            if cert.date:
                p.add_run(f" ({cert.date})")

    # ── Idiomas ─────────────────────────────────────────────────────────
    if resume.languages:
        _format_heading(doc, "Idiomas", level=1)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        langs = [f"{lang.name} ({lang.level})" for lang in resume.languages]
        p.add_run(" | ".join(langs))

    # Salva o arquivo final
    output_path = OUTPUT_DIR / f"{output_name}.docx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    
    return output_path
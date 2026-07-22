"""
Gerador de currículo Word (.docx) a partir de dados estruturados e otimizado para ATS.
Totalmente compatível com os esquemas Pydantic e espelhado ao padrão LaTeX/PDF.
"""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Inches, RGBColor
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
    bottom.set(qn('w:color'), '333333')  # Cinza escuro elegante
    pBdr.append(bottom)
    pPr.append(pBdr)


def _format_heading(doc, text, level=1):
    """Cria um título tratado com fonte Arial e borda inferior elegante."""
    heading = doc.add_heading(level=level)
    heading.paragraph_format.space_before = Pt(12)
    heading.paragraph_format.space_after = Pt(4)
    heading.paragraph_format.keep_with_next = True 
    
    run = heading.add_run(text.upper() if level == 1 else text)
    run.font.name = 'Arial'
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
    run.font.size = Pt(11) if level == 1 else Pt(10)
    
    if level == 1:
        _add_bottom_border(heading)
        
    return heading


def generate_word(resume: ResumeData, output_name: str = "resume_tailored") -> Path:
    """Gera um arquivo .docx altamente escaneável e compacto para triagens ATS."""
    doc = Document()
    
    # Style base Normal
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(10)
    
    # Margens executivas (0.6 pol)
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.7)
        section.right_margin = Inches(0.7)

    # ── 1. Cabeçalho (Contatos) ──────────────────────────────────────────
    if hasattr(resume, 'contact') and resume.contact:
        name_para = doc.add_paragraph()
        name_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        name_para.paragraph_format.space_after = Pt(2)
        
        name_run = name_para.add_run(resume.contact.name)
        name_run.bold = True
        name_run.font.size = Pt(18)
        name_run.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

        contact_details = []
        if resume.contact.email: contact_details.append(resume.contact.email)
        if resume.contact.phone: contact_details.append(resume.contact.phone)
        if resume.contact.location: contact_details.append(resume.contact.location)
        if resume.contact.linkedin: contact_details.append(resume.contact.linkedin)
        if resume.contact.github: contact_details.append(resume.contact.github)
        
        if contact_details:
            contact_para = doc.add_paragraph("  |  ".join(contact_details))
            contact_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            contact_para.paragraph_format.space_after = Pt(8)
            contact_para.runs[0].font.size = Pt(9)
            contact_para.runs[0].font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    # ── 2. Resumo Profissional / Objetivo ──────────────────────────────
    if resume.summary:
        _format_heading(doc, "Objetivo Profissional", level=1)
        p = doc.add_paragraph(resume.summary)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15

    # ── 3. Formação Acadêmica ─────────────────────────────────────────
    if resume.education:
        _format_heading(doc, "Formação Acadêmica", level=1)
        for edu in resume.education:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(2)
            
            # Formatação Básica: Grau - Instituição
            run_edu = p.add_run(f"{edu.degree} – {edu.institution}")
            run_edu.bold = True
            
            # Só adiciona o período SE ele existir no currículo original
            period_text = getattr(edu, 'period', None)
            status_text = getattr(edu, 'status', None)
            
            info_extra = []
            if period_text: info_extra.append(f"Período: {period_text}")
            if status_text: info_extra.append(f"({status_text})")
            
            if info_extra:
                run_det = p.add_run(f" | {' '.join(info_extra)}")
                run_det.italic = True
                run_det.font.size = Pt(9.5)
                run_det.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # ── 4. Conhecimentos / Habilidades Técnicas ────────────────────────
    skills_list = getattr(resume, 'technical_skills', None) or getattr(resume, 'skills', None)
    if skills_list:
        _format_heading(doc, "Conhecimentos Técnicos", level=1)
        for sc in skills_list:
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.15
            
            category_text = getattr(sc, 'category', '')
            items_list = getattr(sc, 'items', [])
            items_str = ", ".join(items_list) if isinstance(items_list, list) else str(items_list)
            
            if category_text:
                run_cat = p.add_run(f"{category_text}: ")
                run_cat.bold = True
            
            p.add_run(items_str)

    # ── 5. Projetos de Portfólio (Experiência Prática) ───────────
    if resume.projects:
        _format_heading(doc, "Projetos de Portfólio (Experiência Prática)", level=1)
        for proj in resume.projects:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            
            # Título do Projeto
            proj_title = getattr(proj, 'title', None) or getattr(proj, 'name', 'Projeto')
            run_title = p.add_run(proj_title)
            run_title.bold = True
            
            # Tecnologias (se houver)
            techs = getattr(proj, 'technologies', None)
            if techs:
                techs_str = ", ".join(techs) if isinstance(techs, list) else str(techs)
                run_tech = p.add_run(f" | {techs_str}")
                run_tech.font.size = Pt(9.5)
                run_tech.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            
            # Período do projeto (SÓ se existir no original)
            proj_period = getattr(proj, 'period', None) or getattr(proj, 'date', None)
            if proj_period:
                run_date = p.add_run(f" ({proj_period})")
                run_date.italic = True
                run_date.font.size = Pt(9)
            
            # Tópicos / Descrição
            highlights = getattr(proj, 'highlights', None)
            description = getattr(proj, 'description', None)
            
            bullets = highlights if highlights else ([description] if description else [])
            for hl in bullets:
                bullet = doc.add_paragraph(hl, style='List Bullet')
                bullet.paragraph_format.space_before = Pt(0)
                bullet.paragraph_format.space_after = Pt(2)
                bullet.paragraph_format.line_spacing = 1.15

    # ── 6. Experiência Profissional (Tradicional) ──────────────────────
    if getattr(resume, 'experience', None):
        _format_heading(doc, "Experiência Profissional", level=1)
        for exp in resume.experience:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            
            role_text = getattr(exp, 'title', None) or getattr(exp, 'role', 'Cargo')
            p.add_run(f"{role_text}").bold = True
            
            if hasattr(exp, 'company') and exp.company:
                p.add_run(f" – {exp.company}")
            
            # Só coloca o período se estiver definido
            exp_period = getattr(exp, 'period', None)
            if exp_period:
                run_per = p.add_run(f" ({exp_period})")
                run_per.italic = True
                run_per.font.size = Pt(9)
            
            highlights = getattr(exp, 'highlights', [])
            for hl in highlights:
                bullet = doc.add_paragraph(hl, style='List Bullet')
                bullet.paragraph_format.space_before = Pt(0)
                bullet.paragraph_format.space_after = Pt(2)

    # ── 7. Certificações ───────────────────────────────────────────────
    if resume.certifications:
        _format_heading(doc, "Certificações", level=1)
        for cert in resume.certifications:
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            
            if isinstance(cert, str):
                p.add_run(cert)
            else:
                cert_name = getattr(cert, 'name', str(cert))
                p.add_run(cert_name).bold = True
                issuer = getattr(cert, 'issuer', None)
                if issuer:
                    p.add_run(f" - {issuer}")
                date = getattr(cert, 'date', None)
                if date:
                    p.add_run(f" ({date})")

    # ── 8. Idiomas ─────────────────────────────────────────────────────
    if getattr(resume, 'languages', None):
        _format_heading(doc, "Idiomas", level=1)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        langs = []
        for lang in resume.languages:
            if isinstance(lang, str):
                langs.append(lang)
            else:
                langs.append(f"{lang.name} ({lang.level})")
        p.add_run("  |  ".join(langs))

    # Salva o arquivo final
    output_path = OUTPUT_DIR / f"{output_name}.docx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    
    return output_path
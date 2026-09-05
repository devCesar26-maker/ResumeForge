"""Backend da Aplicação Web ResumeForge (Flask)."""

import gc
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from pydantic import ValidationError

from resumeforge.config import DATA_DIR, OUTPUT_DIR
from resumeforge.models import JobPosting, MatchResult
from resumeforge.resume_parser import parse_resume
from resumeforge.scraper import scrape_job, clean_job_text_content
from resumeforge.analyzer import parse_job_posting, analyze_match, generate_tailored_resume, generate_cover_letter
from resumeforge.word_generator import generate_word

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = DATA_DIR / 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload

# Garante que as pastas existem
app.config['UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def check_api_key():
    from resumeforge.config import GEMINI_API_KEY
    return bool(GEMINI_API_KEY)


@app.route('/')
def index():
    has_key = check_api_key()
    return render_template('index.html', has_key=has_key)


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL não informada'}), 400
    try:
        extracted_text = scrape_job(url)
        return jsonify({'text': extracted_text})
    except Exception as e:
        print(f"\n[Erro Scrape]: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if 'resume' not in request.files:
        return jsonify({'error': 'Nenhum currículo enviado.'}), 400
        
    file = request.files['resume']
    raw_job_text = request.form.get('job_text', '')
    
    if file.filename == '':
        return jsonify({'error': 'Arquivo vazio.'}), 400
    if not raw_job_text:
        return jsonify({'error': 'Texto da vaga não informado.'}), 400
        
    try:
        filename = secure_filename(file.filename)
        timestamp = int(time.time())
        safe_filename = f"{timestamp}_{filename}"
        resume_path = app.config['UPLOAD_FOLDER'] / safe_filename
        file.save(resume_path)
        
        # 1. Parse Resume
        try:
            raw_resume, resume_data = parse_resume(resume_path)
        except Exception as e:
            print(f"[Erro Parse Resume]: {e}")
            return jsonify({'error': f'Falha ao processar o arquivo de currículo: {str(e)}'}), 422
        
        # 2. Clean & Parse Job
        try:
            job_text = clean_job_text_content(raw_job_text)
            job = parse_job_posting(job_text)
        except ValidationError as ve:
            print(f"[Erro Validação Job]: {ve}")
            return jsonify({'error': 'Não foi possível estruturar os dados da vaga de emprego fornecida.'}), 422
        except Exception as e:
            print(f"[Erro Parse Job]: {e}")
            return jsonify({'error': f'Falha ao analisar o texto da vaga: {str(e)}'}), 500
        
        # 3. Match via Gemini
        try:
            match = analyze_match(raw_resume, job, resume_data)
        except ValidationError as ve:
            print(f"[Erro Validação Match]: {ve}")
            return jsonify({'error': 'Erro de validação nos dados de compatibilidade gerados pela IA.'}), 502
        except Exception as e:
            print(f"[Erro Analyze Match]: {e}")
            return jsonify({'error': f'Falha na análise de compatibilidade (Gemini): {str(e)}'}), 502
        
        # Monta a resposta ANTES de liberar a memória
        response = jsonify({
            'success': True,
            'job': {
                'title': job.title,
                'company': job.company
            },
            'match': match.model_dump(), # Evita esquecer campos novos (strengths, weaknesses, etc.)
            'session_data': {
                'resume_path': str(resume_path),
                'job_text': job_text,
                # Reenvia job + match já calculados para o /api/generate NÃO
                # precisar reanalisar a vaga nem refazer o analyze_match no Gemini
                'job': job.model_dump(exclude={'raw_text'}),
                'match': match.model_dump(exclude={'tailored_resume'}),
            }
        })
        
        # Libera objetos pesados da memória
        del raw_resume, resume_data, job, match
        gc.collect()
        
        return response
        
    except Exception as e:
        # Print detalhado no terminal para debugar em tempo real caso ocorra um erro imprevisto
        print("\n" + "="*50)
        print(f"ERRO CRÍTICO INESPERADO NA ROTA /api/analyze: {e}")
        print("="*50 + "\n")
        return jsonify({'error': f'Erro interno no servidor: {str(e)}'}), 500


def _session_job_match(data: dict, raw_resume: str, resume_data, job_text: str):
    """Reconstrói job + match a partir da sessão; recalcula se ausentes."""
    if data.get('job') and data.get('match'):
        return JobPosting(**data['job']), MatchResult(**data['match'])
    job = parse_job_posting(job_text)
    match = analyze_match(raw_resume, job, resume_data)
    return job, match


@app.route('/api/generate-resume', methods=['POST'])
def api_generate_resume():
    """Gera apenas o currículo adaptado (.docx)."""
    data = request.json
    resume_path = Path(data.get('resume_path', ''))
    job_text = data.get('job_text', '')
    
    if not resume_path.exists() or not job_text:
        return jsonify({'error': 'Dados da sessão inválidos.'}), 400
        
    try:
        raw_resume, resume_data = parse_resume(resume_path)
        job, match = _session_job_match(data, raw_resume, resume_data, job_text)
        
        tailored_data = generate_tailored_resume(raw_resume, job, match, resume_data)
        
        company_slug = "".join(c for c in job.company if c.isalnum()).lower()
        word_path = generate_word(tailored_data, f"cv_{company_slug}")
        
        response = jsonify({
            'success': True,
            'files': {
                'word': f'/download/{word_path.name}',
            }
        })
        
        del raw_resume, resume_data, job, match, tailored_data
        gc.collect()
        return response
        
    except Exception as e:
        print(f"\n[Erro Geração de Currículo]: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate-cover-letter', methods=['POST'])
def api_generate_cover_letter():
    """Gera apenas a carta de apresentação."""
    data = request.json
    resume_path = Path(data.get('resume_path', ''))
    job_text = data.get('job_text', '')
    
    if not resume_path.exists() or not job_text:
        return jsonify({'error': 'Dados da sessão inválidos.'}), 400
        
    try:
        raw_resume, resume_data = parse_resume(resume_path)
        job, match = _session_job_match(data, raw_resume, resume_data, job_text)
        
        cover_letter = generate_cover_letter(raw_resume, job, match)
        
        # Rede de segurança: nunca devolver carta em branco sem feedback.
        # generate_cover_letter já lança erro se o Gemini retornar vazio/None,
        # mas este guard duplo garante erro explícito mesmo em caso de regressão.
        if not cover_letter or not cover_letter.strip():
            # TODO-DEBUG: remover após confirmar estabilidade (guard vazio/None)
            print("\n[ERRO Carta] generate_cover_letter retornou texto vazio — retornando erro explícito")
            return jsonify({'error': 'Falha ao gerar a carta de apresentação, tente novamente.'}), 502
        
        response = jsonify({'success': True, 'cover_letter': cover_letter})
        
        del raw_resume, resume_data, job, match, cover_letter
        gc.collect()
        return response
        
    except Exception as e:
        print(f"\n[Erro Geração de Carta]: {e}")
        # Mensagem amigável pro usuário; o erro real fica no log do servidor
        return jsonify({'error': 'Falha ao gerar a carta de apresentação, tente novamente.'}), 502


@app.route('/healthz')
def healthz():
    """Endpoint leve para health-check / keep-alive (ex.: cron-job.org)."""
    return jsonify({'status': 'ok'}), 200


@app.route('/download/<filename>')
def download_file(filename):
    secure_name = secure_filename(filename)
    path = OUTPUT_DIR / secure_name
    if path.exists():
        return send_file(path, as_attachment=True)
    return "File not found", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=True)

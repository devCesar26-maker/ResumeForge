"""Backend da Aplicação Web ResumeForge (Flask)."""

import os
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from pydantic import ValidationError
from google.genai.errors import APIError

from resumeforge.config import (
    DATA_DIR, 
    OUTPUT_DIR, 
    UPLOAD_FOLDER, 
    HOST, 
    PORT, 
    DEBUG, 
    MAX_CONTENT_LENGTH, 
    GEMINI_API_KEYS
)
from resumeforge.resume_parser import parse_resume
from resumeforge.scraper import scrape_job
from resumeforge.analyzer import (
    parse_job_posting, 
    analyze_match, 
    generate_tailored_resume, 
    generate_cover_letter
)
from resumeforge.generator import generate_latex, compile_pdf
from resumeforge.word_generator import generate_word

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Garante rigorosamente que as pastas temporárias existam na inicialização
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def check_api_key():
    """Verifica se existe pelo menos uma chave válida na lista de rotação do Gemini."""
    return bool(GEMINI_API_KEYS)


@app.route('/')
def index():
    has_key = check_api_key()
    return render_template('index.html', has_key=has_key)


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    data = request.json or {}
    url = data.get('url')
    if not url:
        return jsonify({'error': 'URL da vaga não informada.'}), 400
    try:
        extracted_text = scrape_job(url)
        return jsonify({'text': extracted_text})
    except Exception as e:
        print(f"\n[Erro Scrape]: {e}")
        return jsonify({'error': 'Não foi possível extrair automaticamente o texto desta página. Por favor, cole a descrição da vaga manualmente.'}), 500


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if 'resume' not in request.files:
        return jsonify({'error': 'Nenhum arquivo de currículo foi enviado.'}), 400
        
    file = request.files['resume']
    job_text = request.form.get('job_text', '')
    
    if file.filename == '':
        return jsonify({'error': 'O arquivo do currículo enviado está vazio.'}), 400
    if not job_text:
        return jsonify({'error': 'O texto da vaga não foi informado.'}), 400
        
    try:
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        
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
            return jsonify({'error': 'Não foi possível ler o arquivo do currículo. Certifique-se de enviar um PDF ou DOCX válido.'}), 422
        
        # 2. Parse Job
        try:
            job = parse_job_posting(job_text)
        except ValidationError as ve:
            print(f"[Erro Validação Job]: {ve}")
            return jsonify({'error': 'Não foi possível identificar os requisitos da vaga. Tente colar um texto mais completo.'}), 422
        except Exception as e:
            print(f"[Erro Parse Job]: {e}")
            return jsonify({'error': 'Ocorreu um erro ao processar a descrição da vaga.'}), 500
        
        # 3. Match via Gemini
        try:
            match = analyze_match(raw_resume, job, resume_data)
        except APIError as e:
            print(f"[Erro API Gemini no Match]: {e}")
            return jsonify({'error': 'O serviço de Inteligência Artificial está temporariamente indisponível ou com alta demanda. Por favor, aguarde cerca de 30 segundos e tente novamente.'}), 503
        except ValidationError as ve:
            print(f"[Erro Validação Match]: {ve}")
            return jsonify({'error': 'Houve uma inconsistência no processamento dos dados. Por favor, tente novamente.'}), 502
        except Exception as e:
            print(f"[Erro Analyze Match]: {e}")
            return jsonify({'error': 'Ocorreu uma falha durante a análise de compatibilidade. Por favor, tente novamente em instantes.'}), 503
        
        return jsonify({
            'success': True,
            'job': {
                'title': job.title,
                'company': job.company
            },
            'match': match.model_dump(),
            'session_data': {
                'resume_path': str(resume_path),
                'job_text': job_text
            }
        })
        
    except Exception as e:
        print("\n" + "="*50)
        print(f"ERRO CRÍTICO INESPERADO NA ROTA /api/analyze: {e}")
        print("="*50 + "\n")
        return jsonify({'error': 'Desculpe, ocorreu um erro interno em nossos servidores. Por favor, tente novamente.'}), 500


@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json or {}
    resume_path = Path(data.get('resume_path', ''))
    job_text = data.get('job_text', '')
    
    if not resume_path.exists() or not job_text:
        return jsonify({
            'error': 'Sessão expirada ou arquivo temporário removido. Por favor, envie o currículo novamente.'
        }), 400
        
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Recupera o parse básico do currículo e da vaga
        raw_resume, resume_data = parse_resume(resume_path)
        job = parse_job_posting(job_text)
        
        # Recria o objeto de match sem reprocessar se necessário
        match = analyze_match(raw_resume, job, resume_data)
        
        # Gera carta de apresentação e currículo adaptado
        cover_letter = generate_cover_letter(raw_resume, job, match)
        tailored_data = generate_tailored_resume(raw_resume, job, match, resume_data)
        
        # Nome do arquivo de saída
        company_slug = "".join(c for c in job.company if c.isalnum()).lower()
        if not company_slug:
            company_slug = "vaga"
        output_name = f"cv_{company_slug}_{int(time.time())}"
        
        word_path = generate_word(tailored_data, output_name)
        tex_path = generate_latex(tailored_data, output_name)
        pdf_path = compile_pdf(tex_path)
        
        return jsonify({
            'success': True,
            'cover_letter': cover_letter,
            'files': {
                'word': f'/download/{word_path.name}',
                'tex': f'/download/{tex_path.name}',
                'pdf': f'/download/{pdf_path.name}' if pdf_path else None
            }
        })
        
    except APIError as e:
        print(f"\n[Erro API Gemini na Geração]: {e}")
        return jsonify({'error': 'A IA demorou a responder ou o limite de requisições foi atingido. Aguarde alguns segundos e clique em gerar novamente.'}), 503
    except Exception as e:
        print(f"\n[Erro Geração de Documentos]: {e}")
        return jsonify({'error': 'Não foi possível gerar os documentos personalizados no momento. Por favor, tente novamente.'}), 500


@app.route('/download/<filename>')
def download_file(filename):
    secure_name = secure_filename(filename)
    path = OUTPUT_DIR / secure_name
    if path.exists():
        return send_file(path, as_attachment=True)
    return "Arquivo não encontrado ou link expirado. Por favor, gere o documento novamente.", 404


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'uptime': 'available',
    }), 200


if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=DEBUG)
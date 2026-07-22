# ResumeForge
**Acesse a aplicação ao vivo:** [https://resumeforge-jg6l.onrender.com/](https://resumeforge-jg6l.onrender.com/)
ResumeForge é uma plataforma full-stack em Python desenvolvida para automatizar a análise de aderência a vagas de emprego e realizar a engenharia reversa e otimização de currículos utilizando Inteligência Artificial.

A aplicação processa o currículo mestre do usuário, extrai os requisitos fundamentais de uma vaga alvo e gera dinamicamente uma versão adaptada do documento focada em compatibilidade com sistemas ATS (Applicant Tracking Systems), clareza técnica e impacto profissional.

---

## 🚀 Funcionalidades Principais

* **Scraping Resiliente de Vagas:** Raspagem direta via `requests` + `BeautifulSoup` com cabeçalhos de navegador simulados e limpeza de HTML para obter descrições limpas de plataformas como LinkedIn.
* **Gestão Inteligente de Infraestrutura:** Tratamento local de falhas, retries e timeouts para mitigar bloqueios e erros temporários.
* **Inteligência Artificial Híbrida (Multi-LLM):** Engenharia de prompts distribuída estrategicamente entre múltiplos provedores. O ecossistema usa **Groq** devido à sua ultravelocidade para realizar o parse e estruturação de payloads de vagas de emprego, delegando ao **Google Gemini** o papel analítico rigoroso de calcular scores (ATS Match), mapear afinidades e reescrever estrategicamente os currículos.
* **Análise de Afinidade (ATS Match Score):** Diagnóstico profundo operado por IA de compatibilidade entre o histórico do candidato e as exigências do mercado, gerando pontuações de aderência e gráficos analíticos.
* **Mapeamento de Gaps e Equivalências:** Identificação de competências ausentes e sugestão automática de pontes de equivalência baseadas nas experiências do usuário.
* **Forja de Ativos de Candidatura:** Geração automatizada de currículos otimizados e pitches/cartas de apresentação personalizados para a vaga.
* **Interface Web Premium:** Painel responsivo em Dark Mode com feedback visual dinâmico em tempo real.

---

## 🛠️ Stack Tecnológica

* **Backend / Core:** Python 3, Flask
* **Validação de Dados:** Pydantic
* **Provedores de IA (LLMs):** Groq API (Velocidade no Parse) & Google Gemini API (Rigor Analítico e Ajuste)
* **Web Scraping Engine:** `requests` & `BeautifulSoup4` (raspagem direta HTTP; nenhum serviço externo de scraping é necessári)
* **Renderização de Interface:** Jinja2, Tailwind CSS, Alpine.js, Plotly
* **Motores de Documentos:** LaTeX, Python-docx

---

## 📂 Arquitetura do Projeto

* `app.py`: Servidor Flask e gerenciamento das rotas da API e da interface.
* `resumeforge/analyzer.py`: Pipeline analítico híbrido de parsing com a Groq, seguidos pelo cálculo de score e reescrita de ativos via Google Gemini.
* `resumeforge/generator.py`: Motor de compilação de arquivos LaTeX e exportação em PDF.
* `resumeforge/word_generator.py`: Motor de estruturação e formatação de documentos Word (`.docx`).
* `resumeforge/models.py`: Modelos de dados fortemente tipados para estruturação dos payloads da IA (`JobPosting`, `MatchResult`, `ResumeData`).
* `resumeforge/resume_parser.py`: Subsistema de leitura e extração de texto de currículos em múltiplos formatos.
* `resumeforge/scraper.py`: Engine de raspagem inteligente baseada em `requests` + `BeautifulSoup`, normalização de URLs do LinkedIn e limpeza de ruídos em HTML.
* `templates/`: Templates HTML da interface web e estruturas base de documentos.
* `static/`: Scripts interativos (`app.js`) e estilizações da aplicação.

## 📋 Formatos de Currículo Suportados

O parser integrado está preparado para extrair dados estruturados de arquivos:

* **Estruturados:** YAML (`.yaml`, `.yml`)
* **Documentos:** PDF (`.pdf`), Word (`.docx`)
* **Texto Puro:** TXT, Markdown (`.md`) e LaTeX (`.tex`)

---

## ⚙️ Instalação

### Instalação Local

1. Clone o repositório:
   ```bash
   git clone https://github.com/devCesar26-maker/ResumeForge
   cd BOT_VAGAS
   ```
2. Crie e ative o ambiente virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
4. Não é necessário instalar Playwright para o scraper: a aplicação realiza requisições HTTP diretas usando `requests` e processa o HTML com `BeautifulSoup`.

### Instalação com Docker

1. Certifique-se de ter Docker instalado.
2. Construa a imagem:
   ```bash
   docker build -t resumeforge .
   ```
3. Execute o container:
   ```bash
   docker run --rm -p 8501:8501  
   -e GEMINI_API_KEY=seu_token
   -e GROQ_API_KEY=seu_token
   # Note: No scraping service token is required; `requests` + `BeautifulSoup` are used.
   -e GEMINI_MODEL=nome_do_modelo
   -e GROQ_MODEL=nome_do_modelo
   -e DEBUG=false
   -e MAX_CONTENT_LENGTH=16777216
   resumeforge
   ```

## 🚀 Executando a Aplicação

Inicie o servidor Flask:

```bash
python app.py
```

Acesse a interface em `http://127.0.0.1:8501` no Chrome.

## 🔧 Configuração

Configure as variáveis de ambiente necessárias para os provedores de IA e scraping:

* `GEMINI_API_KEY`
* `GROQ_API_KEY`
* `GEMINI_MODEL`
* `GROQ_MODEL`
* `DEBUG`
* `MAX_CONTENT_LENGTH`

## 🧪 Fluxo de Uso

1. Faça upload do currículo mestre.
2. Informe a vaga alvo ou cole a URL do anúncio.
3. A aplicação extrai os requisitos da vaga, compara com o histórico e calcula o score de aderência.
4. Gere o currículo otimizado e baixe o PDF, DOCX ou TEX.

## 🤝 Contribuição

Bug reports, melhorias e pull requests são bem-vindos. Use issues para discutir mudanças antes de enviar contribuições.

## 📄 Licença

Este projeto está licenciado sob a licença Apache 2.0. Consulte o arquivo `LICENSE` para os termos completos.

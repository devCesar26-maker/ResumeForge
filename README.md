# 🎯 ResumeForge: IA para Currículos Adaptativos

O **ResumeForge** é uma aplicação web completa que utiliza Inteligência Artificial (Google Gemini) para comparar seu currículo base com uma vaga de emprego, apontar os pontos fortes e fracos, e gerar automaticamente um novo currículo personalizado (em PDF, Word e LaTeX), além de uma Carta de Apresentação.

## 🚀 Como Rodar o Projeto

Existem duas formas de rodar o projeto na sua máquina: a forma tradicional via Python, e a forma recomendada via Docker (muito mais profissional e simples).

### Opção 1: Via Docker (Recomendado ⭐)
Se você for apresentar o projeto em um evento, use esta opção. O Docker resolve todas as dependências de sistema (como os pacotes do LaTeX para gerar PDF e o Chromium para acessar vagas) sem instalar lixo na sua máquina.

1. Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Garanta que você preencheu o arquivo `.env` com sua `GEMINI_API_KEY`.
3. Abra o terminal na pasta do projeto e rode:
   ```bash
   docker-compose up --build
   ```
4. Acesse `http://localhost:8501` no seu navegador.

### Opção 2: Localmente (Ambiente Virtual Python)
Para desenvolvimento local:

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate  # No Windows: venv\Scripts\activate
   ```

2. Instale as dependências e o navegador do Playwright:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   playwright install-deps chromium
   ```

3. Instale o LaTeX na sua máquina (necessário para compilar os PDFs localmente):
   - **Linux:** `sudo apt install texlive-latex-base texlive-fonts-recommended texlive-latex-extra`
   - **Windows:** Instale o MiKTeX.
   - **Mac:** Instale o MacTeX.

4. Rode o servidor Flask:
   ```bash
   flask run --port=8501 --host=0.0.0.0
   ```
5. Acesse `http://localhost:8501` no seu navegador.

---

## 🛠️ Tecnologias Utilizadas
* **Backend:** Python 3.11, Flask, Pydantic, Playwright (Scraping)
* **Frontend:** Tailwind CSS, Alpine.js, Plotly.js
* **IA:** Google GenAI SDK (Gemini 3.5 Flash)
* **Geradores:** Jinja2 + LaTeX (PDFs lindos), `python-docx` (Word padrão ATS)
* **Infra:** Docker & docker-compose

# 🎯 ResumeForge: IA para Currículos Adaptativos

Acesse a plataforma: [resumeforge-jg6l.onrender.com](https://resumeforge-jg6l.onrender.com/)

O **ResumeForge** é uma aplicação web completa que utiliza Inteligência Artificial (Google Gemini) para comparar seu currículo base com uma vaga de emprego, apontar os pontos fortes e fracos, e gerar automaticamente um novo currículo personalizado (em Word `.docx`), além de uma Carta de Apresentação.

## 🚀 Como Rodar o Projeto

Existem duas formas de rodar o projeto na sua máquina: a forma tradicional via Python, e a forma recomendada via Docker (muito mais profissional e simples).

### Opção 1: Via Docker (Recomendado ⭐)

O Docker resolve todas as dependências de sistema sem instalar lixo na sua máquina.

1. Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Garanta que você preencheu o arquivo `.env` com sua `GEMINI_API_KEY, GROQ_API_KEY, GEMINI_MODEL e GROQ_MODEL`.
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
2. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```
3. Rode o servidor Flask:

   ```bash
   flask run --port=8501 --host=0.0.0.0
   ```
4. Acesse `http://localhost:8501` no seu navegador.

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python 3.11, Flask, Pydantic, Requests + BeautifulSoup (Scraping)
* **Frontend:** Tailwind CSS, Alpine.js, Plotly.js
* **IA:** Google GenAI SDK (Gemini) e Groq
* **Geradores:** `python-docx` (Word `.docx` padrão ATS)
* **Infra:** Docker & docker-compose


## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

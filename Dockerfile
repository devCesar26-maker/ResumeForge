FROM python:3.11-slim

# Instalar dependências de sistema (para o Playwright e o LaTeX)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-latex-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar bibliotecas Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar navegadores do Playwright (apenas os necessários)
RUN playwright install chromium
RUN playwright install-deps chromium

# Copiar código-fonte
COPY . .

# Expor a porta do Flask
EXPOSE 8501

# Comando de execução com Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8501", "--timeout", "120", "app:app"]

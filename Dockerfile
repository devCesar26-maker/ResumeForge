FROM python:3.11-slim

# Evita travamentos interativos durante a instalação dos pacotes do APT
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependências de sistema (LaTeX e ferramentas essenciais)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-latex-extra \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o código-fonte do projeto
COPY . .

# Expor a porta padrão
EXPOSE 8501

# Comando de execução com timeout de 180s e leitura dinâmica da porta do Render
CMD gunicorn --bind 0.0.0.0:${PORT:-8501} --timeout 180 app:app
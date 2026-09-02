FROM python:3.11-slim

WORKDIR /app

# Instalar bibliotecas Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código-fonte
COPY . .

# O Render gerencia a porta dinamicamente via variável $PORT
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 app:app
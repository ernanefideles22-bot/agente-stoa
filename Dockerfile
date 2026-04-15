FROM python:3.11-slim

LABEL maintainer="STOA Agent"
LABEL description="IA Multimodal com Reconhecimento de Voz"

WORKDIR /app

# Instala dependências de sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements
COPY stoa-agent-requirements.txt .

# Instala dependências Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r stoa-agent-requirements.txt

# Copia código
COPY main.py .
COPY .env .env.example ./

# Configuração
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV DEBUG=False

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health', timeout=5)"

# Expõe porta
EXPOSE 8000

# Inicia aplicação
CMD ["python", "-u", "main.py"]

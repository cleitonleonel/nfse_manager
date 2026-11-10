FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PYTHONPATH=/workspace/backend \
    TZ=America/Sao_Paulo

WORKDIR /workspace

# Dependências de sistema para lxml, xmlsec/cryptography, psycopg2 e git (para instalar pynfse)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && pip install --no-cache-dir poetry \
    && rm -rf /var/lib/apt/lists/*

# Copia manifesto de dependências da raiz
COPY pyproject.toml poetry.lock* README.md ./

# Instala dependências de produção
RUN poetry install --only main --no-root

# Copia o código do backend e cria diretórios de dados
COPY backend/app ./backend/app
RUN mkdir -p /workspace/backend/certificados /workspace/backend/downloads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/workspace/backend", "--host", "0.0.0.0", "--port", "8000"]

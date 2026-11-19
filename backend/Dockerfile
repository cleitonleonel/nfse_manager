FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PYTHONPATH=/workspace/backend \
    TZ=America/Sao_Paulo

WORKDIR /workspace

# Dependências de sistema para lxml, cffi/cryptography, pillow, psycopg2 e git (para instalar pynfse)
# Em arquiteturas 32-bit ARM (armhf / Raspberry Pi OS 32-bit), inclui rustc/cargo para compilar pydantic-core
RUN set -eux; \
    EXTRA_PKGS=""; \
    if [ "$(dpkg --print-architecture)" = "armhf" ]; then EXTRA_PKGS="rustc cargo"; fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    libfreetype-dev \
    zlib1g-dev \
    $EXTRA_PKGS \
    && pip install --no-cache-dir poetry \
    && rm -rf /var/lib/apt/lists/*

# Copia manifesto de dependências e changelogs da raiz
COPY pyproject.toml poetry.lock* README.md CHANGELOG.md* changelog.txt* ./

# Instala dependências de produção
RUN poetry install --only main --no-root

# Copia o código do backend e CLI manage.py, e cria diretórios de migrações/dados
COPY manage.py ./manage.py
COPY backend/app ./backend/app
RUN mkdir -p /workspace/backend/migrations/versions /workspace/backend/certificados /workspace/backend/downloads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/workspace/backend", "--host", "0.0.0.0", "--port", "8000"]

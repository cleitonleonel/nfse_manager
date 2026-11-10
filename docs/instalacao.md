# ⚙️ Instalação e Execução

O **NFSe Manager Pro** pode ser executado tanto de forma totalmente containerizada com **Docker e Docker Compose** quanto localmente com **Poetry + Uvicorn** ou como aplicativo **Desktop Tauri**.

---

## 1. Variáveis de Ambiente (`.env`)

Na raiz do projeto há um arquivo `.env.example`. Se desejar alterar credenciais ou portas, copie-o para `.env`:

```bash
cp .env.example .env
```

| Variável | Padrão | Descrição |
| :--- | :--- | :--- |
| `POSTGRES_DB` | `nfse_db` | Nome do banco PostgreSQL |
| `POSTGRES_USER` | `nfse_user` | Usuário do PostgreSQL |
| `POSTGRES_PASSWORD` | `nfse_pass` | Senha do PostgreSQL |
| `POSTGRES_HOST` | `localhost` (local) / `database` (Docker) | Host do banco de dados |
| `POSTGRES_PORT` | `5434` | Porta exposta no host para o PostgreSQL |
| `DATABASE_URL` | `postgresql+psycopg2://nfse_user:nfse_pass@localhost:5434/nfse_db` | URI de conexão SQLAlchemy |
| `BACKEND_PORT` | `8000` | Porta HTTP do Backend FastAPI |
| `FRONTEND_PORT` | `3000` | Porta HTTP do Frontend Nginx |

---

## 2. Executando com Docker Compose (Recomendado)

A arquitetura Docker do projeto é modular: cada camada possui seu próprio `Dockerfile` e `docker-compose.yml` (`database/`, `backend/` e `frontend/`), enquanto o `docker-compose.yml` da raiz utiliza `include` para orquestrar todos os serviços juntos.

=== "Subir Stack Completa (Raiz)"

    ```bash
    # Sobe PostgreSQL + Backend FastAPI + Frontend Nginx
    docker compose up -d --build

    # Acompanhar logs
    docker compose logs -f
    ```

=== "Subir Camadas Individualmente"

    ```bash
    # 1. Apenas o Banco de Dados (PostgreSQL 16)
    docker compose -f database/docker-compose.yml up -d --build

    # 2. Apenas o Backend (FastAPI)
    docker compose -f backend/docker-compose.yml up -d --build

    # 3. Apenas o Frontend (Nginx SPA)
    docker compose -f frontend/docker-compose.yml up -d --build
    ```

### Persistência de Dados no Docker

- **Banco de Dados**: persistido no volume nomeado `nfse_postgres_data`.
- **Certificados Digitais A1 (`.pfx`)**: persistidos em `backend/certificados/`.
- **XMLs, PDFs e Lotes ZIP**: persistidos em `backend/downloads/`.

---

## 3. Executando Localmente com Poetry

Para desenvolvimento local do Python/FastAPI:

1. **Inicie o container do PostgreSQL**:
   ```bash
   docker compose -f database/docker-compose.yml up -d
   ```
2. **Instale as dependências com Poetry**:
   ```bash
   poetry install --with dev
   ```
3. **Suba o servidor web**:
   ```bash
   ./run_web.sh
   ```
   Ou diretamente com Uvicorn apontando `--app-dir backend` para o pacote `app`:
   ```bash
   poetry run python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
   ```

!!! tip "Importações no Backend"
    O diretório `backend/` é a raiz do Python (`PYTHONPATH=backend`), portanto todos os imports internos utilizam o pacote `app` (`from app.models import ...`, `from app.database import ...`, `from app.services.adn_service import AdnService`).

---

## 4. Visualizando e Gerando a Documentação (MkDocs)

Para rodar o servidor local da documentação com live-reload ou gerar o pacote estático do GitHub Pages:

```bash
# Servidor local em http://127.0.0.1:8001
poetry run mkdocs serve -a 127.0.0.1:8001

# Gerar site estático na pasta site/
poetry run mkdocs build --strict
```

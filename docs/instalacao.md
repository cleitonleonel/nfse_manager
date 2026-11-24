# ⚙️ Instalação e Execução

O **NFSe Manager Pro** pode ser executado tanto de forma totalmente containerizada com **Docker e Docker Compose** quanto localmente com **Poetry + Uvicorn** ou como aplicativo **Desktop Tauri**.

---

## 1. Clonar o Repositório

```bash
git clone https://github.com/cleitonleonel/nfse_manager.git
cd nfse_manager
```

---

## 2. Variáveis de Ambiente (`.env`)

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
| `NFSE_ENCRYPTION_KEY` | *(chave mestra padrão de dev)* | Chave simétrica para criptografia em repouso das senhas de clientes e certificados (AES/Fernet) |
| `JWT_SECRET_KEY` | Derivada de `NFSE_ENCRYPTION_KEY` | Chave secreta para assinatura de tokens JWT (`HS256`) dos operadores |
| `NFSE_DATA_DIR` | `backend/` (ou `%PROGRAMDATA%\NFSeManager` no binário frozen Windows) | Diretório raiz compartilhado para certificados e downloads (ex.: share UNC `\\SERVIDOR\NFSeData`) |
| `NFSE_CERTS_DIR` | `{NFSE_DATA_DIR}/certificados` | Diretório dedicado para armazenamento dos certificados `.pfx` |
| `NFSE_DOWNLOADS_DIR` | `{NFSE_DATA_DIR}/downloads` | Diretório dedicado para XMLs, PDFs e lotes ZIP |
| `NFSE_CATALOGS_DIR` | `{NFSE_DATA_DIR}/catalogs` | Cache compartilhado gravável dos catálogos oficiais sincronizados (`V0073`, NBS, `cClassTrib`, Anexos VII/VIII) |
| `NFSE_DEPLOYMENT_MODE` | Auto-detectado | Modo exibido no diagnóstico (`server`, `standalone`, `client`) |
| `NFSE_SCHEDULER_MODE` | `auto` | Controle do worker de contingência (`auto`, `leader` ou `disabled`) |
| `NFSE_ALLOW_PUBLIC_REGISTER` | `1` | Define se novos usuários podem se auto-cadastrar após o 1º admin (`0` fecha o cadastro público para uso corporativo) |
| `NFSE_ALLOW_OPERATOR_CREATE_CLIENT` | `1` | Define se usuários não-admin podem cadastrar novas empresas (ficando vinculados como `manager` somente das empresas que criarem; `0` restringe a criação ao Admin) |
| `NFSE_DISABLE_SELF_UPDATE` | `0` (`1` em sidecar frozen) | Desabilita auto-atualização via GitHub na UI (`403`) em servidores gerenciados / WTS |
| `DEFAULT_SMTP_*` | Vazio (`PORT=587`, `TLS=1`) | Credenciais SMTP padrão do sistema (envio de NFS-e sem SMTP próprio e notificações de suporte) |
| `SUPPORT_EMAIL_TO` | `cleiton.leonel@gmail.com` | Destinatário das mensagens enviadas pelo formulário de Suporte & Feedback |
| `SUPPORT_TELEGRAM_BOT_TOKEN` | Vazio | Token do bot Telegram (`@BotFather`) para encaminhar mensagens de suporte |
| `SUPPORT_TELEGRAM_CHAT_ID` | `@cleitonLC` | `chat_id` numérico (para DM privada após `/start`) ou canal/grupo de destino no Telegram |

> 🔒 **Dica de Segurança:** Em produção, gere uma chave criptográfica forte para `NFSE_ENCRYPTION_KEY` (por exemplo: `python -c "import secrets; print(secrets.token_hex(32))"`). Em ambientes multiusuário (escritórios contábeis), configure `NFSE_ALLOW_PUBLIC_REGISTER=0`, `NFSE_ALLOW_OPERATOR_CREATE_CLIENT=0` e `DB_FALLBACK_SQLITE=0` após criar o administrador inicial, gerenciando os operadores e seus vínculos de empresas em **Equipe** (visível para administradores).

---

## 3. Executando com Docker Compose (Recomendado)

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

!!! tip "Raspberry Pi / ARM (`arm64` vs `armhf`)"
    O `backend/Dockerfile` inclui `libffi-dev`, `libssl-dev`, `pkg-config`, `libjpeg-dev`, `libfreetype-dev` e instala automaticamente `rustc`/`cargo` quando detecta ambiente 32-bit (`armhf`). Ainda assim, recomenda-se usar **Raspberry Pi OS 64-bit (`arm64`/`aarch64`)**, pois há *wheels* pré-compilados no PyPI e o build é muito mais rápido.

---

## 4. Executando Localmente com Poetry

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

## 5. Visualizando e Gerando a Documentação (MkDocs)

Para rodar o servidor local da documentação com live-reload ou gerar o pacote estático do GitHub Pages:

```bash
# Servidor local em http://127.0.0.1:8001
poetry run mkdocs serve -a 127.0.0.1:8001

# Gerar site estático na pasta site/
poetry run mkdocs build --strict
```

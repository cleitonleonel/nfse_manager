# Regras do Projeto — NFSe Manager Pro

Estas diretrizes aplicam-se a todas as sessões de IA que operarem neste repositório.

## 1. Commits, Versionamento e Releases
- **Padrão de commits:** utilizar sempre `:emoji: <tipo>: <mensagem clara>` em português (ex.: `:sparkles: feat: ...`, `:bug: fix: ...`, `:art: chore: ...`, `:bookmark: chore: publica release vX.Y.Z — ...`).
- **Comando único de release:** utilizar `python manage.py release [patch|minor|major|X.Y.Z] --notes "..."` (que reutiliza `scripts/bump_version.py`), mantendo sincronizados `pyproject.toml`, `ui/package.json`, `ui/package-lock.json`, `ui/src-tauri/Cargo.toml`, `ui/src-tauri/tauri.conf.json`, `frontend/views/about.html`, `CHANGELOG.md` e `changelog.txt`.
- **Stage seguro:** nunca executar `git add -A` cegamente para não versionar arquivos locais ignoráveis (`backend/nfse.db`, `.env`, `skills/`, caches).
- **GitHub Actions:** no fluxo padrão, enviar apenas o commit da branch (`--push` sem `--tag`); `.github/workflows/auto-release.yml` valida os testes, cria a tag/Release e dispara `.github/workflows/desktop-installers.yml` (Linux e Windows).

## 2. Verificações Obrigatórias Antes de Concluir
Sempre validar todas as camadas afetadas após a última edição antes de reportar sucesso:
- **Backend Python:** `ruff check --no-cache backend tests` (incluir `manage.py` e `scripts/*.py` quando alterados).
- **Frontend JS:** `node --check` em todos os módulos `.js` modificados ou criados.
- **Testes em SQLite limpo:** executar `pytest` apontando `DATABASE_URL` para um arquivo temporário em `/tmp/` e removê-lo após o teste (nunca depender do `backend/nfse.db` local).
- **Testes em PostgreSQL 16:** validar a suíte completa contra um banco temporário no PostgreSQL (ex.: `nfse_pytest_ci`), confirmando `engine.dialect.name == "postgresql"` e removendo o banco temporário ao final — nunca usar o fallback silencioso para SQLite achando que rodou PostgreSQL.
- **Documentação:** `mkdocs build --strict` sempre que alterar `docs/` ou `mkdocs.yml`.
- **Containers locais:** quando os containers Docker (`nfse_backend`, `nfse_frontend`) estiverem ativos no ambiente, sincronizar os arquivos atualizados via `docker cp`, reiniciar `nfse_backend` se houver alteração Python e verificar `/api/health`.

## 3. Arquitetura, Segurança e Banco de Dados
- **Segredos e `.env`:** nunca comitar `.env`, `NFSE_ENCRYPTION_KEY`, senhas ou certificados (`.pfx`) no Git nem embuti-los no instalador Tauri. Para uso com Docker, apontar o Tauri via `server_url` (`desktop.json` ou modal **Configurar Servidor Central**); em modo standalone, `load_dotenv_if_present()` também lê `<NFSE_DATA_DIR>/.env`.
- **Isolamento de `save_path` e espelhamento local:** apenas usuários `admin` podem definir/alterar `Client.save_path` no backend, restrito a `get_downloads_dir()` (`NFSE_DOWNLOADS_DIR`), salvo `NFSE_ALLOW_CUSTOM_CLIENT_SAVE_PATH=1`. O espelhamento na máquina do operador ocorre exclusivamente no frontend via File System Access API (`frontend/js/core/local-mirror.js`).
- **Portabilidade de caminhos:** sempre resolver caminhos persistidos via `resolve_storage_path()` / `to_storage_relative_path()` com fallback para `get_downloads_dir()` / `get_certs_dir()` quando caminhos legados de container/outro SO não existirem no host, e higienizar espaços em segmentos de `path_structure`.
- **PostgreSQL & FKs:** locks distribuídos (`pg_try_advisory_lock`) devem rodar em conexão dedicada isolada da sessão ORM principal e liberar explicitamente no `finally`. Ao excluir registros locais de `Invoice`, desvincular `BatchImportItem.invoice_id = None` antes do `DELETE`.

## 4. UX, Tauri Desktop e Mensagens de Erro
- **Compatibilidade WebKitGTK (Tauri Linux):** não depender de controles sem suporte nativo no WebKitGTK (como `<input type="month">` sem popover customizado ou `window.showDirectoryPicker()` obrigatório sem fallback).
- **Feedback honesto de erros:** tarefas em background (como `background_download`) nunca devem retornar `status = "completed"` com sucesso se todas as notas falharem; erros SMTP (`EmailService._dispatch_smtp`) devem distinguir falhas de autenticação (`SMTPAuthenticationError` / desconexão durante `login`), porta/TLS e timeout com mensagens claras em PT-BR.
- **Idioma e código:** manter UI, documentação e respostas ao usuário em PT-BR, evitar duplicação de lógica e manter links clicáveis para arquivos e símbolos citados.

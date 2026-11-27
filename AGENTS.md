# Regras do Projeto — NFSe Manager Pro

Estas diretrizes aplicam-se a todas as sessões de IA que operarem neste repositório.

## 1. Commits, Versionamento e Releases
- **Padrão de commits:** utilizar sempre `:emoji: <tipo>: <mensagem clara>` em português (ex.: `:sparkles: feat: ...`, `:bug: fix: ...`, `:art: chore: ...`, `:bookmark: chore: publica release vX.Y.Z — ...`).
- **Comando único de release:** utilizar `python manage.py release [patch|minor|major|X.Y.Z] --notes "..."` (que reutiliza `scripts/bump_version.py`), mantendo sincronizados `pyproject.toml`, `ui/package.json`, `ui/package-lock.json`, `ui/src-tauri/Cargo.toml`, `ui/src-tauri/tauri.conf.json`, `frontend/views/about.html`, `CHANGELOG.md` e `changelog.txt`.
- **Stage seguro:** nunca executar `git add -A` cegamente para não versionar arquivos locais ignoráveis (`backend/nfse.db`, `.env`, `skills/`, caches).
- **GitHub Actions:** `.github/workflows/ci.yml` valida lint, boot, SQLite, PostgreSQL 16 e documentação a cada push/PR na branch principal **sem criar tags ou releases**. Releases/tags só devem ser criadas quando o usuário solicitar explicitamente (`python manage.py release ...` + `--push` sem `--tag`, deixando `.github/workflows/auto-release.yml` publicar a tag/Release e disparar `.github/workflows/desktop-installers.yml`).

## 2. Verificações Obrigatórias Antes de Concluir
Sempre validar todas as camadas afetadas após a última edição antes de reportar sucesso:
- **Sincronização de `pynfse` e `poetry.lock`:** sempre que o backend passar a usar novos símbolos, parâmetros ou regras do `pynfse` (`emissor_nfse`), garantir que o commit correspondente já esteja enviado no `origin` do `emissor_nfse`, rodar `poetry update pynfse --lock` e commitar `poetry.lock` junto com o código (nunca confiar apenas no `pynfse` editável local; o teste `tests/test_lockfile_pynfse_sync.py` bloqueia drift).
- **Backend Python:** `ruff check --no-cache backend tests` (incluir `manage.py` e `scripts/*.py` quando alterados).
- **Frontend JS:** `node --check` em todos os módulos `.js` modificados ou criados.
- **Testes em SQLite limpo:** executar `pytest` apontando `DATABASE_URL` para um arquivo temporário em `/tmp/` e removê-lo após o teste (nunca depender do `backend/nfse.db` local).
- **Testes em PostgreSQL 16:** validar a suíte completa contra um banco temporário no PostgreSQL (ex.: `nfse_pytest_ci`), confirmando `engine.dialect.name == "postgresql"` e removendo o banco temporário ao final — nunca usar o fallback silencioso para SQLite achando que rodou PostgreSQL.
- **Documentação:** `mkdocs build --strict` sempre que alterar `docs/` ou `mkdocs.yml`.
- **Containers locais:** quando os containers Docker (`nfse_backend`, `nfse_frontend`) estiverem ativos no ambiente, sincronizar os arquivos atualizados via `docker cp` (ou reconstruir com `docker compose up -d --build backend` sempre que `pyproject.toml`/`poetry.lock` mudar), reiniciar `nfse_backend` se houver alteração Python e verificar `/api/health`.

## 3. Arquitetura, Segurança e Banco de Dados
- **Segredos e `.env`:** nunca comitar `.env`, `NFSE_ENCRYPTION_KEY`, senhas ou certificados (`.pfx`) no Git nem embuti-los no instalador Tauri. Para uso com Docker, apontar o Tauri via `server_url` (`desktop.json` ou modal **Configurar Servidor Central**); em modo standalone, `load_dotenv_if_present()` também lê `<NFSE_DATA_DIR>/.env`.
- **Isolamento de `save_path` e espelhamento local:** apenas usuários `admin` podem definir/alterar `Client.save_path` no backend, restrito a `get_downloads_dir()` (`NFSE_DOWNLOADS_DIR`), salvo `NFSE_ALLOW_CUSTOM_CLIENT_SAVE_PATH=1`. O espelhamento na máquina do operador ocorre exclusivamente no frontend via File System Access API (`frontend/js/core/local-mirror.js`).
- **Portabilidade de caminhos:** sempre resolver caminhos persistidos via `resolve_storage_path()` / `to_storage_relative_path()` com fallback para `get_downloads_dir()` / `get_certs_dir()` quando caminhos legados de container/outro SO não existirem no host, e higienizar espaços em segmentos de `path_structure`.
- **PostgreSQL & FKs:** locks distribuídos (`pg_try_advisory_lock`) devem rodar em conexão dedicada isolada da sessão ORM principal e liberar explicitamente no `finally`. Ao excluir registros locais de `Invoice`, desvincular `BatchImportItem.invoice_id = None` antes do `DELETE`.

## 4. UX, Tauri Desktop e Mensagens de Erro
- **Compatibilidade WebKitGTK (Tauri Linux):** não depender de controles sem suporte nativo no WebKitGTK (como `<input type="month">` sem popover customizado ou `window.showDirectoryPicker()` obrigatório sem fallback).
- **Feedback honesto de erros:** tarefas em background (como `background_download`) nunca devem retornar `status = "completed"` com sucesso se todas as notas falharem; erros SMTP (`EmailService._dispatch_smtp`) devem distinguir falhas de autenticação (`SMTPAuthenticationError` / desconexão durante `login`), porta/TLS e timeout com mensagens claras em PT-BR.
- **Idioma e código:** manter UI, documentação e respostas ao usuário em PT-BR, evitar duplicação de lógica e manter links clicáveis para arquivos e símbolos citados.

## 5. Equipe Contábil & Skills Fiscais (`.agents/skills/`)
Sempre que a tarefa envolver legislação da NFS-e Nacional (NT 008 / NT 1.101), Reforma Tributária (`LC 214/2025` — IBS/CBS), regimes tributários (`MEI`, `Simples Nacional`, `Lucro Presumido`, `Lucro Real`), retenções, catálogos RFB ou cálculos fiscais:
- Ativar a skill orquestradora `.agents/skills/nfse-contabilidade-equipe/SKILL.md` e suas especialistas (`.agents/skills/nfse-normas-e-reforma/`, `.agents/skills/nfse-matematica-tributaria/` e `.agents/skills/nfse-implementacao-fiscal/`).
- Validar qualquer mudança numérica executando `.agents/skills/nfse-matematica-tributaria/scripts/audit_tax_math.py`, mantendo fonte única de verdade em `pynfse.adn.tax_calculator` e `AdnService`.

## 6. Equipe Sênior Fixa & Crivo Obrigatório (`.agents/skills/nfse-equipe-engenharia/`)
A equipe fixa de engenharia do produto é composta por 4 especialistas persistentes em `.agents/skills/`, orquestrados por `.agents/skills/nfse-equipe-engenharia/SKILL.md`. Nenhuma entrega pode ser considerada concluída sem pesquisa prévia, troca de pareceres quando aplicável, aprovação do usuário para decisões estruturais e crivo final obrigatório via subagentes dedicados:
- **Arquiteto de Software & Data Designer Sênior (`.agents/skills/nfse-arquiteto-e-dados/SKILL.md`):** revisar modelagem relacional, design de dados (PostgreSQL 16 / SQLite), migrações, acoplamento e proteção anti-IDOR/RBAC em todas as rotas afetadas antes de concluir.
- **Engenheiro Backend & Fullstack Sênior (`.agents/skills/nfse-dev-fullstack/SKILL.md`):** diagnosticar causa raiz, implementar backend Python/FastAPI e frontend SPA sem duplicação de lógica e manter `docs/` atualizado.
- **Designer UI/UX Sênior — Material Design 3 (`.agents/skills/nfse-designer-material-ux/SKILL.md`):** revisar toda alteração de interface (`frontend/views/`, `frontend/css/`, `frontend/js/`) aplicando padrões modernos inspirados em Google Material Design 3, Vue/React/Flutter/Mobile-first, acessibilidade WCAG AA, temas claro/escuro e compatibilidade WebKitGTK (Tauri).
- **Engenheiro de QA & Testes Sênior (`.agents/skills/nfse-qa-engenheiro/SKILL.md`):** garantir testes automatizados cobrindo cenários novos, negativos (403/400/404) e regressões; **todos** os testes (`pytest` em SQLite limpo + PostgreSQL 16, `ruff`, `node --check` e `mkdocs build --strict` quando aplicável) devem passar 100% antes da entrega final.



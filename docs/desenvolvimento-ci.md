# 🧪 Testes, Versionamento e CI/CD

Esta seção documenta os padrões de qualidade de código, a suíte de testes automatizados, o fluxo de versionamento semântico e os pipelines do **GitHub Actions**.

---

## 1. Suíte de Testes Automatizados (`tests/`)

Os testes utilizam **Pytest** e `fastapi.testclient.TestClient` conectados ao banco **PostgreSQL** ou SQLite WAL em fallback (**74 testes automatizados**):

```bash
poetry run pytest -v
```

### Cobertura dos Módulos de Teste

- **`tests/test_adn_emission_and_tax.py`**:
  - CRUD completo de clientes com campos fiscais ADN v1.01 e persistência de certificado `.pfx` em `backend/certificados/`.
  - Contagem e busca nos catálogos fiscais (`18 CST`, `138 cClassTrib`, `338 cTribNac`, `28 cIndOp`, `Anexo VIII`).
  - Calculadora tributária nos cenários `2026`, `2027` e `2033+`, incluindo reduções de alíquota (`Saúde 60%`, `Prouni 60%/100%`, `Profissão Regulamentada 30%`, `Locação Imóvel 70%`).
  - Regras de validação IBS/CBS (`E0905`, `E0910`, `E0931`, `E0958`, `E0959`, `E0966`).
  - Geração de XML, assinatura `XML-DSig` (`infDPS` e `infPedReg`), validação contra schemas `XSD v1.01` e emissão/substituição/cancelamento ADN.
  - Filtro de combinações `NBS × cClassTrib × cIndOp`, persistência SMTP por cliente com preservação de senha e download sob demanda de XML/PDF no envio de e-mail.
- **`tests/test_versioning_and_updates.py`**:
  - Sincronia entre `pyproject.toml`, `app.version.VERSION` e `GET /api/system/version`.
  - Verificação de nova release (`GET /api/system/check-update`).
  - Extração em `release/staging/` e cópia transacional com preservação de `backend/certificados/` e `backend/downloads/`.
  - Validação do endpoint `/api/health`, dos arquivos `Dockerfile` / `docker-compose.yml` e dos scripts de CI/release.
- **`tests/test_xml_canonicalization_nt.py`**:
  - Determinismo de canonicalização `C14N 1.0`, verificação criptográfica de `DigestValue` / `SignatureValue` após assinatura `XML-DSig`, ausência de tags vazias, ordenação estrita de elementos XSD (`DPS_v1.01.xsd` e `pedRegEvento_v1.01.xsd`) e cenários multi-NT/competência (`2026`, saúde `200029`, `2027`, substituição `<subst>`, eventos `e101101`/`e105102`).
- **`tests/test_batch_import_and_competencia.py`**:
  - Emissão em lote (`/api/adn/dps/emitir-lote`) com isolamento de falhas por item e gravação de `data_competencia`.
  - Modelos e importação em massa CSV/XLSX de tomadores (inclusive CNPJ alfanumérico) e serviços (com enriquecimento automático via Anexo VIII).
  - Relatório mensal por competência (`/api/reports/competencia`) nos formatos JSON, CSV e XLSX separando notas ativas, canceladas/substituídas e pendentes na fila.
- **`tests/test_batch_emission_v2.py`**:
  - Módulo persistente `/api/batch-emission`: leitura CSV (`;` e `,`), XLSX com zeros à esquerda, validação em 3 níveis (estrutural, cadastral e fiscal/XSD), correção inline por linha (`PATCH`), processamento sequencial tolerante a rejeições (`REJECTED`), recuperação idempotente de `UNKNOWN` via `consultar_dps`, cancelamento de pendentes e exportação CSV/XLSX.
- **`tests/test_router_auth_guards.py`**:
  - Proteção JWT obrigatória (`401`) em todos os routers de negócio, RBAC `admin` vs `operador` (`403`), gestão completa via `PATCH /api/auth/users/{id}`, bloqueio contra auto-rebaixamento/exclusão do último admin, `NFSE_ALLOW_PUBLIC_REGISTER=0`, `/api/system/environment`, `NFSE_DISABLE_SELF_UPDATE=1`, proteção contra Path Traversal em `/api/download/file` e envio de suporte (E-mail + Telegram).
- **`tests/test_multiuser_wts_concurrency.py`**:
  - Diretórios portáveis (`NFSE_DATA_DIR`, `NFSE_CERTS_DIR`, `NFSE_DOWNLOADS_DIR`), reserva concorrente de `ultimo_numero_dps` em múltiplas threads sem colisão, persistência de tarefas em `background_tasks` (`TaskStore`) e lock distribuído do `SchedulerService` (`scheduler_locks` / `NFSE_SCHEDULER_MODE=disabled`).

---

## 2. Linter e Qualidade de Código (Ruff)

O projeto utiliza o **Ruff** configurado no `pyproject.toml` (`src = ["backend", "tests"]`, `line-length = 120`):

```bash
poetry run ruff check backend tests
```

---

## 3. Versionamento Centralizado e Releases

A versão única do projeto fica em `pyproject.toml` (`[project] version = "X.Y.Z"`). O comando unificado `manage.py release` (que reutiliza `scripts/bump_version.py`) busca tags remotas antes de calcular o diff, atualiza todos os manifestos (`pyproject.toml`, `ui/package.json`, `ui/package-lock.json`, `ui/src-tauri/Cargo.toml`, `ui/src-tauri/tauri.conf.json`, `frontend/views/about.html`), gera `CHANGELOG.md` / `changelog.txt` e cria o commit sem incluir arquivos locais ignoráveis (`*.db`, `skills/`):

```bash
# Release completa de correção (patch, ex.: 0.2.2 -> 0.2.3) com commit e push
python manage.py release --notes "Resumo das melhorias" --push

# Release de funcionalidade (minor) ou versão explícita
python manage.py release minor --notes "Novos recursos" --push
python manage.py release 0.3.0 --push

# Apenas simular ou preparar localmente sem enviar ao GitHub
python manage.py release --dry-run
python manage.py release --no-commit
```

!!! tip "Autenticação interativa no push"
    Se o `git push` exigir autenticação interativa de credencial/SSH no terminal, rode `python manage.py release --notes "..."` sem `--push` e execute apenas `git push origin master` diretamente no seu terminal.

Para uso direto dos scripts subjacentes:

```bash
# Atualizar versão manualmente (explícita ou patch/minor/major) + changelog
poetry run python scripts/bump_version.py 0.2.0 --notes "Resumo dos destaques"
# ou apenas sincronizar a partir do pyproject.toml:
poetry run python scripts/sync_version.py

# Criar tag e release localmente (quando aplicável)
./scripts/release.sh
```

---

## 4. Pipelines GitHub Actions (`.github/workflows/`)

O repositório conta com três workflows automatizados:

### 4.1. Auto-Release (`.github/workflows/auto-release.yml`)
- Disparado automaticamente em `push` para `main`/`master`, `workflow_dispatch` ou ao mesclar Pull Request com a label `release`.
- Sobe um container de serviço `postgres:16-alpine`.
- Instala dependências com Poetry e executa `ruff check` + `pytest -v`.
- Lê a versão via `PYTHONPATH=backend poetry run python -c "from app.version import VERSION; print(VERSION)"`.
- Se a tag `vX.Y.Z` ainda não existir no remoto, cria a tag, publica a Release no GitHub com as notas extraídas do `CHANGELOG.md` e aciona o workflow `desktop-installers.yml`.

### 4.2. Instaladores Desktop Multi-OS (`.github/workflows/desktop-installers.yml`)
- Disparado manualmente (`workflow_dispatch`) ou automaticamente ao enviar uma tag `v*`.
- Executa em matriz **`ubuntu-latest`** e **`windows-latest`**.
- Empacota o sidecar Python via PyInstaller (`ui/build_sidecar.sh` / `ui/build_sidecar.ps1`) e compila o app Tauri.
- Publica os artefatos e os anexa diretamente na GitHub Release:
  - **Linux**: `.deb` e `.AppImage`
  - **Windows**: `.msi` e `.exe` (NSIS)

### 4.3. Publicação no GitHub Pages (`.github/workflows/docs.yml`)
- Disparado automaticamente a cada `push` em `main` / `master` (ou manualmente via `workflow_dispatch`).
- Instala o `mkdocs-material` e executa `mkdocs build --strict`.
- Publica o site estático diretamente no **GitHub Pages** usando `actions/upload-pages-artifact` e `actions/deploy-pages`.

!!! info "Como ativar o GitHub Pages no repositório"
    No GitHub, acesse **Settings → Pages → Build and deployment** e selecione **Source: GitHub Actions**. Na próxima execução do workflow `Deploy Documentation to GitHub Pages`, o site estará publicado em `https://cleitonleonel.github.io/nfse_manager/`.

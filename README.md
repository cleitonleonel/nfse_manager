# 🚀 NFSe Manager Pro

<p align="center">
  <a href="https://github.com/cleitonleonel/nfse_manager">
    <img src="docs/assets/nfse_manager.png" alt="nfse_manager logo" width="45%" height="auto">
  </a>
</p>

<p align="center">
  <i>Plataforma completa para gestão, sincronização, cálculo tributário (IBS/CBS e ISSQN) e emissão de NFS-e Nacional (ADN / Sefin Nacional v1.01) com backend FastAPI, banco PostgreSQL, frontend SPA e versão desktop nativa em Tauri.</i>
</p>

---

## 📌 Sumário

1. [Sobre o Projeto](#-sobre-o-projeto)
2. [Principais Funcionalidades](#-principais-funcionalidades)
3. [Arquitetura e Stack Tecnológica](#-arquitetura-e-stack-tecnológica)
4. [Estrutura de Diretórios](#-estrutura-de-diretórios)
5. [Configuração e Variáveis de Ambiente](#-configuração-e-variáveis-de-ambiente)
6. [Como Executar (Docker, Local e Desktop)](#-como-executar)
7. [Referência da API e Exemplos Práticos](#-referência-da-api-e-exemplos-práticos)
8. [Modelo de Dados (PostgreSQL)](#-modelo-de-dados-postgresql)
9. [Testes, Qualidade e CI/CD](#-testes-qualidade-e-cicd)
10. [Documentação Técnica Detalhada](#-documentação-técnica-detalhada)

---

## 📖 Sobre o Projeto

O **NFSe Manager Pro** centraliza a operação fiscal de múltiplos clientes/CNPJs em uma única interface web ou desktop. Ele atua em duas frentes complementares através do pacote [`pynfse`](https://github.com/cleitonleonel/emissor_nfse):

1. **Sincronização e Gestão via Portal Nacional**: autentica via credenciais ou Certificado Digital A1 (`.pfx`), consulta notas emitidas e recebidas por período, baixa XMLs e PDFs (com geração local offline de DANFSE quando o portal não disponibiliza o PDF), enriquece dados no banco **PostgreSQL** e exporta relatórios gerenciais.
2. **Emissão ADN / Sefin Nacional v1.01 e Reforma Tributária (LC 214/2025 — NT 1.101)**: disponibiliza catálogos fiscais oficiais (`CST`, `cClassTrib`, `cTribNac`, `LC 116`, `Anexo VIII`, `cIndOp`), motor de cálculo e validação tributária (`ISSQN`, retenções federais e `IBS/CBS` para os cenários 2026, 2027–2032 e 2033+), construção e assinatura `XML-DSig` (`infDPS` e `infPedReg`), validação contra schemas `XSD v1.01` e transmissão mTLS de **Emissão de DPS**, **Cancelamento (`e101101`)** e **Substituição (`e105102`)**.

![Dashboard e Visão Geral](docs/assets/1.jpeg)
![Gerenciamento e Notas](docs/assets/2.jpeg)

---

## ✨ Principais Funcionalidades

- **Gestão Multi-CNPJ de Clientes**:
  - Cadastro de credenciais do portal, upload de certificado digital A1 (`.pfx`) e senha.
  - Configuração de parâmetros fiscais ADN v1.01 (Inscrição Municipal, código IBGE, regime tributário `normal | simples | mei`, regime de apuração SN, série e numeração de DPS, ambiente `homologacao | producao`).
  - Personalização de diretório de saída e máscara dinâmica de pastas (`{CLIENTE}/{TIPO}/{ANO}/{MES}`).
- **Sincronização e Downloads Inteligentes**:
  - Sincronização assíncrona em background de notas `emitidas` e `recebidas` com barra de progresso em tempo real.
  - Download individual ou em lote (`.zip`), recuperação automática de arquivos ausentes e **geração local de PDF (DANFSE)** a partir do XML.
- **Emissão de NFS-e e Eventos no ADN (Sefin Nacional v1.01)**:
  - Preview e validação XSD de XML da DPS antes do envio.
  - Assinatura digital A1 (`RSA-SHA256`) e transmissão mTLS para o Ambiente de Dados Nacional (ADN).
  - Cancelamento de NFS-e (`e101101`) e Substituição de NFS-e (`<subst>` + evento `e105102`).
  - Consulta de parâmetros municipais (convênio e alíquotas por código IBGE).
- **Motor Tributário da Reforma Tributária (NT 1.101 / LC 214/2025)**:
  - Catálogos completos: 18 `CST`, 138 `cClassTrib`, 338 serviços `cTribNac`, subitens da `LC 116/2003`, 1.739 correlações do `Anexo VIII` e 28 indicadores `cIndOp`.
  - Cálculo integrado de `ISSQN`, retenções federais (`PIS`, `COFINS`, `IRRF`, `CSLL`, `INSS`) e `IBS/CBS` (com suporte a reduções de alíquota, diferimento, crédito presumido, tributação regular e compras governamentais).
- **Analytics e Relatórios**:
  - Dashboard com KPIs financeiros, gráfico temporal (`7d`, `30d`, `90d`, `12m`), ranking de clientes e enriquecimento de notas via XML.
  - Exportação de relatórios financeiros em **JSON**, **CSV** e **XLSX (Excel)**.
- **Auto-Update Transacional**:
  - Consulta de novas versões no GitHub Releases, download em background para `release/staging/`, backup automático com rollback em caso de falha e reinicialização assistida.

---

## 🏗️ Arquitetura e Stack Tecnológica

```mermaid
flowchart LR
    subgraph Client["Camada de Apresentação"]
        SPA["Frontend SPA (HTML/CSS/JS ES6)<br/>Nginx :3000 ou FastAPI Static"]
        Tauri["Desktop App (Tauri / Rust)"]
    end

    subgraph Backend["Camada de Aplicação (backend/app)"]
        API["FastAPI (:8000)<br/>app.main:app"]
        Routers["9 Routers REST<br/>(/api/*)"]
        AdnSvc["AdnService<br/>(pynfse.adn)"]
        PortalBot["ClienteNfseNacional<br/>(pynfse)"]
    end

    subgraph Infra["Persistência e Integrações Externas"]
        PG[("PostgreSQL 16<br/>(:5434 -> :5432)")]
        FS[("Storage Local<br/>backend/certificados<br/>backend/downloads")]
        ADN["ADN / Sefin Nacional<br/>(API mTLS v1.01)"]
        Portal["Portal Nacional NFS-e"]
    end

    Tauri --> SPA
    SPA -->|HTTP / JSON| API
    API --> Routers
    Routers --> PG
    Routers --> FS
    Routers --> AdnSvc
    Routers --> PortalBot
    AdnSvc -->|mTLS + XML-DSig| ADN
    PortalBot -->|HTTPS / Sessão| Portal
```

### Tecnologias Utilizadas

| Camada | Tecnologias |
| :--- | :--- |
| **Backend** | Python 3.12+, FastAPI, Uvicorn, SQLAlchemy 2.0, Pydantic v2, HTTPX, OpenPyXL |
| **Motor Fiscal / NFSe** | `pynfse` (`ClienteNfseNacional`, `pynfse.adn`, `DanfseGenerator`, `XsdValidator`, `DpsSigner`) |
| **Banco de Dados** | PostgreSQL 16 (`psycopg2-binary`) |
| **Frontend Web** | HTML5, CSS3 Modular, JavaScript Vanilla (ES6 Modules), Nginx 1.27 Alpine |
| **Desktop** | Tauri (Rust + WebView nativo + PyInstaller sidecar) |
| **Infra & Qualidade** | Docker, Docker Compose (multi-compose com `include`), Poetry, Pytest, Ruff, GitHub Actions |

---

## 🧱 Estrutura de Diretórios

```text
nfse_manager/
├── 🐘 database/                         # Container dedicado do banco PostgreSQL 16
│   ├── Dockerfile
│   └── docker-compose.yml
├── 📁 backend/                          # Diretório raiz do Backend
│   ├── Dockerfile                       # Imagem Docker da API FastAPI
│   ├── docker-compose.yml               # Compose dedicado do Backend
│   ├── 🔐 certificados/                 # Certificados digitais A1 (.pfx) enviados
│   ├── 📂 downloads/                    # XMLs, PDFs, lotes ZIP e artefatos ADN (dps, nfse, eventos)
│   └── 📦 app/                          # Pacote Python principal da aplicação (app)
│       ├── main.py                      # Entrypoint FastAPI, middlewares, healthcheck e static mount
│       ├── database.py                  # Engine SQLAlchemy (PostgreSQL) e dependência get_db()
│       ├── models.py                    # Tabelas SQLAlchemy (Client, Invoice) e init_db()
│       ├── schemas.py                   # Schemas Pydantic de entrada e saída
│       ├── version.py                   # Leitura dinâmica da versão a partir do pyproject.toml
│       ├── services/
│       │   └── adn_service.py           # Orquestração fiscal ADN / Sefin Nacional v1.01
│       └── api/
│           ├── deps.py                  # Factory de ClienteNfseNacional com paths do backend
│           ├── state.py                 # Estado em memória (tasks_status) das tarefas em background
│           └── routers/                 # Rotas modulares por domínio
│               ├── clients.py           # CRUD de clientes e upload de certificado .pfx
│               ├── invoices.py          # Sincronização (/api/sync), tasks e listagem de notas
│               ├── downloads.py         # Download individual, lote ZIP e geração de DANFSE local
│               ├── analytics.py         # KPIs, série temporal, ranking e enriquecimento XML
│               ├── reports.py           # Exportação de relatórios (JSON, CSV, XLSX)
│               ├── system.py            # Versão, auto-update, suporte e navegador de pastas
│               ├── catalogs.py          # Catálogos CST, cClassTrib, cTribNac, LC 116, Anexo VIII, cIndOp
│               ├── tax.py               # Cálculo e validação de regras IBS/CBS + ISSQN + Federais
│               └── emission.py          # Preview/Emissão de DPS, Cancelamento e Substituição ADN
├── 🎨 frontend/                         # Aplicação Web SPA (independente)
│   ├── Dockerfile                       # Imagem Nginx Alpine do frontend
│   ├── docker-compose.yml               # Compose dedicado do Frontend
│   ├── nginx.conf                       # Configuração Nginx (SPA + proxy reverso para /api)
│   ├── index.html                       # Layout base (sidebar, topbar, modais)
│   ├── css/                             # Estilos modulares (variables, base, layout, components, pages)
│   ├── js/                              # Módulos ES6 (main.js, core/*, pages/*)
│   └── views/                           # Views HTML carregadas dinamicamente (dashboard, clients, invoices, about)
├── 🖥️ ui/                               # Shell Desktop Nativo (Tauri / Rust)
│   ├── dev.sh                           # Inicia servidor Python + janela Tauri em modo dev
│   ├── build_sidecar.sh                 # Empacota o backend como binário sidecar via PyInstaller
│   ├── release.sh                       # Gera pacotes instaláveis (.deb, .AppImage, .msi, .dmg)
│   └── src-tauri/                       # Código Rust e configurações do Tauri
├── 📚 docs/                             # Documentação técnica e especificações
│   ├── arquitetura-e-uso.md             # Manual de arquitetura, banco, fluxos e contratos da API
│   ├── nt008.pdf / nt008.txt            # Especificação técnica de referência
│   └── assets/                          # Imagens e logotipos da documentação
├── 🧪 tests/                            # Suíte de testes automatizados (Pytest)
│   ├── conftest.py
│   ├── test_adn_emission_and_tax.py     # Testes de CRUD fiscal, catálogos, calculadora IBS/CBS e ADN
│   └── test_versioning_and_updates.py   # Testes de versão, healthcheck, update transacional e CI
├── 🛠️ scripts/                          # Scripts de automação e manutenção
│   ├── sync_version.py                  # Sincroniza a versão do pyproject.toml com arquivos estáticos
│   └── release.sh                       # Criação automatizada de tags Git e GitHub Releases
├── 🐳 docker-compose.yml                # Compose raiz (usa `include` para unir database, backend e frontend)
├── ⚙️ .env.example                      # Modelo de variáveis de ambiente
├── 🧩 pyproject.toml                    # Dependências Poetry, configuração do Pytest e Ruff
├── 🐍 server.py                         # Entrypoint auxiliar compatível com o sidecar desktop
├── ▶️ run_web.sh                        # Script rápido para subir o servidor web localmente
└── 🚀 run_ui.sh                         # Script rápido para subir o app desktop Tauri
```

---

## ⚙️ Configuração e Variáveis de Ambiente

Copie o arquivo [`.env.example`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/.env.example) para `.env` na raiz do projeto caso deseje customizar portas ou credenciais:

```bash
cp .env.example .env
```

| Variável | Valor Padrão | Descrição |
| :--- | :--- | :--- |
| `POSTGRES_DB` | `nfse_db` | Nome do banco de dados PostgreSQL |
| `POSTGRES_USER` | `nfse_user` | Usuário do banco PostgreSQL |
| `POSTGRES_PASSWORD` | `nfse_pass` | Senha do banco PostgreSQL |
| `POSTGRES_HOST` | `localhost` (local) / `database` (Docker) | Host do servidor PostgreSQL |
| `POSTGRES_PORT` | `5434` | Porta exposta pelo container PostgreSQL no host |
| `DATABASE_URL` | `postgresql+psycopg2://nfse_user:nfse_pass@localhost:5434/nfse_db` | URI completa de conexão SQLAlchemy |
| `BACKEND_PORT` | `8000` | Porta HTTP exposta pelo container do Backend |
| `FRONTEND_PORT` | `3000` | Porta HTTP exposta pelo container Nginx do Frontend |

---

## 🚀 Como Executar

### Opção 1: Com Docker e Docker Compose (Recomendado)

Cada camada (`database/`, `backend/` e `frontend/`) possui seu próprio `Dockerfile` e `docker-compose.yml`. O arquivo [`docker-compose.yml`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/docker-compose.yml) na raiz utiliza a diretiva `include` para subir todos os serviços integrados na rede `nfse_network`:

```bash
# Subir toda a stack (PostgreSQL + Backend FastAPI + Frontend Nginx)
docker compose up -d --build
```

Se desejar subir ou reiniciar **cada camada individualmente** usando seu próprio compose:

```bash
# 1. Subir apenas o banco de dados PostgreSQL
docker compose -f database/docker-compose.yml up -d --build

# 2. Subir apenas o Backend FastAPI
docker compose -f backend/docker-compose.yml up -d --build

# 3. Subir apenas o Frontend Nginx
docker compose -f frontend/docker-compose.yml up -d --build
```

Acessos após inicializar:
- **Frontend Web (Nginx)**: `http://localhost:3000`
- **Backend API & Frontend integrado**: `http://localhost:8000`
- **Documentação interativa Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **PostgreSQL**: `localhost:5434`

---

### Opção 2: Execução Local com Poetry (Desenvolvimento)

1. Certifique-se de que o banco PostgreSQL está ativo (por exemplo, subindo apenas o compose do banco):
   ```bash
   docker compose -f database/docker-compose.yml up -d
   ```
2. Instale as dependências com o Poetry:
   ```bash
   poetry install --with dev
   ```
3. Inicie a aplicação web com o script [`run_web.sh`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/run_web.sh):
   ```bash
   ./run_web.sh
   ```
   Ou diretamente via Uvicorn:
   ```bash
   poetry run python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
   ```

---

### Opção 3: Aplicativo Desktop Nativo (Tauri)

Para abrir o sistema como aplicativo desktop nativo:

```bash
./run_ui.sh
```

Para gerar o pacote instalável de distribuição (`.deb`, `.AppImage`, `.msi`, `.dmg`), consulte [`ui/README.md`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/ui/README.md) ou execute:

```bash
cd ui && ./release.sh
```

---

## 📡 Referência da API e Exemplos Práticos

### Padrão de Imports Internos (`backend/app`)

Dentro do backend e nos testes, utilize sempre o pacote `app` (com `PYTHONPATH=backend` ou `--app-dir backend`):

```python
from app.main import app
from app.database import get_db, SessionLocal
from app.models import Client, Invoice, init_db
from app.schemas import ClientResponse, SyncRequest, EmitirDpsRequest, TaxCalculationRequest
from app.api.deps import get_nfse_client
from app.api.state import tasks_status
from app.services.adn_service import AdnService
from app.version import VERSION
```

### 1. Clientes (`/api/clients`)

- `GET /api/clients` — Lista todos os clientes cadastrados.
- `POST /api/clients` — Cadastra um cliente (`multipart/form-data`, aceita certificado `.pfx` e parâmetros fiscais ADN).
- `PUT /api/clients/{client_id}` — Atualiza dados cadastrais, fiscais ou certificado do cliente.
- `DELETE /api/clients/{client_id}` — Remove um cliente.

```bash
curl -X POST "http://localhost:8000/api/clients" \
  -F "cnpj=19.495.981/0001-13" \
  -F "razao_social=Minha Empresa Ltda" \
  -F "username=19495981000113" \
  -F "password=senha_portal" \
  -F "inscricao_municipal=123456" \
  -F "codigo_municipio=3201308" \
  -F "uf=ES" \
  -F "regime_tributario=simples" \
  -F "serie_dps_padrao=900" \
  -F "ambiente_padrao=homologacao" \
  -F "cert_password=senha_pfx" \
  -F "cert_file=@meu_certificado.pfx"
```

### 2. Sincronização e Notas (`/api/sync`, `/api/invoices`, `/api/tasks`)

- `POST /api/sync` — Dispara sincronização em background com o portal nacional.
- `GET /api/tasks/{task_id}` — Consulta progresso (`0` a `100%`) e mensagem de uma tarefa em background.
- `GET /api/invoices` — Lista notas sincronizadas/emitidas com filtros (`client_id`, `tipo`, `data_inicio`, `data_fim`).

```bash
curl -X POST "http://localhost:8000/api/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": 1,
    "data_inicio": "01/01/2026",
    "data_fim": "31/05/2026",
    "tipo": "emitidas"
  }'
```

### 3. Downloads e Lotes (`/api/download`)

- `POST /api/download/sync-portal` — Baixa XMLs/PDFs pendentes do portal (ou gera o PDF DANFSE localmente a partir do XML).
- `GET /api/download/file?path=...` — Entrega um XML ou PDF específico (recuperando do portal caso ausente no disco).
- `POST /api/download/batch` — Empacota uma lista de arquivos em um `.zip` em `backend/downloads/temp/`.

### 4. Catálogos Fiscais da Reforma Tributária (`/api/catalogs`)

- `GET /api/catalogs/cst?apenas_nfse=true` — Lista os 18 códigos CST do IBS/CBS.
- `GET /api/catalogs/cclasstrib?cst=200&apenas_anexo_viii=true&q=...` — Filtra os 138 códigos `cClassTrib`.
- `GET /api/catalogs/cclasstrib/{codigo}` — Detalhes e percentuais de redução de um `cClassTrib` (ex.: `200029`).
- `GET /api/catalogs/servicos?item_lc116=01.01&q=sistemas` — Pesquisa os 338 códigos `cTribNac`.
- `GET /api/catalogs/servicos/{c_trib_nac}` — Detalhes de incidência de ISSQN e correlações do serviço.
- `GET /api/catalogs/lc116` — Lista subitens da LC 116/2003 e seus desdobramentos.
- `GET /api/catalogs/correlacoes` — Matriz oficial do Anexo VIII (`LC 116 x NBS x cIndOp x cClassTrib`).
- `GET /api/catalogs/indop` — Lista os 28 indicadores de operação (`cIndOp`).
- `GET /api/catalogs/favoritos` — Presets rápidos de serviços frequentes.

### 5. Calculadora e Validador Tributário (`/api/tax`)

- `POST /api/tax/calculate` — Calcula `ISSQN`, retenções federais (`PIS`, `COFINS`, `IRRF`, `CSLL`, `INSS`) e `IBS/CBS` conforme o ano de competência (`2026`, `2027–2032`, `2033+`).
- `POST /api/tax/validate-ibscbs` — Valida regras de negócio da NT 1.101 (`E0905`, `E0910`, `E0931`, `E0958`, `E0959`, `E0966`, etc.).

```bash
curl -X POST "http://localhost:8000/api/tax/calculate" \
  -H "Content-Type: application/json" \
  -d '{
    "valor_servicos": 10000.00,
    "regime_prestador": "normal",
    "cClassTrib": "200029",
    "cIndOp": "030101",
    "cTribNac": "040101",
    "ano_competencia": 2026,
    "aliquota_iss": 2.0,
    "p_ibs_uf": 0.10,
    "p_ibs_mun": 0.00,
    "p_cbs": 0.90
  }'
```

### 6. Emissão, Cancelamento e Substituição ADN (`/api/adn`)

- `POST /api/adn/dps/preview` — Gera o XML da DPS v1.01 com cálculo tributário integrado e valida contra `DPS_v1.01.xsd`.
- `POST /api/adn/dps/emitir` — Gera, valida XSD, assina com Certificado A1 (`infDPS`), salva em `backend/downloads/adn/dps/` e transmite via mTLS ao ADN.
- `POST /api/adn/nfse/cancelar` — Gera evento `e101101` (`pedRegEvento`), valida XSD, assina (`infPedReg`) e transmite o cancelamento.
- `POST /api/adn/nfse/substituir` — Emite DPS substituta (`<subst>`) e gera o evento `e105102`, atualizando o status da nota original para `substituida`.
- `GET /api/adn/parametros-municipais/{cod_ibge}` — Consulta convênio e alíquotas municipais no ADN.

### 7. Analytics, Relatórios e Sistema (`/api/analytics`, `/api/reports`, `/api/system`)

- `GET /api/analytics/stats` — Totais de notas, clientes, downloads pendentes e valores financeiros.
- `GET /api/analytics/chart?period=30d` — Série temporal de emissões e recebimentos.
- `GET /api/analytics/ranking?period=30d` — Top 5 clientes por volume emitido e recebido.
- `POST /api/analytics/enrich-xml` — Reprocessa XMLs locais para preencher valores e números faltantes.
- `GET /api/reports/export?format=json|csv|xlsx&period=30d` — Exporta relatório financeiro consolidado.
- `GET /api/health` — Healthcheck da aplicação.
- `GET /api/system/version` — Retorna a versão atual definida no `pyproject.toml`.
- `GET /api/system/check-update` — Verifica se há nova release publicada no GitHub.
- `POST /api/system/update/download` & `POST /api/system/update/apply` — Baixa e aplica atualização com backup transacional.

---

## 🗄️ Modelo de Dados (PostgreSQL)

O schema é gerenciado via SQLAlchemy em [`backend/app/models.py`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/backend/app/models.py) e contém duas tabelas principais:

- **`clients`**: armazena `id`, `cnpj` (único), `razao_social`, `username`, `password`, `cert_path` (em `backend/certificados/`), `cert_password`, `description`, `save_path`, `path_structure` e os campos fiscais de emissão ADN (`inscricao_municipal`, `codigo_municipio`, `uf`, `cep`, `logradouro`, `numero`, `complemento`, `bairro`, `telefone`, `email`, `regime_tributario`, `regime_apuracao_sn`, `regime_especial`, `serie_dps_padrao`, `ultimo_numero_dps`, `ambiente_padrao`).
- **`invoices`**: armazena `id`, `client_id` (FK), `data_emissao`, `numero`, `chave` (única), `status`, `tipo` (`emitidas` / `recebidas`), `valor`, `xml_path`, `pdf_path`, `download_url_xml`, `download_url_pdf` e os metadados ADN/IBS/CBS (`id_dps`, `serie_dps`, `numero_dps`, `chave_substituida`, `chave_substituta`, `motivo_cancelamento`, `data_cancelamento`, `xml_dps_path`, `xml_evento_path`, `valor_iss`, `valor_ibs`, `valor_cbs`, `valor_liquido`, `c_trib_nac`, `c_nbs`, `c_class_trib`, `cst_ibscbs`).

---

## 🧪 Testes, Qualidade e CI/CD

### Executando Testes e Linter

```bash
# Executar toda a suíte de testes automatizados (Pytest)
poetry run pytest -v

# Verificar formatação e lint (Ruff)
poetry run ruff check backend tests
```

### Versionamento e Releases

A versão oficial do sistema é centralizada no [`pyproject.toml`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/pyproject.toml) (`project.version`) e lida dinamicamente por [`backend/app/version.py`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/backend/app/version.py):

```bash
# Sincronizar versão com arquivos estáticos (se necessário)
poetry run python scripts/sync_version.py

# Criar tag vX.Y.Z e publicar release no GitHub localmente
./scripts/release.sh
```

No GitHub Actions, o workflow [`.github/workflows/auto-release.yml`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/.github/workflows/auto-release.yml) sobe um serviço `postgres:16-alpine`, executa `ruff` e `pytest`, lê `app.version.VERSION` e publica automaticamente a tag e a release quando um Pull Request com a label `release` é mesclado.

---

## 📚 Documentação Técnica Detalhada

Consulte também na pasta [`docs/`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/docs):

- **[`docs/arquitetura-e-uso.md`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/docs/arquitetura-e-uso.md)**: detalhamento profundo da arquitetura, fluxos de sequência, regras de cálculo da Reforma Tributária (NT 1.101), estrutura dos containers Docker e guia de extensão de novos routers.
- **[`ui/README.md`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/ui/README.md)**: guia específico do empacotamento desktop com Tauri e PyInstaller.
- **[`docs/nt008.pdf`](file:///home/cleiton/PyJobs/MeusProjetos/nfse_manager/docs/nt008.pdf)**: Nota Técnica de referência da NFS-e Nacional.

---

## 👤 Autor

**Cleiton Leonel Creton** — [cleiton.leonel@gmail.com](mailto:cleiton.leonel@gmail.com)

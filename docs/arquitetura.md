# 🏗️ Visão de Arquitetura

O **NFSe Manager Pro** adota uma arquitetura modular que separa claramente a camada de banco de dados (`database/`), a camada de backend e regras fiscais (`backend/app/`), o frontend web estático (`frontend/`) e o empacotamento desktop (`ui/`).

---

## 1. Diagrama de Camadas e Containers

```mermaid
flowchart LR
    subgraph Presentation["Apresentação"]
        SPA["Frontend SPA<br/>(frontend/ - Nginx :3000)"]
        Desktop["Desktop App<br/>(ui/ - Tauri Rust)"]
    end

    subgraph AppLayer["Backend FastAPI (backend/app/)"]
        Main["app.main:app (:8000)"]
        Routers["api/routers/*<br/>(12 domínios REST)"]
        AdnService["services/adn_service.py"]
        Deps["api/deps.py"]
    end

    subgraph Storage["Persistência & Arquivos"]
        PG[("PostgreSQL 16<br/>(database/ :5434)")]
        Certs["backend/certificados/<br/>(Arquivos .pfx)"]
        Downloads["backend/downloads/<br/>(XMLs, PDFs, ZIPs, ADN)"]
    end

    subgraph External["Serviços Governamentais"]
        ADN["ADN / Sefin Nacional<br/>(API mTLS v1.01)"]
        Portal["Portal Nacional NFS-e"]
    end

    Desktop --> SPA
    SPA -->|fetch /api/*| Main
    Main --> Routers
    Routers --> PG
    Routers --> Certs
    Routers --> Downloads
    Routers --> AdnService
    Routers --> Deps
    AdnService -->|pynfse.adn (mTLS)| ADN
    Deps -->|ClienteNfseNacional| Portal
```

---

## 2. Estrutura do Repositório

```text
nfse_manager/
├── database/                  # Container PostgreSQL 16 Alpine
│   ├── Dockerfile
│   └── docker-compose.yml
├── backend/                   # Raiz do Backend
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── certificados/          # Certificados A1 (.pfx) dos clientes
│   ├── downloads/             # XMLs, PDFs, lotes ZIP e artefatos ADN
│   └── app/                   # Pacote Python principal (app)
│       ├── main.py            # Inicialização FastAPI, CORS, /api/health e static files
│       ├── database.py        # Engine SQLAlchemy (PostgreSQL) e get_db()
│       ├── models.py          # Entidades Client e Invoice + init_db()
│       ├── schemas.py         # Schemas Pydantic v2
│       ├── version.py         # Leitura centralizada da versão no pyproject.toml
│       ├── core/
│       │   └── security.py    # Criptografia simétrica em repouso (AES/Fernet)
│       ├── services/
│       │   └── adn_service.py # Orquestração ADN / Sefin Nacional v1.01
│       └── api/
│           ├── deps.py        # Instanciação de ClienteNfseNacional
│           ├── state.py       # Estado de tarefas em background (tasks_status)
│       │   └── routers/       # 12 routers modulares
├── frontend/                  # SPA Vanilla ES6 + Nginx
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── nginx.conf
│   ├── index.html
│   ├── css/
│   ├── js/
│   └── views/
├── ui/                        # Aplicativo Desktop Tauri (Rust)
├── docs/                      # Documentação MkDocs
├── tests/                     # Testes automatizados Pytest
├── scripts/                   # Scripts de versão e release
├── mkdocs.yml                 # Configuração do MkDocs Material (GitHub Pages)
├── docker-compose.yml         # Orquestrador global (include)
└── pyproject.toml             # Dependências Poetry, Pytest e Ruff
```

---

## 3. Responsabilidade dos Routers (`backend/app/api/routers/`)

| Router | Prefixo | Descrição |
| :--- | :--- | :--- |
| `auth.py` | `/api/auth` | Autenticação JWT (`HS256`) de operadores, cadastro público com bootstrap do 1º admin (`/register`), perfil (`/me`), troca de senha e gestão de usuários. |
| `clients.py` | `/api/clients` | CRUD de clientes, SMTP próprio, upload de certificado `.pfx` (com inspeção de validade X.509 e `/certificados/alertas`) e parâmetros fiscais ADN. |
| `registry.py` | `/api/customers`, `/api/service-items`, `/api/lookup` | CRUD de Tomadores e Serviços Recorrentes (com autocompletar pelo Anexo VIII) e consulta automática de CNPJ/CEP com código IBGE. |
| `invoices.py` | `/api/sync`, `/api/invoices`, `/api/tasks` | Sincronização em background com o portal nacional, consulta de progresso e listagem filtrada de notas. |
| `downloads.py` | `/api/download` | Download de XML/PDF do portal, conversão de HTML em XML/PDF e criação de lotes `.zip` em `backend/downloads/temp/`. |
| `analytics.py` | `/api/analytics` | Estatísticas do dashboard (incluindo alertas de certificados), gráfico temporal, ranking de clientes e enriquecimento de notas via XML. |
| `reports.py` | `/api/reports` | Exportação de relatórios financeiros em `JSON`, `CSV` e `XLSX`. |
| `catalogs.py` | `/api/catalogs` | Consulta aos catálogos oficiais (`CST`, `cClassTrib`, `cTribNac`, `LC 116`, `Anexo VIII`, `cIndOp`, `favoritos`). |
| `tax.py` | `/api/tax` | Cálculo tributário completo (`ISSQN` + Federais + `IBS/CBS`) e validação de regras da `NT 1.101`. |
| `emission.py` | `/api/adn` | Preview/emissão de DPS, Fila de Contingência Offline, Worker em Background (`/worker/*`), envio de XML/PDF por e-mail, Cofre ADN por NSU, cancelamento (`e101101`) e substituição (`e105102`). |
| `batch.py` | `/api/batch-emission` | Importação CSV/XLSX de lotes de notas, validação em 3 níveis, correção inline (`PATCH`), processamento resiliente com estado `UNKNOWN`, exclusão sincronizada com a fila e exportação. |
| `system.py` | `/api/system`, `/api/support` | Versão atual, verificação/download/aplicação de updates via GitHub Releases, suporte e navegação de pastas. |

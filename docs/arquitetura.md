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
        Routers["api/routers/*<br/>(9 domínios REST)"]
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
│       ├── services/
│       │   └── adn_service.py # Orquestração ADN / Sefin Nacional v1.01
│       └── api/
│           ├── deps.py        # Instanciação de ClienteNfseNacional
│           ├── state.py       # Estado de tarefas em background (tasks_status)
│           └── routers/       # 9 routers modulares
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
| `clients.py` | `/api/clients` | CRUD de clientes, upload de certificado `.pfx` para `backend/certificados/` e parâmetros fiscais ADN. |
| `invoices.py` | `/api/sync`, `/api/invoices`, `/api/tasks` | Sincronização em background com o portal nacional, consulta de progresso e listagem filtrada de notas. |
| `downloads.py` | `/api/download` | Download de XML/PDF do portal, geração local de PDF DANFSE a partir do XML e criação de lotes `.zip` em `backend/downloads/temp/`. |
| `analytics.py` | `/api/analytics` | Estatísticas do dashboard, gráfico temporal, ranking de clientes e enriquecimento de notas via XML. |
| `reports.py` | `/api/reports` | Exportação de relatórios financeiros em `JSON`, `CSV` e `XLSX`. |
| `catalogs.py` | `/api/catalogs` | Consulta aos catálogos oficiais (`CST`, `cClassTrib`, `cTribNac`, `LC 116`, `Anexo VIII`, `cIndOp`, `favoritos`). |
| `tax.py` | `/api/tax` | Cálculo tributário completo (`ISSQN` + Federais + `IBS/CBS`) e validação de regras da `NT 1.101`. |
| `emission.py` | `/api/adn` | Preview de DPS, emissão assinada mTLS, cancelamento (`e101101`), substituição (`e105102`) e parâmetros municipais. |
| `system.py` | `/api/system`, `/api/support` | Versão atual, verificação/download/aplicação de updates via GitHub Releases, suporte e navegação de pastas. |

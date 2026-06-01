# 🚀 NFSe Manager

<p align="center">
  <a href="https://github.com/cleitonleonel/nfse_manager">
    <img src="docs/assets/nfse_manager.png" alt="nfse_manager logo" width="45%" height="auto">
  </a>
</p>

<p align="center">
  <i>Aplicação para gerenciamento de NFSe com backend FastAPI, frontend web estático e empacotamento desktop com Tauri.
</i>
</p>


## Sobre
O projeto armazena clientes e notas em um banco SQLite local, sincroniza dados com o portal de NFSe, baixa XML/PDF, gera relatórios e exibe indicadores no dashboard.

![1.jpeg](docs/assets/1.jpeg)
![2.jpeg](docs/assets/2.jpeg)


## Visão geral

- **Web app** servido pelo próprio FastAPI em `backend/main.py`.
- **Frontend SPA** em `frontend/`, com páginas carregadas dinamicamente.
- **Desktop app** em `ui/`, usando Tauri como shell nativo.
- **Banco local**: `nfse.db`.

## O que o sistema faz

- Cadastro, edição e remoção de clientes.
- Sincronização de notas emitidas e recebidas por período.
- Download de XML e PDF.
- Recuperação de arquivos ausentes usando as URLs salvas no banco.
- Exportação de relatórios em JSON, CSV e XLSX.
- Dashboard com estatísticas, gráfico temporal e ranking.
- Verificação de atualização do sistema via GitHub Releases.
- Navegação de pastas para seleção de diretórios de saída.

## Tecnologias usadas

- Python 3.12+
- FastAPI
- SQLAlchemy
- SQLite
- Pydantic
- Uvicorn
- OpenPyXL
- HTTPX
- Frontend em HTML/CSS/JavaScript puro
- Tauri para desktop

## 🧱 Estrutura principal

```text
nfse_manager/
├── 📁 backend/                # API, modelos, schemas e rotas
├── 🎨 frontend/               # UI web servida pelo FastAPI
├── 🖥️ ui/                     # Shell desktop com Tauri
├── 📚 docs/                   # Documentação do projeto
├── 🗃️ nfse.db                 # Banco SQLite local
├── 🧩 pyproject.toml          # Dependências e configuração do Poetry
├── ▶️ run_web.sh              # Inicializa a versão web
└── 🚀 run_ui.sh               # Inicializa a versão desktop
```

## Documentação técnica

Leia também:

- `docs/arquitetura-e-uso.md`

## Exemplos práticos de uso

Os exemplos abaixo foram condensados do `USAGE_EXAMPLES.md` para facilitar o uso direto pelo `README`.

### Iniciando a aplicação

#### Opção recomendada: Uvicorn

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Via Python

```python
import uvicorn
from backend.main import app

if __name__ == "__main__":
	uvicorn.run(app, host="0.0.0.0", port=8000)
```

#### Execução direta

```bash
python -c "from backend.main import app; import uvicorn; uvicorn.run(app, port=8000)"
```

### Importações corretas

Use sempre os caminhos do pacote `backend`:

```python
from backend.models import Client, Invoice
from backend.schemas import ClientResponse, SyncRequest, DashboardStats
from backend.database import get_db, SessionLocal
from backend.main import app
from backend.api.deps import get_nfse_client
from backend.api.state import tasks_status
```

### Criar cliente

```bash
curl -X POST "http://localhost:8000/api/clients" \
  -F "cnpj=19.495.981/0001-13" \
  -F "razao_social=Minha Empresa" \
  -F "username=usuario" \
  -F "password=senha123" \
  -F "description=Cliente de teste"
```

Com certificado:

```bash
curl -X POST "http://localhost:8000/api/clients" \
  -F "cnpj=19.495.981/0001-13" \
  -F "razao_social=Minha Empresa" \
  -F "username=usuario" \
  -F "password=senha123" \
  -F "cert_file=@certificado.pfx"
```

### Listar clientes

```bash
curl "http://localhost:8000/api/clients"
```

### Iniciar sincronização

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

### Consultar status da tarefa

```bash
curl "http://localhost:8000/api/tasks/{task_id}"
```

### Consultar estatísticas

```bash
curl "http://localhost:8000/api/analytics/stats?client_id=1"
```

### Exportar relatório

```bash
# JSON
curl "http://localhost:8000/api/reports/export?format=json&period=30d" > relatorio.json

# CSV
curl "http://localhost:8000/api/reports/export?format=csv&period=30d" > relatorio.csv

# XLSX
curl "http://localhost:8000/api/reports/export?format=xlsx&period=30d" > relatorio.xlsx
```

### Acessar a documentação automática

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Desenvolvendo novos routers

Para adicionar um novo domínio de negócio:

1. criar o arquivo em `backend/api/routers/`;
2. declarar um `APIRouter` com prefixo próprio;
3. importar e registrar o router em `backend/main.py`.

Exemplo mínimo:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db

router = APIRouter(prefix="/api/novo_dominio", tags=["novo_dominio"])


@router.get("/rota-1")
def exemplo(db: Session = Depends(get_db)):
	return {"status": "ok"}
```

## Testando tudo

```bash
python -c "from backend.main import app; print('✓ OK')"
curl "http://localhost:8000/openapi.json" | python -m json.tool
pytest tests/ -v
```

## Instalação

### Com Poetry

```bash
poetry install --with dev
```

### Observação

O projeto não usa `requirements.txt`; a referência oficial de dependências é o `pyproject.toml`.

## Como executar

### Modo web

```bash
chmod +x run_web.sh
./run_web.sh
```

Ou, manualmente:

```bash
poetry run python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

A aplicação ficará disponível em:

- `http://localhost:8000`
- documentação automática da API em `http://localhost:8000/docs`
- alternativa em `http://localhost:8000/redoc`

### Modo desktop

```bash
chmod +x run_ui.sh
./run_ui.sh
```

O script entra na pasta `ui/` e chama o fluxo de desenvolvimento do Tauri.

## Backend

O backend principal está em `backend/main.py` e:

1. inicializa o banco com `init_db()`;
2. registra os routers da API;
3. monta a pasta `frontend/` na raiz da aplicação;
4. aplica CORS liberado para facilitar o uso local.

### Routers disponíveis

- `backend/api/routers/clients.py` — CRUD de clientes.
- `backend/api/routers/invoices.py` — Sincronização e listagem de faturas (invoices).
- `backend/api/routers/downloads.py` — Download de arquivos e lote ZIP.
- `backend/api/routers/analytics.py` — Estatísticas e gráficos.
- `backend/api/routers/reports.py` — Exportação de relatórios.
- `backend/api/routers/system.py` — Suporte, update check e navegação de pastas.

## Principais endpoints

### Clientes

- `GET /api/clients`
- `POST /api/clients`
- `PUT /api/clients/{client_id}`
- `DELETE /api/clients/{client_id}`

### Notas e sincronização

- `POST /api/sync`
- `GET /api/tasks/{task_id}`
- `GET /api/invoices`

### Downloads

- `POST /api/download/sync-portal`
- `GET /api/download/file?path=...`
- `POST /api/download/batch`

### Analytics

- `GET /api/analytics/stats`
- `GET /api/analytics/chart`
- `POST /api/analytics/enrich-xml`
- `GET /api/analytics/ranking`

### Relatórios

- `GET /api/reports/export?format=json|csv|xlsx`

### Sistema e suporte

- `POST /api/support/message`
- `GET /api/system/check-update`
- `GET /api/system/list-folders`

## Modelo de dados

### `clients`

Guarda credenciais e configuração de cada cliente:

- CNPJ
- razão social
- usuário/senha do portal
- certificado A1 opcional
- caminho base de salvamento
- estrutura personalizada de diretórios

### `invoices`

Guarda as notas sincronizadas:

- identificador interno
- cliente vinculado
- chave da nota
- número
- status
- tipo (`emitidas` / `recebidas`)
- valor
- caminhos do XML e PDF
- URLs de download do portal

## Fluxo de uso sugerido

1. Abrir a aplicação web ou desktop.
2. Cadastrar um cliente na área de clientes.
3. Sincronizar notas por período.
4. Baixar XML/PDF quando necessário.
5. Gerar relatórios ou acompanhar o dashboard.

## Configurações importantes

- Datas de filtro e sincronização usam o formato `DD/MM/AAAA`.
- O progresso das tarefas é guardado em memória; reiniciar o processo limpa o status.
- O sistema depende da estrutura atual do portal de NFSe; mudanças no HTML podem exigir ajustes.
- Os arquivos baixados seguem a estrutura configurada por cliente.

## Troubleshooting rápido

- `ModuleNotFoundError: No module named 'backend'`: execute os comandos a partir da raiz do projeto.
- Porta já em uso: altere a porta no comando do Uvicorn.
- Banco não encontrado: o arquivo `nfse.db` é criado automaticamente ao inicializar a aplicação.
- Se estiver importando módulos antigos, troque por `backend.models`, `backend.schemas` e `backend.database`.

## 🛠️ Scripts úteis

```bash
./run_web.sh   # sobe a API + frontend
./run_ui.sh    # inicia o desktop Tauri
```

## 🔖 Versionamento e releases

Este projeto centraliza a versão no `pyproject.toml` (campo `project.version`). Para manter tudo sincronizado e facilitar releases, seguem ferramentas e recomendações:

- Fonte única de verdade: edite a versão em `pyproject.toml` (ex.: `version = "0.2.0"`).
- O backend expõe essa versão via `backend.version.VERSION` e existe um endpoint leve `/api/system/version` que retorna `{ "current_version": "X.Y.Z" }`.
- A página **Sobre** carrega a versão dinamicamente e o botão de update não abre mais o GitHub: ele baixa o ZIP da release em background, extrai em `release/staging/` e só depois libera a aplicação.
- Para atualizar automaticamente trechos estáticos (ex.: `frontend/views/about.html`) execute:

```bash
python3 scripts/sync_version.py
```

- Para criar a tag Git e a release no GitHub localmente execute (após merge e com a árvore limpa):
- Para criar a tag Git e a release no GitHub localmente execute (após merge e com a árvore limpa):

```bash
chmod +x scripts/release.sh
./scripts/release.sh
```

- Critério de "estável": por convenção aqui consideramos estável uma versão sem sufixo de pre-release. Ex.: `1.2.3` é estável, `1.3.0-alpha` e `2.0.0-rc.1` são pré-releases e não gerarão automaticamente a release.

### Automação com GitHub Actions

Existe um workflow (`.github/workflows/auto-release.yml`) que é disparado quando uma PR para `main` é encerrada com merge **e** recebe a label `release`. O comportamento padrão do workflow:

- Executa testes (se existirem) e tenta criar uma tag `vX.Y.Z` e uma release no GitHub;
- Só cria release automática se a versão não contiver sufixos `-` ou `+` (pré-release);
- Só roda quando a PR estiver mesclada e marcada com a label `release`;
- Se preferir releases manuais, desabilite o workflow ou ajuste as condições.

Recomendações de processo:

1. Atualize a versão em `pyproject.toml` (use `poetry version patch/minor/major` se utilizar Poetry).
2. Abra PR para `main`. Aguarde a execução do CI (testes/lint).
3. Depois do merge, o workflow de `auto-release` pode criar a tag e a release automaticamente.

Se quiser que eu adapte o workflow para um fluxo diferente (por exemplo: apenas criar release quando uma PR tiver uma label `release` ou quando um arquivo `RELEASE.md` for modificado), posso ajustar isso.

## ⚡ Referência rápida da estrutura do backend

```text
backend/
├── 🚪 main.py               # inicia a API e serve o frontend
├── 🗄️ database.py           # engine, sessão e get_db()
├── 🧱 models.py              # Client, Invoice e init_db()
├── 🧾 schemas.py             # modelos Pydantic
└── api/
    ├── 🔌 deps.py            # cliente NFSe a partir do banco
    ├── 🧠 state.py           # status de tarefas em memória
    └── routers/
        ├── 👥 clients.py
        ├── 📝 invoices.py
        ├── ⬇️ downloads.py
        ├── 📊 analytics.py
        ├── 📤 reports.py
        └── ⚙️ system.py
```

### 📌 Resumo rápido

| Área | Arquivo | Função |
|------|---------|--------|
| API principal | `backend/main.py` | Sobe o FastAPI e monta o frontend |
| Banco | `backend/database.py` | Conexão SQLite e sessão SQLAlchemy |
| Modelos | `backend/models.py` | Tabelas `Client` e `Invoice` |
| Schemas | `backend/schemas.py` | Validação de dados |
| Clientes | `backend/api/routers/clients.py` | CRUD de clientes |
| Invoices | `backend/api/routers/invoices.py` | Sincronização e listagem |
| Downloads | `backend/api/routers/downloads.py` | Baixa arquivos e gera ZIP |
| Analytics | `backend/api/routers/analytics.py` | Estatísticas e ranking |
| Relatórios | `backend/api/routers/reports.py` | Exportação JSON/CSV/XLSX |
| Sistema | `backend/api/routers/system.py` | Update, suporte e pastas |

## Contribuição

Contribuições, melhorias e correções são bem-vindas.

## Autor

Cleiton Leonel Creton — cleiton.leonel@gmail.com

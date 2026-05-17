# NFSe Manager — documentação técnica

## 1. Visão geral

O `nfse_manager` é uma aplicação para gerenciamento de NFSe com três camadas principais:

- **Backend FastAPI** para CRUD, sincronização, downloads, relatórios e estatísticas.
- **Frontend estático** em `frontend/`, servido pelo próprio backend.
- **Desktop Tauri** em `ui/`, que empacota a aplicação web em uma janela nativa.

A aplicação usa um banco SQLite local (`nfse.db`) e mantém os dados de clientes, notas e caminhos de arquivos baixados.

## 2. Arquitetura

```text
┌──────────────────────────────────────────────┐
│ Frontend estático                             │
│ - HTML/CSS/JS em /frontend                    │
│ - Views carregadas sob demanda                │
└──────────────────────────────────────────────┘
                     ▲
                     │ fetch /api/*
                     ▼
┌──────────────────────────────────────────────┐
│ Backend FastAPI                               │
│ - backend/main.py                             │
│ - routers em backend/api/routers              │
│ - estado efêmero de tarefas em memória        │
└──────────────────────────────────────────────┘
                     ▲
                     │ SQLAlchemy
                     ▼
┌──────────────────────────────────────────────┐
│ SQLite local                                  │
│ - nfse.db                                     │
│ - tabelas clients e notes                     │
└──────────────────────────────────────────────┘
```

## 3. Componentes principais

### Backend

- `backend/main.py`
  - inicializa a aplicação FastAPI;
  - carrega o banco com `init_db()`;
  - registra os routers por domínio;
  - monta a pasta `frontend/` na raiz da aplicação.

- `backend/models.py`
  - define os modelos SQLAlchemy `Client` e `Note`;
  - executa pequenas migrações de compatibilidade no SQLite.

- `backend/schemas.py`
  - declara os schemas Pydantic usados nas rotas.

- `backend/api/deps.py`
  - cria o cliente `ClienteNfseNacional` com base nas credenciais salvas.

- `backend/api/state.py`
  - mantém o status das tarefas em background em memória.

### Routers

- `clients.py`: CRUD de clientes.
- `notes.py`: sincronização e listagem de notas.
- `downloads.py`: download, recuperação e empacotamento de arquivos.
- `analytics.py`: estatísticas, gráfico, ranking e enriquecimento via XML.
- `reports.py`: exportação de relatórios em JSON, CSV e XLSX.
- `system.py`: suporte, verificação de versão e navegação de pastas.

### Frontend

O frontend é uma SPA leve, composta por:

- `frontend/index.html`: layout base, sidebar, modal e áreas globais.
- `frontend/js/main.js`: inicialização da aplicação.
- `frontend/js/core/`: API, estado, roteamento e utilitários de UI.
- `frontend/js/pages/`: lógica específica de cada página.
- `frontend/views/`: fragmentos HTML carregados dinamicamente.

### Desktop

A pasta `ui/` contém o shell Tauri para distribuir a aplicação como app desktop.

- Em modo desenvolvimento, o app aponta para o servidor Python local.
- No build, o backend pode ser empacotado como sidecar para distribuição.

## 4. Modelo de dados

### `clients`

Campos principais:

- `id`
- `cnpj`
- `razao_social`
- `username`
- `password`
- `cert_path`
- `cert_password`
- `description`
- `save_path`
- `path_structure`

### `notes`

Campos principais:

- `id`
- `client_id`
- `data_emissao`
- `numero`
- `chave`
- `status`
- `tipo` (`emitidas` ou `recebidas`)
- `valor`
- `xml_path`
- `pdf_path`
- `download_url_xml`
- `download_url_pdf`

## 5. Principais fluxos

### Cadastro de cliente

1. Usuário envia dados do cliente.
2. O backend salva os dados e, se houver, armazena o certificado em `certificados/`.
3. O cliente fica disponível para sincronização e downloads.

### Sincronização de notas

1. O frontend chama `/api/sync`.
2. O backend executa a tarefa em background.
3. Cada cliente é autenticado via `ClienteNfseNacional`.
4. As notas retornadas são persistidas no SQLite.
5. O progresso é publicado em `tasks_status`.

### Download de arquivos

1. O frontend solicita `/api/download/file` ou `/api/download/batch`.
2. O backend tenta localizar o arquivo no disco.
3. Se o arquivo não existir, ele pode ser recuperado pelo portal usando as URLs salvas na nota.
4. O arquivo é entregue ao navegador ou incluído em um ZIP temporário.

### Analytics e relatórios

- Estatísticas consolidadas: `/api/analytics/stats`
- Série temporal: `/api/analytics/chart`
- Ranking: `/api/analytics/ranking`
- Exportação: `/api/reports/export`

## 6. Endpoints relevantes

### Clientes

- `GET /api/clients`
- `POST /api/clients`
- `PUT /api/clients/{client_id}`
- `DELETE /api/clients/{client_id}`

### Notas e sincronização

- `POST /api/sync`
- `GET /api/tasks/{task_id}`
- `GET /api/notes`

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

## 7. Execução local

### Web

```bash
poetry install --with dev
./run_web.sh
```

O backend sobe em `http://localhost:8000`.

### Desktop

```bash
cd ui
npm install
./dev.sh
```

O shell Tauri usa o backend local em desenvolvimento.

## 8. Observações importantes

- O banco usado é o SQLite local `nfse.db`.
- O estado de tarefas em background é **em memória** e se perde ao reiniciar o processo.
- A integração com o portal depende da estrutura atual do site do governo.
- As datas usadas em filtros e sincronização seguem o formato `DD/MM/AAAA`.
- A interface web usa componentes carregados dinamicamente, então uma atualização do backend pode exigir refresh do navegador.

## 9. Estrutura resumida do repositório

```text
nfse_manager/
├── backend/
├── frontend/
├── ui/
├── nfse.db
├── poetry.lock
├── pyproject.toml
├── run_web.sh
└── run_ui.sh
```

## 10. Próximos passos sugeridos

- Criar testes automatizados para rotas críticas.
- Separar segredos e credenciais em um gerenciador de ambiente mais robusto.
- Evoluir as migrações do banco para algo mais formal.
- Documentar o contrato dos endpoints com exemplos de request/response.


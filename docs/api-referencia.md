# 📡 Referência da API REST

O backend FastAPI expõe todos os endpoints sob o prefixo `/api` (além da documentação interativa em `/docs` e `/redoc`).

---

## 1. Saúde, Autenticação JWT e Sistema (`/api/health`, `/api/auth`, `/api/system`, `/api/support`)

> 🔒 **Proteção JWT**: exceto `/api/health`, `/api/auth/status`, `/api/auth/login` e `/api/auth/register`, todos os demais endpoints da API exigem `Authorization: Bearer <token>`.

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Healthcheck leve (`{"status": "ok", "version": "..."}`) |
| `GET` | `/api/auth/status` | Indica se existem operadores cadastrados e se auto-cadastro público está habilitado (`{"has_users": bool, "total_users": int, "allow_self_register": bool}`) |
| `POST` | `/api/auth/register` | Cadastra novo operador e retorna token JWT Bearer (o 1º usuário criado recebe `role == "admin"`, demais `"operador"`; respeita `NFSE_ALLOW_PUBLIC_REGISTER=0` após o bootstrap) |
| `POST` | `/api/auth/login` | Autentica um operador por `username` ou `email` e retorna token JWT Bearer |
| `GET` | `/api/auth/me` | Retorna os dados do operador autenticado pelo cabeçalho `Authorization: Bearer <token>` |
| `POST` | `/api/auth/change-password` | Altera a senha do operador autenticado |
| `GET` | `/api/auth/users` | Lista todos os operadores cadastrados com seus respectivos `client_ids` vinculados (restrito a `role == "admin"`) |
| `POST` | `/api/auth/users` | Cadastra novo operador aceitando lista opcional de `client_ids` autorizados (restrito a `role == "admin"`) |
| `PATCH` | `/api/auth/users/{user_id}` | Atualiza dados, papel (`admin` \| `operador`), status ativo, `client_ids` vinculados ou senha de um operador (restrito a `role == "admin"`, protegendo contra auto-bloqueio/remoção do último admin) |
| `DELETE` | `/api/auth/users/{user_id}` | Remove um operador pelo ID (restrito a `role == "admin"`) |
| `GET` | `/api/system/version` | Retorna a versão atual lida do `pyproject.toml` |
| `GET` | `/api/system/environment` | Retorna diagnóstico de implantação (dialeto do banco, modo servidor/local, diretórios configurados, status do worker e prontidão multiusuário) |
| `GET` | `/api/system/check-update` | Consulta a última release no GitHub e compara com a versão local |
| `POST` | `/api/system/update/download` | Baixa o pacote ZIP da release em background para `release/staging/` (restrito a `role == "admin"`, bloqueado se `NFSE_DISABLE_SELF_UPDATE=1`) |
| `POST` | `/api/system/update/apply` | Aplica os arquivos de `release/staging/` com backup transacional e reinicia (restrito a `role == "admin"`) |
| `GET` | `/api/system/list-folders` | Lista subdiretórios do servidor para seleção visual de pastas (restrito a `role == "admin"`) |
| `POST` | `/api/support/message` | Encaminha mensagem de suporte via E-mail (`DEFAULT_SMTP_*` / `SUPPORT_EMAIL_TO`) e Telegram Bot (`SUPPORT_TELEGRAM_BOT_TOKEN` / `SUPPORT_TELEGRAM_CHAT_ID`) |

---

## 2. Clientes e Monitoramento de Certificados A1 (`/api/clients`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/clients` | Lista as empresas acessíveis ao usuário autenticado (`admin` vê todas; `operador` vê apenas as vinculadas em `user_clients`) |
| `GET` | `/api/clients/certificados/alertas` | Lista certificados A1 vencidos ($\le 0$ dias), expirando ($\le$ `dias_aviso`, padrão `30`) e válidos das empresas acessíveis |
| `POST` | `/api/clients` | Cria novo cliente via `multipart/form-data` (quando criado por não-admin, vincula automaticamente o criador como `manager`; respeita `NFSE_ALLOW_OPERATOR_CREATE_CLIENT`) |
| `PUT` | `/api/clients/{client_id}` | Atualiza dados cadastrais, fiscais ou certificado do cliente (validando acesso do usuário ao `client_id`) |
| `DELETE` | `/api/clients/{client_id}` | Remove um cliente pelo ID (restrito a `admin` ou ao gestor `manager` que criou a empresa) |

### Exemplo: Criar Cliente com Certificado e Parâmetros Fiscais ADN

```bash
curl -X POST "http://localhost:8000/api/clients" \
  -F "cnpj=19.495.981/0001-13" \
  -F "razao_social=Empresa Exemplo Ltda" \
  -F "username=19495981000113" \
  -F "password=minhasenha" \
  -F "cert_password=senhapfx" \
  -F "inscricao_municipal=123456" \
  -F "codigo_municipio=3201308" \
  -F "uf=ES" \
  -F "regime_tributario=simples" \
  -F "serie_dps_padrao=900" \
  -F "ambiente_padrao=homologacao" \
  -F "cert_file=@certificado.pfx"
```

---

## 3. Notas Fiscais e Sincronização (`/api/sync`, `/api/invoices`, `/api/tasks`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/sync` | Inicia tarefa em background para sincronizar notas `emitidas` ou `recebidas` |
| `GET` | `/api/tasks/{task_id}` | Retorna `{status, message, progress}` da tarefa em background |
| `GET` | `/api/invoices` | Lista notas com filtros opcionais (`client_id`, `tipo`, `data_inicio`, `data_fim`) |

```json title="POST /api/sync — Exemplo de Payload"
{
  "client_id": 1,
  "data_inicio": "01/01/2026",
  "data_fim": "31/05/2026",
  "tipo": "emitidas"
}
```

---

## 4. Downloads e Geração de PDF Local (`/api/download`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/download/sync-portal` | Baixa XMLs/PDFs em background para `backend/downloads/` (gera DANFSE local se necessário) |
| `GET` | `/api/download/file?path=...` | Baixa um arquivo individual (recuperando-o automaticamente se ausente) |
| `POST` | `/api/download/batch` | Cria um arquivo `.zip` com os caminhos solicitados em `{"arquivos": [...]}` |

---

## 5. Catálogos Fiscais (`/api/catalogs`)

| Método | Rota | Parâmetros de Query |
| :--- | :--- | :--- |
| `GET` | `/api/catalogs/cst` | `apenas_nfse` (`bool`) |
| `GET` | `/api/catalogs/cclasstrib` | `cst`, `apenas_nfse`, `apenas_anexo_viii`, `q` |
| `GET` | `/api/catalogs/cclasstrib/{codigo}` | — |
| `GET` | `/api/catalogs/servicos` | `item_lc116`, `q`, `limite` |
| `GET` | `/api/catalogs/servicos/{c_trib_nac}` | — |
| `GET` | `/api/catalogs/lc116` | — |
| `GET` | `/api/catalogs/correlacoes` | `q`, `item_lc116`, `c_trib_nac`, `c_nbs`, `c_class_trib`, `indop`, `limite` |
| `GET` | `/api/catalogs/nbs` | `q`, `item_lc116`, `apenas_anexo_viii`, `limite` (lista oficial completa com 920+ NBS) |
| `GET` | `/api/catalogs/nbs/{c_nbs}/combinacoes` | `c_trib_nac` (retorna `cClassTrib` e `cIndOp` compatíveis no Anexo VIII ou Regra Geral) |
| `GET` | `/api/catalogs/indop` | — |
| `GET` | `/api/catalogs/favoritos` | — |
| `GET` | `/api/catalogs/status` | `check_remote` (`bool` para checar versão vigente na RFB e `gov.br/nfse`) |
| `POST` | `/api/catalogs/sync` | `force`, `validar_calculadora` (**Admin** — sincroniza tabelas oficiais no `NFSE_CATALOGS_DIR`) |

---

## 6. Cálculo e Validação Tributária (`/api/tax`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/tax/calculate` | Calcula `ISSQN`, retenções federais e `IBS/CBS` |
| `POST` | `/api/tax/validate-ibscbs` | Valida compatibilidade entre `CST`, `cClassTrib`, `cIndOp`, `cTribNac` e grupos especiais |

---

## 7. Emissão, Fila de Contingência, E-mail, Cofre ADN e Eventos (`/api/adn`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/adn/dps/preview` | Gera XML da DPS v1.01, calcula tributos e valida XSD sem transmitir |
| `POST` | `/api/adn/dps/emitir` | Gera, valida XSD, assina com Certificado A1, gera PDF DANFSE e transmite ao ADN (aceita `customer_id` e `service_item_id` ou vai para `fila_contingencia` se sem rede) |
| `POST` | `/api/adn/dps/emitir-lote` | Emite múltiplas DPS sequencialmente para o mesmo prestador (`itens[]` + `data_competencia`), retornando contagem de autorizadas, contingência e erros por item |
| `GET` | `/api/adn/fila` | Lista notas pendentes na fila de contingência (`dps_gerada` ou `fila_contingencia`) |
| `POST` | `/api/adn/fila/reenviar` | Retransmite individualmente ou em lote as DPS pendentes na fila |
| `GET` | `/api/adn/worker/status` | Retorna o estado atual, intervalo e resultado da última execução do worker automático de contingência (`SchedulerService`) |
| `POST` | `/api/adn/worker/trigger` | Dispara imediatamente um ciclo do worker de retransmissão da fila de contingência |
| `POST` | `/api/adn/nfse/{invoice_id}/enviar-email` | Recupera/gera XML e PDF sob demanda (`ensure_invoice_files`) e envia por e-mail via SMTP do Prestador ou fallback global (`DEFAULT_SMTP_*`) com `Reply-To` (retorna HTTP `422` se nenhum anexo estiver disponível) |
| `POST` | `/api/adn/cofre/sincronizar` | Sincroniza o Cofre de Notas (emitidas e recebidas) diretamente do Ambiente Nacional via Certificado A1 (`DistDFe` por NSU) |
| `POST` | `/api/adn/nfse/cancelar` | Gera e transmite o evento `e101101` de cancelamento de NFS-e |
| `POST` | `/api/adn/nfse/substituir` | Emite DPS substituta (`<subst>`) e gera evento `e105102` |
| `GET` | `/api/adn/parametros-municipais/{cod_ibge}` | Consulta parâmetros municipais no ADN |

---

## 7.1. Cadastros Recorrentes e Consultas CNPJ/CEP (`/api/customers`, `/api/service-items`, `/api/lookup`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/lookup/cnpj/{cnpj}` | Consulta dados cadastrais, regime tributário (`simples`, `mei`, `normal`) e código IBGE de 7 dígitos pelo CNPJ (aceita 14 caracteres alfanuméricos) |
| `GET` | `/api/lookup/cep/{cep}` | Consulta logradouro, bairro, UF e código IBGE de 7 dígitos pelo CEP |
| `GET` | `/api/customers` | Lista tomadores recorrentes (filtra por `client_id` + globais e busca por `q`) |
| `POST` | `/api/customers` | Cria um tomador recorrente |
| `PUT` | `/api/customers/{customer_id}` | Atualiza dados de um tomador recorrente |
| `DELETE` | `/api/customers/{customer_id}` | Remove um tomador recorrente |
| `GET` | `/api/customers/import/template` | Baixa planilha modelo (`format=csv\|xlsx`) para importação em lote de tomadores |
| `POST` | `/api/customers/import` | Importa tomadores via `multipart/form-data` (`.csv`/`.xlsx`), preservando CNPJs alfanuméricos e atualizando registros existentes opcionalmente |
| `GET` | `/api/service-items` | Lista serviços recorrentes (filtra por `client_id` + globais e busca por `q`) |
| `POST` | `/api/service-items` | Cria um serviço recorrente preenchendo automaticamente `c_nbs`, `c_class_trib`, `cst_ibscbs` e `c_ind_op` pelo Anexo VIII |
| `PUT` | `/api/service-items/{item_id}` | Atualiza dados de um serviço recorrente |
| `DELETE` | `/api/service-items/{item_id}` | Remove um serviço recorrente |
| `GET` | `/api/service-items/import/template` | Baixa planilha modelo (`format=csv\|xlsx`) para importação em lote de serviços |
| `POST` | `/api/service-items/import` | Importa serviços via `multipart/form-data` (`.csv`/`.xlsx`) com enriquecimento automático pela matriz do Anexo VIII |

---

## 7.2. Módulo Persistente de Importação e Emissão em Lote (`/api/batch-emission`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/batch-emission/template` | Baixa o modelo padrão CSV (`;`) ou XLSX (abas `Notas Lote` e `Instrucoes`) para importação de notas |
| `POST` | `/api/batch-emission/import` | Importa planilha CSV (`;` ou `,`) ou XLSX sem transmitir notas, gerando `BatchImport` e `BatchImportItem` e aplicando validação em 3 níveis |
| `GET` | `/api/batch-emission` | Lista o histórico de lotes importados (`client_id` opcional) |
| `GET` | `/api/batch-emission/{batch_id}` | Consulta resumo e contadores do lote |
| `POST` | `/api/batch-emission/{batch_id}/validate` | Reexecuta a validação estrutural (CPF/CNPJ alfanumérico), cadastral e fiscal/XSD v1.01 |
| `GET` | `/api/batch-emission/{batch_id}/items` | Lista linhas do lote com filtro opcional por `status` (`VALID`, `INVALID`, `AUTHORIZED`, `REJECTED`, `UNKNOWN`, `RETRY`, `CANCELLED`) |
| `PATCH` | `/api/batch-emission/{batch_id}/items/{item_id}` | Corrige campos de uma linha específica e revalida imediatamente |
| `POST` | `/api/batch-emission/{batch_id}/process` | Processa sequencialmente os itens válidos confirmados sem manter transação de banco durante chamadas HTTP |
| `POST` | `/api/batch-emission/{batch_id}/retry` | Consulta itens `UNKNOWN` no ADN (`consultar_dps`) antes de reenviar e reprocessa itens `RETRY` |
| `POST` | `/api/batch-emission/{batch_id}/cancel` | Cancela itens ainda pendentes do lote |
| `GET` | `/api/batch-emission/{batch_id}/export` | Exporta resumo e itens detalhados em `format=csv\|xlsx` |

```json title="POST /api/adn/dps/emitir — Exemplo de Payload"
{
  "client_id": 1,
  "transmitir": true,
  "tomador": {
    "documento": "12345678000195",
    "razao_social": "TOMADOR EXEMPLO S.A.",
    "endereco": {
      "codigo_municipio": "3201308",
      "cep": "29140000",
      "logradouro": "AV CENTRAL",
      "numero": "100",
      "bairro": "CENTRO"
    }
  },
  "servico": {
    "codigo_municipio_prestacao": "3201308",
    "cTribNac": "010101",
    "descricao": "Desenvolvimento de software sob encomenda",
    "cNBS": "115021000",
    "valor": 5000.00,
    "cClassTrib": "000001",
    "indop": "030101"
  }
}
```

---

## 8. Analytics e Relatórios (`/api/analytics`, `/api/reports`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/analytics/stats` | Estatísticas consolidadas (`client_id` opcional) |
| `GET` | `/api/analytics/chart` | Dados do gráfico por período (`7d`, `30d`, `90d`, `12m`) |
| `GET` | `/api/analytics/ranking` | Top 5 clientes emitentes e tomadores |
| `POST` | `/api/analytics/enrich-xml` | Extrai valores e números de XMLs já baixados |
| `GET` | `/api/reports/export` | Exporta relatório em `format=json|csv|xlsx` |
| `GET` | `/api/reports/competencia` | Conferência mensal por `competencia=YYYY-MM` em `format=json|csv|xlsx` (separa notas ativas, canceladas/substituídas e pendentes na fila) |

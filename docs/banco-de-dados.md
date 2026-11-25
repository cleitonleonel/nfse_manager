# 🗄️ Banco de Dados (PostgreSQL)

O **NFSe Manager Pro** utiliza **PostgreSQL 16** gerenciado pelo **SQLAlchemy 2.0** (`backend/app/database.py` e `backend/app/models.py`).

---

## 1. Resolução Híbrida de Conexão (`backend/app/database.py`)

A função `resolve_database_url()` em `backend/app/database.py` permite que a aplicação funcione de forma transparente tanto em containers Docker quanto localmente (com PostgreSQL ou SQLite), sem precisar alterar o `.env` ao alternar de ambiente:

1. **Execução dentro do Docker (`nfse_backend`)**:
   - Quando `DATABASE_URL` aponta para o serviço `@database:5432` e o DNS interno da rede `nfse_network` resolve `database`, a conexão é feita diretamente com o container `nfse_database`.
2. **Execução Local no Host com PostgreSQL ativo (via Docker ou local)**:
   - Se `DATABASE_URL` no `.env` contiver `@database:5432`, mas o backend estiver rodando diretamente no host (`./run_web.sh`, `./run_ui.sh` ou `python manage.py`), o sistema detecta que o hostname `database` não existe fora do Docker e substitui automaticamente por `@localhost:<porta>` (verificando `POSTGRES_PORT`, `5434` e `5432`).
3. **Execução Local / Desktop (Tauri) sem PostgreSQL ativo (Fallback SQLite)**:
   - Se nenhum servidor PostgreSQL estiver escutando em `localhost` e `DB_FALLBACK_SQLITE=1` (padrão), o sistema faz *fallback* automático para o banco SQLite local em `backend/nfse.db` (`sqlite:///.../backend/nfse.db`).

Na inicialização da aplicação (`init_db()` em `backend/app/models.py`) ou via CLI (`python manage.py migrate`), o sistema:

1. Aguarda o banco ficar disponível com *retry* automático.
2. Executa as migrações versionadas de `backend/migrations/versions/` (registradas na tabela `schema_migrations`) e sincroniza o schema atual.
3. Criptografa automaticamente em repouso (`EncryptedString` AES/Fernet) eventuais senhas legadas em texto puro.

Para executar o `manage.py` diretamente dentro do container Docker (`nfse_backend`):

```bash
docker compose exec backend python manage.py showmigrations
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py create_admin
```

---

## 2. Diagrama Entidade-Relacionamento (ERD)

```mermaid
erDiagram
    CLIENTS ||--o{ INVOICES : "client_id"

    CLIENTS {
        int id PK
        varchar cnpj UK
        varchar razao_social
        varchar username
        varchar password
        varchar cert_path
        varchar cert_password
        varchar description
        varchar save_path
        varchar path_structure
        varchar inscricao_municipal
        varchar codigo_municipio
        varchar uf
        varchar cep
        varchar logradouro
        varchar numero
        varchar complemento
        varchar bairro
        varchar telefone
        varchar email
        varchar regime_tributario
        varchar regime_apuracao_sn
        varchar regime_especial
        varchar serie_dps_padrao
        int ultimo_numero_dps
        varchar ambiente_padrao
    }

    INVOICES {
        int id PK
        int client_id FK
        timestamp data_emissao
        varchar numero
        varchar chave UK
        varchar status
        varchar tipo
        double valor
        varchar xml_path
        varchar pdf_path
        varchar download_url_xml
        varchar download_url_pdf
        varchar id_dps
        varchar serie_dps
        int numero_dps
        varchar chave_substituida
        varchar chave_substituta
        varchar motivo_cancelamento
        timestamp data_cancelamento
        varchar xml_dps_path
        varchar xml_evento_path
        double valor_iss
        double valor_ibs
        double valor_cbs
        double valor_liquido
        varchar c_trib_nac
        varchar c_nbs
        varchar c_class_trib
        varchar cst_ibscbs
    }
```

---

## 3. Dicionário de Dados

### Tabela `clients`

| Coluna | Tipo | Padrão | Descrição |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | PK Auto | Identificador interno do cliente |
| `cnpj` | `VARCHAR` | Único | CNPJ ou CPF do prestador/tomador |
| `razao_social` | `VARCHAR` | — | Nome empresarial / Razão Social |
| `username` / `password` | `VARCHAR` | — | Credenciais de acesso ao portal (`password` utiliza `EncryptedString` com AES/Fernet) |
| `cert_path` | `VARCHAR` | `NULL` | Caminho do certificado `.pfx` em `backend/certificados/{CNPJ}/` |
| `cert_password` | `VARCHAR` | `NULL` | Senha do certificado digital A1 (`EncryptedString` com AES/Fernet) |
| `cert_valid_until` / `cert_subject` | `TIMESTAMP` / `VARCHAR` | `NULL` | Data de expiração (UTC) e titular X.509 extraídos automaticamente do certificado A1 |
| `save_path` | `VARCHAR` | `NULL` | Diretório base customizado (padrão: `backend/downloads/`) |
| `path_structure` | `VARCHAR` | `NULL` | Máscara de subpastas (ex.: `{CLIENTE}/{TIPO}/{ANO}/{MES}`) |
| `inscricao_municipal` | `VARCHAR` | `NULL` | Inscrição Municipal do prestador |
| `codigo_municipio` | `VARCHAR` | `"3201308"` | Código IBGE de 7 dígitos do município do prestador |
| `uf` | `VARCHAR` | `"ES"` | Sigla da UF do prestador |
| `regime_tributario` | `VARCHAR` | `"normal"` | `normal`, `simples` ou `mei` |
| `regime_apuracao_sn` | `VARCHAR` | `"1"` | Regime de apuração de tributos pelo Simples Nacional (`regApTribSN`) |
| `regime_especial` | `VARCHAR` | `"0"` | Regime especial de tributação (`regEspTrib`) |
| `serie_dps_padrao` | `VARCHAR` | `"900"` | Série padrão para emissão de DPS |
| `ultimo_numero_dps` | `INTEGER` | `0` | Último número sequencial de DPS emitido pelo cliente |
| `ambiente_padrao` | `VARCHAR` | `"homologacao"` | Ambiente padrão ADN (`homologacao` ou `producao`) |
| `ultimo_nsu_adn` | `INTEGER` | `0` | Último NSU sincronizado via Cofre de Notas ADN (`DistDFe`) |
| `smtp_host` / `smtp_port` | `VARCHAR` / `INTEGER` | `NULL` / `587` | Servidor e porta SMTP próprio do Prestador |
| `smtp_user` / `smtp_password` | `VARCHAR` | `NULL` | Credenciais SMTP (`smtp_password` usa `EncryptedString` AES/Fernet) |
| `smtp_from` / `smtp_tls` / `enviar_email_automatico` | `VARCHAR` / `INTEGER` | `NULL` / `1` / `0` | Remetente, uso de STARTTLS e disparo automático na emissão |

### Tabelas `users` (Operadores) e `schema_migrations` (Controle de Migrações)

- **`users`**: armazena os operadores do sistema (`id`, `username` único, `email` único, `full_name`, `password_hash` via `PBKDF2-HMAC-SHA256`, `role` (`admin` ou `operador`), `is_active` e `created_at`). O primeiro superusuário é criado via `python manage.py create_admin`.
- **`schema_migrations`**: controla o histórico de migrações aplicadas pelo utilitário `python manage.py migrate` (`id`, `version` ex.: `0001`, `name` ex.: `initial` e `applied_at`).

### Tabelas `customers` (Tomadores Recorrentes) e `service_items` (Serviços Recorrentes)

- **`customers`**: armazena `id`, `client_id` (FK opcional — `NULL` permite tomadores globais compartilhados), `documento` (CPF/CNPJ), `razao_social`, `inscricao_municipal`, `email`, `telefone`, `cep`, `logradouro`, `numero`, `complemento`, `bairro`, `codigo_municipio` (IBGE 7 dígitos) e `uf`.
- **`service_items`**: armazena `id`, `client_id` (FK opcional), `codigo_interno`, `titulo`, `descricao`, `valor_unitario`, `c_trib_nac`, `c_nbs`, `c_class_trib`, `cst_ibscbs`, `c_ind_op`, `aliquota_iss`, `iss_retido` e `reter_federais`.

### Tabela `invoices`

| Coluna | Tipo | Descrição |
| :--- | :--- | :--- |
| `id` | `INTEGER` (PK) | Identificador interno da nota fiscal |
| `client_id` | `INTEGER` (FK) | Referência para `clients.id` |
| `data_emissao` | `TIMESTAMP` | Data/hora de emissão da nota |
| `numero` | `VARCHAR` | Número da NFS-e ou DPS |
| `chave` | `VARCHAR` (Único) | Chave de acesso de 50 dígitos da NFS-e |
| `status` | `VARCHAR` | Status (`gerada`, `dps_gerada`, `cancelada`, `substituida`, etc.) |
| `tipo` | `VARCHAR` | `emitidas` ou `recebidas` |
| `valor` | `DOUBLE PRECISION` | Valor bruto do serviço (`vServ`) |
| `xml_path` / `pdf_path` | `VARCHAR` | Caminho local do XML e do PDF (DANFSE) em `backend/downloads/` |
| `id_dps` | `VARCHAR` | Identificador de 45 caracteres da DPS (`DPS` + 42 dígitos) |
| `serie_dps` / `numero_dps` | `VARCHAR` / `INTEGER` | Série e número da DPS |
| `chave_substituida` / `chave_substituta` | `VARCHAR` | Chaves de 50 dígitos vinculadas em caso de substituição |
| `motivo_cancelamento` / `data_cancelamento` | `VARCHAR` / `TIMESTAMP` | Histórico de evento de cancelamento ou substituição |
| `xml_dps_path` / `xml_evento_path` | `VARCHAR` | Caminhos dos XMLs assinados de DPS e de eventos (`e101101` / `e105102`) |
| `valor_iss` / `valor_ibs` / `valor_cbs` / `valor_liquido` | `DOUBLE PRECISION` | Valores calculados de ISSQN, IBS, CBS e valor líquido da nota |
| `c_trib_nac` / `c_nbs` / `c_class_trib` / `cst_ibscbs` | `VARCHAR` | Classificações fiscais aplicadas na emissão |
| `tomador_documento` / `tomador_nome` / `tomador_email` | `VARCHAR` | Dados do tomador salvos na emissão para consulta rápida e envio de e-mail |
| `tentativas_envio` / `ultimo_erro_envio` / `payload_dps_json` | `INTEGER` / `VARCHAR` | Controle da Fila de Contingência Offline e diagnóstico de retransmissão |
| `created_by_user_id` / `created_by_username` | `INTEGER` / `VARCHAR` | Auditoria do operador responsável pela emissão da DPS/NFS-e |
| `ambiente` | `VARCHAR` | Ambiente da nota (`producao` ou `homologacao`) |

### Tabela `user_clients`

| Coluna | Tipo | Descrição |
| :--- | :--- | :--- |
| `id` | `INTEGER` (PK) | Identificador do vínculo |
| `user_id` | `INTEGER` (FK) | Referência para `users.id` (`ON DELETE CASCADE`) |
| `client_id` | `INTEGER` (FK) | Referência para `clients.id` (`ON DELETE CASCADE`) |
| `access_level` | `VARCHAR` | Nível de acesso na empresa (`manager` para criador/gestor, `operator` para operador vinculado) |
| `created_at` | `TIMESTAMP` | Data de criação do vínculo |

### Tabela `audit_logs`

| Coluna | Tipo | Descrição |
| :--- | :--- | :--- |
| `id` | `INTEGER` (PK) | Identificador do evento de auditoria |
| `created_at` | `TIMESTAMP` | Data/hora UTC do registro |
| `actor_user_id` / `actor_username` / `actor_role` | `INTEGER` / `VARCHAR` | Usuário responsável pela ação (nullable para rotinas internas) |
| `client_id` | `INTEGER` (FK) | Empresa relacionada ao evento (`ON DELETE SET NULL`) |
| `action` / `entity_type` / `entity_id` | `VARCHAR` | Ação executada, domínio (`user`, `client`, `invoice`, `batch`, `system`) e identificador alvo |
| `summary` / `details_json` | `VARCHAR` | Resumo legível e metadados JSON da operação |
| `status` / `ip_address` | `VARCHAR` | Resultado (`success`, `error`, `denied`) e IP de origem |

---

## 4. Segurança e Criptografia em Repouso (Encryption at Rest)

Para autenticar no Portal Nacional da NFS-e e assinar lotes/eventos via mTLS com certificados A1 (`.pfx`), a aplicação necessita das senhas originais dos clientes (`password` e `cert_password`) em tempo de execução. Logo, **não é viável utilizar funções hash unidirecionais** (como BCrypt ou Argon2), pois elas impossibilitariam o envio das senhas reais aos serviços externos.

Para proteger os dados em caso de vazamento acidental do banco de dados ou despejos (`pg_dump`), o sistema adota **Criptografia Simétrica Autenticada em Repouso** via `backend/app/core/security.py`:

- **Algoritmo**: Fernet (AES-128 em modo CBC com HMAC-SHA256 para autenticação e integridade de dados).
- **Chave Mestra**: Definida na variável de ambiente `NFSE_ENCRYPTION_KEY` (com derivação determinística de 32 bytes via SHA-256).
- **Transparência ORM**: Implementado através do `EncryptedString(TypeDecorator)` em `backend/app/models.py`. As senhas são criptografadas antes do `INSERT`/`UPDATE` e decifradas na leitura pelo SQLAlchemy, mantendo o restante do código desacoplado.
- **Formato no Banco**: As strings criptografadas recebem o prefixo `enc:` seguido do payload Base64 seguro do Fernet (ex: `enc:gAAAAABn...`).
- **Migração Automática**: Na inicialização (`init_db()`), o sistema verifica se há credenciais legadas armazenadas em texto plano e as criptografa automaticamente de forma idempotente.


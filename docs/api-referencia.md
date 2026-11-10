# 📡 Referência da API REST

O backend FastAPI expõe todos os endpoints sob o prefixo `/api` (além da documentação interativa em `/docs` e `/redoc`).

---

## 1. Saúde e Sistema (`/api/health`, `/api/system`, `/api/support`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Healthcheck leve (`{"status": "ok", "version": "..."}`) |
| `GET` | `/api/system/version` | Retorna a versão atual lida do `pyproject.toml` |
| `GET` | `/api/system/check-update` | Consulta a última release no GitHub e compara com a versão local |
| `POST` | `/api/system/update/download` | Baixa o pacote ZIP da release em background para `release/staging/` |
| `POST` | `/api/system/update/apply` | Aplica os arquivos de `release/staging/` com backup transacional e reinicia |
| `GET` | `/api/system/list-folders` | Lista subdiretórios do servidor para seleção visual de pastas |
| `POST` | `/api/support/message` | Registra envio de mensagem de suporte |

---

## 2. Clientes (`/api/clients`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `GET` | `/api/clients` | Lista todos os clientes cadastrados |
| `POST` | `/api/clients` | Cria novo cliente via `multipart/form-data` (dados + certificado `.pfx`) |
| `PUT` | `/api/clients/{client_id}` | Atualiza dados cadastrais, fiscais ou certificado do cliente |
| `DELETE` | `/api/clients/{client_id}` | Remove um cliente pelo ID |

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
| `GET` | `/api/catalogs/indop` | — |
| `GET` | `/api/catalogs/favoritos` | — |

---

## 6. Cálculo e Validação Tributária (`/api/tax`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/tax/calculate` | Calcula `ISSQN`, retenções federais e `IBS/CBS` |
| `POST` | `/api/tax/validate-ibscbs` | Valida compatibilidade entre `CST`, `cClassTrib`, `cIndOp`, `cTribNac` e grupos especiais |

---

## 7. Emissão e Eventos ADN (`/api/adn`)

| Método | Rota | Descrição |
| :--- | :--- | :--- |
| `POST` | `/api/adn/dps/preview` | Gera XML da DPS v1.01, calcula tributos e valida XSD sem transmitir |
| `POST` | `/api/adn/dps/emitir` | Gera, valida XSD, assina com Certificado A1, salva em disco e transmite ao ADN |
| `POST` | `/api/adn/nfse/cancelar` | Gera e transmite o evento `e101101` de cancelamento de NFS-e |
| `POST` | `/api/adn/nfse/substituir` | Emite DPS substituta (`<subst>`) e gera evento `e105102` |
| `GET` | `/api/adn/parametros-municipais/{cod_ibge}` | Consulta parâmetros municipais no ADN |

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

# 🧮 Reforma Tributária (IBS/CBS) & Emissão ADN v1.01

O **NFSe Manager Pro** integra o pacote `pynfse.adn` através da camada [`AdnService`](https://github.com/cleitonleonel/nfse_manager/blob/master/backend/app/services/adn_service.py) para atender integralmente ao leiaute **Sefin Nacional / ADN v1.01** e às regras da **Reforma Tributária do Consumo (`LC 214/2025` e `NT 1.101`)**.

---

## 1. Catálogos Fiscais Oficiais e Atualizáveis (`/api/catalogs`)

A aplicação consome os catálogos oficiais mantidos pela `pynfse` (base RFB `V0073` + Anexos VII v1.03.00 e VIII v1.02.00) e permite atualizá-los diretamente na interface (**Sistema & Administração → Catálogos Tributários Oficiais**) ou via API (`/api/catalogs/sync`) sem depender de terceiros:

- **18 Códigos de Situação Tributária (`CST`)** do IBS/CBS (`/api/catalogs/cst`).
- **173+ Classificações Tributárias (`cClassTrib`)** da Reforma Tributária (`/api/catalogs/cclasstrib`), com filtro por `apenas_nfse=true`, `apenas_anexo_viii=true`, indicadores de redução de alíquota, diferimento, crédito presumido e estorno.
- **920 Códigos NBS Oficiais** (`/api/catalogs/nbs` e `/api/catalogs/nbs/{c_nbs}/combinacoes`), cobrindo tanto os **731 NBS do Anexo VIII** quanto os demais códigos com enquadramento na **Regra Geral** (`CST 000` / `cClassTrib 000001` / `cIndOp 100301`).
- **338 Códigos de Tributação Nacional (`cTribNac` — 6 dígitos)** distribuídos nos 41 grupos da **LC 116/2003** (`/api/catalogs/servicos` e `/api/catalogs/lc116`), integrados na tela de emissão via seletor pesquisável.
- **1.603+ Correlações Oficiais do Anexo VIII** cruzando `Item LC 116 x cTribNac x NBS x cIndOp x cClassTrib` (`/api/catalogs/correlacoes`), com filtro automático por `cTribNac` ou listagem completa na interface.
- **48+ Códigos Indicadores de Operação (`cIndOp`)** combinando o Anexo VII v1.03.00 e a Calculadora RFB (`/api/catalogs/indop`).

> 💡 **Atualização em ambiente multiusuário / WTS:** As sincronizações via `POST /api/catalogs/sync` (exclusivo para administradores) salvam os arquivos JSON no diretório compartilhado definido por `NFSE_CATALOGS_DIR` (padrão `{NFSE_DATA_DIR}/catalogs`), aplicando a atualização imediatamente sem reinstalar o aplicativo.

---

## 2. Motor de Cálculo Tributário (`/api/tax/calculate`)

O cálculo tributário contempla simultaneamente **ISSQN**, **Retenções Federais (`PIS`, `COFINS`, `IRRF`, `CSLL`, `INSS`)** e **IBS (Estadual + Municipal) / CBS (Federal)** conforme o cronograma de transição:

### Cronograma de Transição (2026 a 2033+)

| Período | Regras Aplicadas pelo Motor |
| :--- | :--- |
| **2026** | Vigência plena de `ISSQN` e `PIS/COFINS`. A base de cálculo `vBC` do IBS/CBS deduz o `ISSQN`, o `PIS` e a `COFINS`. As alíquotas de teste (`0,1%` IBS e `0,9%` CBS) são destacadas informativamente e **não** somam por fora no `valor_total_nf`. |
| **2027 a 2032** | Extinção do `PIS` e da `COFINS` (entrada plena da `CBS`). O `ISSQN` continua sendo deduzido da `vBC` do IBS/CBS. O valor líquido de `IBS + CBS` passa a somar no `valor_total_nf`. |
| **2033+** | Extinção do `ISSQN` (entrada plena do `IBS` Estadual e Municipal). A `vBC` do IBS/CBS passa a considerar apenas descontos incondicionados, reembolsos/repasses e deduções legais. |

### Reduções de Alíquota por `cClassTrib`

O motor aplica automaticamente os percentuais de redução previstos na LC 214/2025:

- **`000001` (CST `000`)**: Tributação integral (0% de redução).
- **`200029` (CST `200`) — Serviços de Saúde**: redução de **60%** no IBS e **60%** na CBS.
- **`200025` (CST `200`) — Prouni**: redução assimétrica de **60%** no IBS e **100%** na CBS.
- **`200052` (CST `200`) — Profissões intelectuais regulamentadas**: redução de **30%** no IBS e **30%** na CBS.
- **`200027` (CST `200`) — Locação, cessão e arrendamento de bens imóveis**: redução de **70%** no IBS e **70%** na CBS.

---

## 3. Validador de Regras de Negócio IBS/CBS (`/api/tax/validate-ibscbs`)

Antes de gerar ou transmitir uma DPS, o validador verifica as regras da Nota Técnica 1.101, retornando os códigos oficiais de rejeição caso haja inconsistência:

- **`E0958`**: `cClassTrib` inexistente na tabela nacional.
- **`E0959`**: `CST` incompatível com os 3 primeiros dígitos do `cClassTrib`.
- **`E0931`**: Serviço de construção civil (`070201`, `070501`, etc.) ou locação de imóvel com preenchimento inválido do grupo de imóvel no bloco IBS/CBS.
- **`E0905`**: Indicador de operação `tpOper = 2` sem nota fiscal referenciada (`gRefNFSe`).
- **`E0910`**: Indicador `indDest = 0` (destinatário é o próprio tomador) com grupo `dest` informado.
- **`E0966`**: Classificação de doação/estorno de crédito (`410026`) sem indicador `indDoacao`.

---

## 4. Emissão, Substituição e Cancelamento no ADN (`/api/adn`)

1. **Formatação de ID da DPS (`formatar_id_dps`)**:
   - Padrão de 45 caracteres: `DPS` + Código IBGE (7) + Tipo de Inscrição (1) + CNPJ/CPF (14) + Série (5) + Número (15).
2. **Validação XSD v1.01 (`XsdValidator`)**:
   - Todo XML de DPS é validado contra `DPS_v1.01.xsd` (com `tiposComplexos_v1.01.xsd`, `tiposSimples_v1.01.xsd` e `xmldsig-core-schema_v1.00.xsd`) **antes e depois** da assinatura digital.
   - Todo XML de evento (`e101101` cancelamento e `e105102` cancelamento por substituição) é validado contra `pedRegEvento_v1.01.xsd`.
3. **Assinatura Digital XML-DSig (`DpsSigner`)**:
   - Assina a tag `<infDPS>` (na emissão/substituição) ou `<infPedReg>` (nos eventos) com certificado A1 `.pfx` (`RSA-SHA256`, `C14N` sem comentários, `enveloped-signature`).
4. **Persistência Local, DANFSe Automático e Transmissão mTLS (`AdnNfseClient`)**:
   - Os XMLs assinados são salvos em `backend/downloads/adn/dps/`, `backend/downloads/adn/nfse/` e `backend/downloads/adn/eventos/`, e o PDF do DANFSe é gerado automaticamente em `backend/downloads/adn/pdfs/`.
   - Quando `transmitir=True` e o cliente possui certificado A1 configurado, a transmissão ocorre via mTLS para o endpoint nacional de homologação ou produção.
5. **Fila de Contingência Offline (`/api/adn/fila` e `/api/adn/fila/reenviar`)**:
   - Se ocorrer falha de rede, timeout ou erro 5xx na Sefin durante a emissão, a nota é salva com `status="fila_contingencia"` para retransmissão posterior em lote sem perda de dados.
6. **Envio de XML + DANFSe por E-mail (`/api/adn/nfse/{invoice_id}/enviar-email`)**:
   - Garante a existência local do XML e do PDF (`ensure_invoice_files`, convertendo `.html` ou baixando do portal sob demanda caso a nota tenha sido apenas sincronizada) e bloqueia com HTTP `422` se nenhum anexo válido estiver disponível.
   - Utiliza prioritariamente o SMTP configurado no cadastro do Prestador (`origem_smtp="cliente"`) ou o fallback global do servidor (`DEFAULT_SMTP_HOST`, `DEFAULT_SMTP_USER`, `DEFAULT_SMTP_PASSWORD` — `origem_smtp="sistema"`), adicionando automaticamente o cabeçalho `Reply-To` apontando para o e-mail do prestador.
7. **Cofre de Notas ADN por NSU (`/api/adn/cofre/sincronizar`)**:
   - Sincroniza incrementalmente todas as notas emitidas e recebidas em que o CNPJ do cliente figura diretamente da distribuição DFe do Ambiente Nacional (`ultimo_nsu_adn`).
8. **Emissão em Lote (`/api/adn/dps/emitir-lote`) & Importação por Planilha**:
   - Permite selecionar múltiplos tomadores recorrentes na mesma competência para gerar, validar XSD, assinar e transmitir em sequência, além de importar tomadores e serviços via CSV/XLSX (`/api/customers/import`, `/api/service-items/import`) com enriquecimento automático do Anexo VIII.
9. **Conferência Mensal por Competência (`/api/reports/competencia`)**:
   - Consolida emitidas ativas, recebidas ativas, tributos (`ISS`, `IBS`, `CBS`), fila de contingência e exceções (`cancelada`/`substituida`) em JSON, CSV e XLSX sem somar notas canceladas no faturamento.

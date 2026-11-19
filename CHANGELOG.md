# Changelog

## v0.2.3 (2026-11-19)

Comparativo a partir de `v0.2.2`.

### Destaques

Fallback de paths legados, erros reais de download, limpeza local de notas e seletor de competencia no Tauri

### Documentação

- `9e52d30` docs: documenta comando unificado manage.py release (cleiton)

### Resumo por Camada

- **Raiz & Configuração**: 1 arquivo(s)
- **Backend (API, Serviços & Banco)**: 4 arquivo(s)
- **Documentação**: 1 arquivo(s)
- **Frontend SPA**: 5 arquivo(s)
- **Testes Automatizados**: 3 arquivo(s)

## v0.2.2 (2026-11-19)

Comparativo a partir de `v0.2.1`.

### Destaques

Restricao de save_path de clientes para admin/subpastas validas, espelhamento local de downloads no navegador (File System Access API), ajuste de status na aba Sobre e comando unificado manage.py release.

### Resumo por Camada

- **Backend (API, Serviços & Banco)**: 1 arquivo(s)
- **Frontend SPA**: 8 arquivo(s)
- **Raiz & Configuração**: 1 arquivo(s)
- **CI/CD & Automação**: 1 arquivo(s)
- **Testes Automatizados**: 1 arquivo(s)

## v0.2.1 (2026-11-19)

Comparativo a partir de `v0.1.0`.

### Destaques

Design mobile Material Design 3 (Bottom Sheet para selects e tabelas compactas), alinhamento dos botoes e escala tipografica da emissao, exibicao completa da chave NFS-e nas tabelas, fallback do changelog local, metadados/atalhos/descricoes dos instaladores desktop (Windows/Linux) e correcao do lock distribuido no PostgreSQL.

### Novas Funcionalidades

- `932313c` feat: adiciona sincronização de catálogos oficiais e endpoint NBS (cleiton)
- `81c8175` feat: adiciona storage portável e automação de versionamento (cleiton)
- `f8ffca4` feat: adiciona relatório por competência e aprimora ações de notas fiscais (cleiton)
- `7f3c7c3` feat: adiciona autenticação JWT, migrações e ações ADN para notas fiscais (cleiton)
- `61f73be` feat: adiciona criptografia de credenciais e conversão de HTML em XML/PDF (cleiton)
- `081ea47` feat: adiciona fluxos de trabalho do GitHub Actions para lançamento automatizado e implantação de documentação (cleiton)
- `8a8aaba` feat: geração local de PDF a partir de XML para notas fiscais e ajustes no download (cleiton)

### Refatoração e Performance

- `1a7c5b8` refactor: ajuste nas propriedades de grid para o portal de autenticação (cleiton)
- `6c04c35` refactor: simplificação do download de arquivos e melhorias gerais (cleiton)
- `b370a93` refactor: alteração de "Notes" para "Invoices" (cleiton)

### Infraestrutura, Build e CI/CD

- `edc9acf` chore: ajusta build de instaladores desktop e dados do sidecar (cleiton)
- `664c261` chore: ajusta testes de downloads e concorrência do lock distribuído (cleiton)
- `4fa81a1` chore: adiciona changelog e automação de instaladores desktop (cleiton)
- `0c7711a` chore: atualiza lockfile e dependência do emissor NFSe (cleiton)
- `fd45c03` chore: aprimora responsividade do frontend e adiciona menu lateral expansível (cleiton)
- `ccffc1f` chore: ajusta layout de campos da emissão e adiciona demo ao README (cleiton)
- `17a1a91` chore: adiciona dependências ARM no Docker do backend e documenta Raspberry Pi (cleiton)
- `2600cbe` chore: adiciona dependências ARM no Docker do backend e documenta Raspberry Pi (cleiton)
- `fc208f9` chore: ajusta diretórios de migrações no Docker do backend (cleiton)
- `84ce95f` chore: atualiza cópia de assets no Dockerfile do frontend (cleiton)
- `90d1992` chore: adiciona Docker para backend e ajusta máscara de CPF/CNPJ (cleiton)
- `c5a7054` chore: adição de scripts para sincronização de versão e release (cleiton)

### Testes e Qualidade

- `2d77110` test: adiciona cobertura para conversão de notas, credenciais e exclusão de clientes (cleiton)

### Documentação

- `e63ed3f` docs: corrige diagramas Mermaid e contagem de routers REST (cleiton)
- `f77ba52` docs: corrige descrição do site no MkDocs (cleiton)
- `b4d4c3d` docs: atualização da arquitetura para PostgreSQL, Docker e backend app (cleiton)
- `8d92f88` docs: atualização do README com imagens e descrição aprimorada (cleiton)

### Melhorias Gerais

- `c3803af` chore: atualiza metadados dos instaladores desktop e layout da emissão (cleiton)
- `e055274` chore: ajusta liberação do lock distribuído PostgreSQL (cleiton)
- `bde1053` chore: aprimora responsividade mobile e custom select em bottom sheet (cleiton)
- `c2dfd5e` chore: ajusta responsividade da topbar e abas da emissão (cleiton)
- `5820d96` chore: aprimora responsividade de tabelas, dashboard e emissão (cleiton)

### Resumo por Camada

- **Raiz & Configuração**: 15 arquivo(s)
- **CI/CD & Automação**: 6 arquivo(s)
- **Backend (API, Serviços & Banco)**: 55 arquivo(s)
- **Documentação**: 21 arquivo(s)
- **Frontend SPA**: 42 arquivo(s)
- **Testes Automatizados**: 14 arquivo(s)
- **Desktop Tauri & Empacotamento**: 17 arquivo(s)

## v0.2.0 (2026-11-18)

Comparativo a partir de `v0.1.0`.

### Destaques

Suporte multiusuário com gestão de operadores (Admin/Operador), banco centralizado PostgreSQL, locks transacionais de DPS/Lote/Scheduler, compatibilidade Windows Server/WTS no Desktop Tauri, envio de suporte por E-mail+Telegram e scripts/CI para instaladores Windows (.exe/.msi) e Linux (.deb/.AppImage).

### Novas Funcionalidades

- `f8ffca4` feat: adiciona relatório por competência e aprimora ações de notas fiscais (cleiton)
- `7f3c7c3` feat: adiciona autenticação JWT, migrações e ações ADN para notas fiscais (cleiton)
- `61f73be` feat: adiciona criptografia de credenciais e conversão de HTML em XML/PDF (cleiton)
- `081ea47` feat: adiciona fluxos de trabalho do GitHub Actions para lançamento automatizado e implantação de documentação (cleiton)
- `8a8aaba` feat: geração local de PDF a partir de XML para notas fiscais e ajustes no download (cleiton)

### Refatoração e Performance

- `1a7c5b8` refactor: ajuste nas propriedades de grid para o portal de autenticação (cleiton)
- `6c04c35` refactor: simplificação do download de arquivos e melhorias gerais (cleiton)
- `b370a93` refactor: alteração de "Notes" para "Invoices" (cleiton)

### Infraestrutura, Build e CI/CD

- `fd45c03` chore: aprimora responsividade do frontend e adiciona menu lateral expansível (cleiton)
- `ccffc1f` chore: ajusta layout de campos da emissão e adiciona demo ao README (cleiton)
- `17a1a91` chore: adiciona dependências ARM no Docker do backend e documenta Raspberry Pi (cleiton)
- `2600cbe` chore: adiciona dependências ARM no Docker do backend e documenta Raspberry Pi (cleiton)
- `fc208f9` chore: ajusta diretórios de migrações no Docker do backend (cleiton)
- `84ce95f` chore: atualiza cópia de assets no Dockerfile do frontend (cleiton)
- `90d1992` chore: adiciona Docker para backend e ajusta máscara de CPF/CNPJ (cleiton)
- `c5a7054` chore: adição de scripts para sincronização de versão e release (cleiton)

### Testes e Qualidade

- `2d77110` test: adiciona cobertura para conversão de notas, credenciais e exclusão de clientes (cleiton)

### Documentação

- `e63ed3f` docs: corrige diagramas Mermaid e contagem de routers REST (cleiton)
- `f77ba52` docs: corrige descrição do site no MkDocs (cleiton)
- `b4d4c3d` docs: atualização da arquitetura para PostgreSQL, Docker e backend app (cleiton)
- `8d92f88` docs: atualização do README com imagens e descrição aprimorada (cleiton)

### Melhorias Gerais

- `c2dfd5e` chore: ajusta responsividade da topbar e abas da emissão (cleiton)
- `5820d96` chore: aprimora responsividade de tabelas, dashboard e emissão (cleiton)

### Resumo por Camada

- **Raiz & Configuração**: 14 arquivo(s)
- **CI/CD & Automação**: 6 arquivo(s)
- **Backend (API, Serviços & Banco)**: 56 arquivo(s)
- **Documentação**: 21 arquivo(s)
- **Frontend SPA**: 42 arquivo(s)
- **Testes Automatizados**: 14 arquivo(s)
- **Desktop Tauri & Empacotamento**: 6 arquivo(s)

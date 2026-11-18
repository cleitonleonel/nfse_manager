# Tauri Desktop App — NFSe Manager Pro

Este diretório contém o shell Tauri que transforma o NFSe Manager em um **app desktop** (Linux, Windows, macOS).

## Arquitetura

```
┌─────────────────────────────────────┐
│           Tauri (Rust)              │  ← janela nativa, system tray
│  WebView → http://localhost:8000    │  ← carrega a UI existente
├─────────────────────────────────────┤
│       FastAPI + PostgreSQL (Python) │  ← mesmo server.py atual
│       Sidecar / processo externo    │
└─────────────────────────────────────┘
```

O Tauri não duplica o frontend — ele apenas abre uma janela nativa apontando para o servidor Python que já existe.

---

## Pré-requisitos

### Linux (Ubuntu/Debian/Pop!_OS)

```bash
sudo apt-get install -y \
  libwebkit2gtk-4.0-dev \
  librsvg2-dev \
  libssl-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  patchelf
```

### Rust (mínimo 1.70)

```bash
# Se precisar atualizar o Rust:
rustup update stable
```

### Node.js

Qualquer versão ≥ 16 (já detectado: v22.17.1 ✅)

---

## Modo Desenvolvimento

Em desenvolvimento, o Tauri aponta diretamente para o servidor Python rodando em `localhost:8000`. Não precisa compilar nada.

```bash
# Da pasta ui/:
./dev.sh

# Ou manualmente:
# Terminal 1 — servidor Python
cd ../ && python3 server.py

# Terminal 2 — Tauri
cd ui/ && npm run tauri dev
```

---

## Build para Distribuição

### 1. Empacotar o servidor Python como binário

```bash
cd ui/
./build_sidecar.sh
```

Isso usa PyInstaller para criar um binário standalone do servidor e o coloca em `src-tauri/binaries/server-x86_64-unknown-linux-gnu`.

### 2. Compilar o app Tauri

```bash
cd ui/
npm run build
# ou tudo de uma vez:
./release.sh
```

### Saída

Os pacotes ficam em `src-tauri/target/release/bundle/`:
- **Linux**: `.deb` e `.AppImage`
- **Windows**: `.msi` e `.exe` (requer cross-compilation ou build no Windows)
- **macOS**: `.dmg` (requer build no macOS)

---

## Estrutura de arquivos

```
ui/
├── package.json              # Dependências npm (@tauri-apps/cli)
├── dev.sh                    # Script de dev (inicia Python + Tauri)
├── build_sidecar.sh          # Empacota o server.py com PyInstaller
├── release.sh                # Build completo para distribuição
└── src-tauri/
    ├── Cargo.toml            # Dependências Rust
    ├── build.rs              # Script de build padrão do Tauri
    ├── tauri.conf.json       # Configuração principal do Tauri
    ├── icons/                # Ícones do app (PNG, ICO, ICNS)
    ├── binaries/             # Binário do servidor (gerado pelo build_sidecar.sh)
    └── src/
        └── main.rs           # Código Rust: tray, sidecar, janela
```

---

## Funcionalidades do App Desktop

- ✅ Janela nativa sem barra de URL
- ✅ Ícone personalizado na taskbar
- ✅ System tray (minimiza para a bandeja ao fechar)
- ✅ Menu de tray: "Mostrar Janela" / "Encerrar"
- ✅ Tamanho mínimo de janela (960×600)
- ✅ Centralizado na primeira abertura
- ✅ Detecção automática de servidor central vs sidecar em porta livre (`127.0.0.1:0`)

---

## Operação Multiusuário (Windows Server / WTS)

Em ambientes com múltiplos usuários simultâneos (ex.: **Windows Server com Terminal Services / WTS** ou rede local), o shell Desktop Tauri evita conflito na porta `8000` e compartilhamento concorrente de SQLite seguindo a ordem de configuração abaixo:

1. Variável de ambiente `NFSE_SERVER_URL` (ex.: `http://127.0.0.1:8000` ou `http://servidor-fiscal:8000`).
2. Arquivo global da máquina:
   - Windows: `%PROGRAMDATA%\NFSeManager\desktop.json`
   - Linux: `/etc/nfse-manager/desktop.json`
3. Arquivo por usuário:
   - Windows: `%APPDATA%\br.com.nfse.manager\desktop.json`
   - Linux: `$HOME/.config/nfse-manager/desktop.json`

Exemplo de `desktop.json`:

```json
{
  "mode": "auto",
  "server_url": "http://127.0.0.1:8000",
  "data_dir": "D:\\NFSeData",
  "disable_scheduler": false
}
```

### Modos disponíveis
- **`auto` (padrão)**: sonda `server_url` (ou `http://127.0.0.1:8000/api/health`). Se o serviço central estiver ativo, a janela conecta diretamente a ele **sem** subir outro processo Python. Caso contrário, aloca uma porta TCP livre (`127.0.0.1:0`) e inicia um sidecar isolado.
- **`central` / `remote`**: conecta diretamente ao `server_url` configurado sem iniciar sidecar local.
- **`sidecar`**: força o uso do sidecar local em porta livre automática (`--host 127.0.0.1 --port <PORTA>`).

### Parâmetros CLI do `server.py` (Serviço Central / Sidecar)
- `--host`: endereço de escuta (padrão `0.0.0.0`).
- `--port`: porta TCP (padrão `8000`; use `0` para alocação automática de porta livre).
- `--data-dir`: define `NFSE_DATA_DIR` (banco, certificados e downloads).
- `--disable-scheduler`: desabilita o worker interno neste processo (`NFSE_SCHEDULER_MODE=disabled`).


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
- ✅ Servidor Python iniciado automaticamente

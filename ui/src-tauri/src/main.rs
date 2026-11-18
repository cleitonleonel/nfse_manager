// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::api::process::{Command, CommandChild};
use tauri::{
    CustomMenuItem, Manager, RunEvent, SystemTray, SystemTrayEvent, SystemTrayMenu,
    SystemTrayMenuItem,
};

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
struct DesktopConfig {
    mode: Option<String>,
    server_url: Option<String>,
    data_dir: Option<String>,
    disable_scheduler: Option<bool>,
}

struct SidecarState(Arc<Mutex<Option<CommandChild>>>);

impl SidecarState {
    fn set(&self, child: CommandChild) {
        if let Ok(mut guard) = self.0.lock() {
            *guard = Some(child);
        }
    }

    fn kill(&self) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

fn system_config_path() -> Option<PathBuf> {
    #[cfg(target_os = "windows")]
    {
        std::env::var_os("PROGRAMDATA")
            .map(|p| PathBuf::from(p).join("NFSeManager").join("desktop.json"))
    }
    #[cfg(not(target_os = "windows"))]
    {
        Some(PathBuf::from("/etc/nfse-manager/desktop.json"))
    }
}

fn user_config_path() -> Option<PathBuf> {
    #[cfg(target_os = "windows")]
    {
        std::env::var_os("APPDATA")
            .map(|p| PathBuf::from(p).join("br.com.nfse.manager").join("desktop.json"))
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::env::var_os("HOME").map(|p| {
            PathBuf::from(p)
                .join(".config")
                .join("nfse-manager")
                .join("desktop.json")
        })
    }
}

fn read_config_file(path: &PathBuf) -> Option<DesktopConfig> {
    let content = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<DesktopConfig>(&content).ok()
}

fn merge_config(base: &mut DesktopConfig, overlay: DesktopConfig) {
    if overlay
        .mode
        .as_deref()
        .is_some_and(|s| !s.trim().is_empty())
    {
        base.mode = overlay.mode;
    }
    if overlay
        .server_url
        .as_deref()
        .is_some_and(|s| !s.trim().is_empty())
    {
        base.server_url = overlay.server_url;
    }
    if overlay
        .data_dir
        .as_deref()
        .is_some_and(|s| !s.trim().is_empty())
    {
        base.data_dir = overlay.data_dir;
    }
    if overlay.disable_scheduler.is_some() {
        base.disable_scheduler = overlay.disable_scheduler;
    }
}

fn load_desktop_config() -> DesktopConfig {
    let mut cfg = DesktopConfig::default();

    // Menor prioridade: configuração por usuário
    if let Some(user_path) = user_config_path() {
        if let Some(user_cfg) = read_config_file(&user_path) {
            merge_config(&mut cfg, user_cfg);
        }
    }

    // Prioridade intermediária: configuração global da máquina / servidor WTS
    if let Some(sys_path) = system_config_path() {
        if let Some(sys_cfg) = read_config_file(&sys_path) {
            merge_config(&mut cfg, sys_cfg);
        }
    }

    // Maior prioridade: variável de ambiente NFSE_SERVER_URL
    if let Ok(env_url) = std::env::var("NFSE_SERVER_URL") {
        let trimmed = env_url.trim().to_string();
        if !trimmed.is_empty() {
            cfg.server_url = Some(trimmed);
        }
    }

    cfg
}

fn normalize_url(raw: &str) -> String {
    raw.trim().trim_end_matches('/').to_string()
}

fn parse_http_target(url: &str) -> Option<(bool, String, u16, String)> {
    let trimmed = url.trim();
    let (is_https, rest) = if let Some(r) = trimmed.strip_prefix("https://") {
        (true, r)
    } else if let Some(r) = trimmed.strip_prefix("http://") {
        (false, r)
    } else {
        (false, trimmed)
    };

    let (authority, base_path) = match rest.find('/') {
        Some(idx) => (&rest[..idx], rest[idx..].trim_end_matches('/').to_string()),
        None => (rest, String::new()),
    };
    if authority.is_empty() {
        return None;
    }

    let default_port = if is_https { 443 } else { 80 };
    let (host, port) = if let Some(bracket_end) = authority.find(']') {
        let h = authority[..=bracket_end].to_string();
        let p = authority[bracket_end + 1..]
            .strip_prefix(':')
            .and_then(|s| s.parse::<u16>().ok())
            .unwrap_or(default_port);
        (h, p)
    } else if let Some((h, p_str)) = authority.rsplit_once(':') {
        let p = p_str.parse::<u16>().ok()?;
        (h.to_string(), p)
    } else {
        (authority.to_string(), default_port)
    };

    Some((is_https, host, port, base_path))
}

fn probe_http_200(host: &str, host_clean: &str, port: u16, path: &str, timeout: Duration) -> bool {
    let Ok(mut addrs) = (host_clean, port).to_socket_addrs() else {
        return false;
    };
    let Some(addr) = addrs.next() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, timeout) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));

    let req = format!(
        "GET {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
        path, host, port
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }

    let mut buf = [0u8; 256];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let head = String::from_utf8_lossy(&buf[..n]);
            head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
        }
        _ => false,
    }
}

fn probe_server_health(url: &str, timeout: Duration) -> bool {
    let Some((is_https, host, port, base_path)) = parse_http_target(url) else {
        return false;
    };
    let host_clean = host.trim_start_matches('[').trim_end_matches(']');
    if is_https {
        let Ok(mut addrs) = (host_clean, port).to_socket_addrs() else {
            return false;
        };
        return addrs
            .next()
            .and_then(|addr| TcpStream::connect_timeout(&addr, timeout).ok())
            .is_some();
    }

    let health_path = format!("{}/api/health", base_path);
    let root_path = if base_path.is_empty() {
        "/".to_string()
    } else {
        format!("{}/", base_path)
    };

    // Exige tanto `/api/health` quanto `/` retornando 200 OK para evitar conectar em
    // containers backend-only (ex: Docker porta 8000 sem frontend montado).
    probe_http_200(&host, host_clean, port, &health_path, timeout)
        && probe_http_200(&host, host_clean, port, &root_path, timeout)
}

fn allocate_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr().map(|addr| addr.port()))
        .unwrap_or(8000)
}

fn spawn_local_sidecar(port: u16, config: &DesktopConfig) -> Result<CommandChild, String> {
    let mut args = vec![
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
    ];
    if let Some(ref data_dir) = config.data_dir {
        if !data_dir.trim().is_empty() {
            args.push("--data-dir".to_string());
            args.push(data_dir.clone());
        }
    }
    if config.disable_scheduler == Some(true) {
        args.push("--disable-scheduler".to_string());
    }

    let cmd = Command::new_sidecar("server")
        .map_err(|e| format!("Falha ao localizar sidecar 'server': {}", e))?
        .args(args);

    let (_rx, child) = cmd
        .spawn()
        .map_err(|e| format!("Falha ao iniciar sidecar 'server': {}", e))?;
    Ok(child)
}

fn wait_for_health(url: &str, max_wait: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < max_wait {
        if probe_server_health(url, Duration::from_millis(350)) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

fn resolve_target_url(app_handle: &tauri::AppHandle) -> String {
    let config = load_desktop_config();
    let mode = config
        .mode
        .as_deref()
        .unwrap_or("auto")
        .trim()
        .to_lowercase();
    let configured_url = config
        .server_url
        .as_deref()
        .map(normalize_url)
        .filter(|s| !s.is_empty());

    if mode != "sidecar" {
        let probe_url = configured_url
            .clone()
            .unwrap_or_else(|| "http://127.0.0.1:8000".to_string());
        if probe_server_health(&probe_url, Duration::from_millis(700)) {
            return probe_url;
        }
        if mode == "central" || mode == "remote" {
            return probe_url;
        }
    }

    // Fallback (ou modo "sidecar"): alocar porta TCP livre e subir sidecar isolado
    let port = allocate_free_port();
    let local_url = format!("http://127.0.0.1:{}", port);

    match spawn_local_sidecar(port, &config) {
        Ok(child) => {
            app_handle.state::<SidecarState>().set(child);
            let _ = wait_for_health(&local_url, Duration::from_secs(20));
        }
        Err(err) => {
            eprintln!("[tauri-setup] {}", err);
            // Em desenvolvimento sem sidecar compilado, aguarda servidor dev padrão se existir
            if probe_server_health("http://127.0.0.1:8000", Duration::from_millis(400)) {
                return "http://127.0.0.1:8000".to_string();
            }
        }
    }

    local_url
}

fn main() {
    let quit = CustomMenuItem::new("quit".to_string(), "Encerrar NFSe Manager");
    let show = CustomMenuItem::new("show".to_string(), "Mostrar Janela");
    let tray_menu = SystemTrayMenu::new()
        .add_item(show)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);

    let system_tray = SystemTray::new().with_menu(tray_menu);
    let sidecar_state = SidecarState(Arc::new(Mutex::new(None)));

    let app = tauri::Builder::default()
        .manage(sidecar_state)
        .system_tray(system_tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::LeftClick { .. } => {
                if let Some(window) = app.get_window("main") {
                    if window.is_visible().unwrap_or(false) {
                        let _ = window.hide();
                    } else {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
                "quit" => {
                    app.state::<SidecarState>().kill();
                    app.exit(0);
                }
                "show" => {
                    if let Some(window) = app.get_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
                _ => {}
            },
            _ => {}
        })
        .setup(|app| {
            let app_handle = app.handle();
            std::thread::spawn(move || {
                let target_url = resolve_target_url(&app_handle);
                if let Some(window) = app_handle.get_window("main") {
                    if let Ok(url_json) = serde_json::to_string(&target_url) {
                        let nav_script = format!(
                            "if (window.location.href.indexOf({0}) !== 0) {{ window.location.replace({0}); }}",
                            url_json
                        );
                        let _ = window.eval(&nav_script);
                        std::thread::sleep(Duration::from_millis(250));
                        let _ = window.eval(&nav_script);
                    }
                    std::thread::sleep(Duration::from_millis(150));
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            });
            Ok(())
        })
        .on_window_event(|event| {
            // Minimize to tray instead of closing
            if let tauri::WindowEvent::CloseRequested { api, .. } = event.event() {
                let _ = event.window().hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building NFSe Manager");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            app_handle.state::<SidecarState>().kill();
        }
    });
}

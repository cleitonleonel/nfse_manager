use std::env;
use std::fs;
use std::path::Path;

fn main() {
    // Em modo debug (`tauri dev` / `cargo check`), cria um placeholder vazio caso o
    // sidecar PyInstaller ainda não tenha sido gerado por `build_sidecar.sh`.
    // Em builds `release`, o binário real continua obrigatório.
    if env::var("PROFILE").as_deref() == Ok("debug") {
        if let Ok(target) = env::var("TARGET") {
            let ext = if target.contains("windows") { ".exe" } else { "" };
            let bin_path = Path::new("binaries").join(format!("server-{target}{ext}"));
            if !bin_path.exists() {
                if let Some(parent) = bin_path.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                let _ = fs::write(&bin_path, b"");
            }
        }
    }

    tauri_build::build()
}

from pathlib import Path
import tempfile
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.version import VERSION, get_version
from app.api.routers import system


client = TestClient(app)


def test_version_constant_matches_pyproject():
    assert VERSION == get_version()
    assert VERSION.count(".") == 2


def test_system_version_endpoint_returns_current_version():
    response = client.get("/api/system/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_version"] == VERSION


def test_check_update_marks_newer_release(monkeypatch):
    monkeypatch.setattr(
        system,
        "_latest_release_data",
        lambda: {
            "tag_name": "v9.9.9",
            "zipball_url": "https://example.com/release.zip",
            "html_url": "https://example.com/release/9.9.9",
            "body": "Notas de teste",
        },
    )

    response = client.get("/api/system/check-update")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_version"] == VERSION
    assert payload["latest_version"] == "9.9.9"
    assert payload["update_available"] is True
    assert payload["zipball_url"] == "https://example.com/release.zip"


def test_stage_from_zip_removes_top_level_folder_and_extracts_files():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        zip_path = td / "sample.zip"
        stage = td / "stage"
        stage.mkdir()

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("repo-name/backend/test.txt", "hello")
            zf.writestr("repo-name/frontend/nested/a.txt", "world")

        task_id = "task-stage"
        system.tasks_status[task_id] = {"status": "running", "message": "x", "progress": 0}

        system._stage_from_zip(zip_path, stage, task_id)

        assert (stage / "backend" / "test.txt").read_text() == "hello"
        assert (stage / "frontend" / "nested" / "a.txt").read_text() == "world"
        assert system.tasks_status[task_id]["phase"] == "extracting"


def test_copy_tree_transactional_copies_files_to_target_and_skips_protected_backend_data(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        source = td / "source"
        target = td / "target"
        backup_root = td / "backup"
        source.mkdir()
        target.mkdir()
        monkeypatch.setattr(system, "BACKUP_ROOT", backup_root)

        (source / "backend" / "app").mkdir(parents=True)
        (source / "backend" / "app" / "new.txt").write_text("new content")
        (source / "backend" / "certificados").mkdir(parents=True)
        (source / "backend" / "certificados" / "staged.pfx").write_text("staged cert")
        (source / "backend" / "downloads").mkdir(parents=True)
        (source / "backend" / "downloads" / "staged.xml").write_text("staged xml")

        (target / "backend" / "app").mkdir(parents=True)
        (target / "backend" / "app" / "old.txt").write_text("old content")

        system._copy_tree_transactional(source, target)

        assert (target / "backend" / "app" / "new.txt").read_text() == "new content"
        assert not (target / "backend" / "certificados" / "staged.pfx").exists()
        assert not (target / "backend" / "downloads" / "staged.xml").exists()


def test_workflow_and_release_scripts_use_app_package():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "auto-release.yml").read_text(encoding="utf-8")
    release_sh = (root / "scripts" / "release.sh").read_text(encoding="utf-8")
    sync_version_py = (root / "scripts" / "sync_version.py").read_text(encoding="utf-8")

    assert "from app.version import VERSION" in workflow
    assert "pytest" in workflow
    assert "from app.version import VERSION" in release_sh
    assert "from app.version import VERSION" in sync_version_py


def test_health_endpoint_and_docker_files_exist():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    root = Path(__file__).resolve().parents[1]
    expected_files = [
        root / "docker-compose.yml",
        root / "database" / "Dockerfile",
        root / "database" / "docker-compose.yml",
        root / "backend" / "Dockerfile",
        root / "backend" / "docker-compose.yml",
        root / "frontend" / "Dockerfile",
        root / "frontend" / "docker-compose.yml",
        root / "frontend" / "nginx.conf",
    ]
    for path in expected_files:
        assert path.exists(), f"Arquivo Docker ausente: {path}"


def test_bump_version_and_sync_all_manifests(tmp_path: Path):
    import json
    import sys

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    import bump_version
    import sync_version

    # Verifica cálculo semântico
    assert bump_version.parse_next_version("0.1.0", "patch") == "0.1.1"
    assert bump_version.parse_next_version("0.1.0", "minor") == "0.2.0"
    assert bump_version.parse_next_version("0.1.0", "major") == "1.0.0"
    assert bump_version.parse_next_version("0.1.0", "v1.2.3") == "1.2.3"

    # Cria árvore temporária simulando os manifestos do projeto
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "nfse"\nversion = "0.1.0"\n', encoding="utf-8")
    (tmp_path / "ui" / "src-tauri").mkdir(parents=True)
    (tmp_path / "frontend" / "views").mkdir(parents=True)
    (tmp_path / "ui" / "package.json").write_text('{"name": "nfse", "version": "1.0.0"}\n', encoding="utf-8")
    (tmp_path / "ui" / "package-lock.json").write_text(
        '{"name": "nfse", "version": "1.0.0", "packages": {"": {"version": "1.0.0"}}}\n', encoding="utf-8"
    )
    (tmp_path / "ui" / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nname = "nfse"\nversion = "1.0.0"\n\n[dependencies]\ntauri = { version = "1.8" }\n',
        encoding="utf-8",
    )
    (tmp_path / "ui" / "src-tauri" / "tauri.conf.json").write_text(
        '{"package": {"productName": "NFSe", "version": "1.0.0"}}\n', encoding="utf-8"
    )
    (tmp_path / "frontend" / "views" / "about.html").write_text(
        '<span class="badge">v0.1.0</span><div id="installed-version-tag">0.1.0</div>', encoding="utf-8"
    )

    bump_version.update_pyproject_version(tmp_path / "pyproject.toml", "0.2.0")
    changed = sync_version.sync_all_version_files(tmp_path, "0.2.0")

    assert "ui/package.json" in changed
    assert "ui/package-lock.json" in changed
    assert "ui/src-tauri/Cargo.toml" in changed
    assert "ui/src-tauri/tauri.conf.json" in changed
    assert "frontend/views/about.html" in changed

    assert json.loads((tmp_path / "ui" / "package.json").read_text())["version"] == "0.2.0"
    lock_data = json.loads((tmp_path / "ui" / "package-lock.json").read_text())
    assert lock_data["version"] == "0.2.0"
    assert lock_data["packages"][""]["version"] == "0.2.0"
    assert json.loads((tmp_path / "ui" / "src-tauri" / "tauri.conf.json").read_text())["package"]["version"] == "0.2.0"
    cargo_txt = (tmp_path / "ui" / "src-tauri" / "Cargo.toml").read_text()
    assert 'version = "0.2.0"' in cargo_txt
    assert 'tauri = { version = "1.8" }' in cargo_txt

    # Idempotência do changelog.txt e CHANGELOG.md
    txt_file = tmp_path / "changelog.txt"
    md_file = tmp_path / "CHANGELOG.md"
    analysis = {
        "new_version": "0.2.0",
        "previous_version": "0.1.0",
        "previous_tag": "v0.1.0",
        "generated_at": "2026-11-18 12:00:00",
        "notes": "Notas de teste",
        "commits": [{"sha": "abc1234", "date": "2026-11-18", "author": "dev", "subject": "feat: teste", "category": "Novas Funcionalidades"}],
        "commits_by_category": {
            "Novas Funcionalidades": [
                {"sha": "abc1234", "date": "2026-11-18", "author": "dev", "subject": "feat: teste", "category": "Novas Funcionalidades"}
            ]
        },
        "committed_shortstat": "1 file changed",
        "working_files": {},
        "working_shortstat": "",
        "files_by_layer": {"Backend (API, Serviços & Banco)": [("backend/app/main.py", "M")]},
    }
    bump_version.upsert_changelog_txt(txt_file, "0.2.0", bump_version.format_changelog_txt_entry(analysis))
    bump_version.upsert_changelog_txt(txt_file, "0.2.0", bump_version.format_changelog_txt_entry(analysis))
    assert txt_file.read_text(encoding="utf-8").count("VERSAO v0.2.0") == 1

    bump_version.upsert_changelog_md(md_file, "0.2.0", bump_version.format_changelog_md_entry(analysis))
    bump_version.upsert_changelog_md(md_file, "0.2.0", bump_version.format_changelog_md_entry(analysis))
    assert md_file.read_text(encoding="utf-8").count("## v0.2.0") == 1


def test_local_changelog_returned_on_version_and_newer_installed_check_update(monkeypatch):
    v_res = client.get("/api/system/version")
    assert v_res.status_code == 200
    assert v_res.json()["current_version"] == VERSION
    assert f"v{VERSION}" in (v_res.json().get("changelog") or "")

    monkeypatch.setattr(
        system,
        "_latest_release_data",
        lambda: {
            "tag_name": "v0.1.0",
            "zipball_url": "https://example.com/release-0.1.0.zip",
            "html_url": "https://example.com/release/0.1.0",
            "body": "Initial Release antigo v0.1.0",
        },
    )
    cu_res = client.get("/api/system/check-update")
    assert cu_res.status_code == 200
    payload = cu_res.json()
    assert payload["update_available"] is False
    assert payload["latest_version"] == "0.1.0"
    assert f"v{VERSION}" in (payload.get("changelog") or "")
    assert "Initial Release antigo" not in (payload.get("changelog") or "")

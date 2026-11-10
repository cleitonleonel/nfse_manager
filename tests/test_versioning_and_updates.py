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

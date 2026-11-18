import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
for path in (BACKEND_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Isola os testes do `.env` local do desenvolvedor (ex.: SMTP/Telegram reais)
os.environ.setdefault("NFSE_DISABLE_DOTENV", "1")
for _external_var in (
    "DEFAULT_SMTP_HOST",
    "DEFAULT_SMTP_PORT",
    "DEFAULT_SMTP_USER",
    "DEFAULT_SMTP_PASSWORD",
    "DEFAULT_SMTP_FROM",
    "DEFAULT_SMTP_TLS",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TLS",
    "SUPPORT_EMAIL_TO",
    "SUPPORT_TELEGRAM_BOT_TOKEN",
    "SUPPORT_TELEGRAM_CHAT_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
):
    os.environ.pop(_external_var, None)

if "DATABASE_URL" not in os.environ:
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = int(os.getenv("POSTGRES_PORT", "5434"))
    pg_available = False
    try:
        with socket.create_connection((pg_host, pg_port), timeout=0.5):
            pg_available = True
    except OSError:
        pg_available = False

    if not pg_available:
        import tempfile

        tmp_db = Path(tempfile.gettempdir()) / "nfse_manager_pytest.db"
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except OSError:
                pass
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"


import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_auth: desabilita o override automático de autenticação JWT para testar auth/RBAC reais.",
    )


@pytest.fixture(autouse=True)
def _auto_auth_override(request):
    from app.api.routers.auth import get_current_user, require_admin_user
    from app.main import app
    from app.models import User

    prev_current = app.dependency_overrides.get(get_current_user)
    prev_admin = app.dependency_overrides.get(require_admin_user)

    if request.node.get_closest_marker("real_auth") is not None:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin_user, None)
    else:
        dummy_admin = User(
            id=999999,
            username="pytest_admin",
            email="pytest_admin@local",
            full_name="Pytest Admin",
            password_hash="",
            role="admin",
            is_active=1,
        )
        app.dependency_overrides[get_current_user] = lambda: dummy_admin
        app.dependency_overrides[require_admin_user] = lambda: dummy_admin

    try:
        yield
    finally:
        if prev_current is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = prev_current

        if prev_admin is None:
            app.dependency_overrides.pop(require_admin_user, None)
        else:
            app.dependency_overrides[require_admin_user] = prev_admin


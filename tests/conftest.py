import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
for path in (BACKEND_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

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

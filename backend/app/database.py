import logging
import os
from pathlib import Path
import socket
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_sqlite_db_path, load_dotenv_if_present

load_dotenv_if_present()

logger = logging.getLogger(__name__)

POSTGRES_USER = os.getenv("POSTGRES_USER", "nfse_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "nfse_pass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5434")
POSTGRES_DB = os.getenv("POSTGRES_DB", "nfse_db")

DEFAULT_SQLITE_PATH = get_sqlite_db_path()
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"


def _can_resolve_host(hostname: str) -> bool:
    try:
        socket.gethostbyname(hostname)
        return True
    except OSError:
        return False


def _is_tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _replace_url_host_port(url: str, new_host: str, new_port: int | str) -> str:
    parsed = urlparse(url)
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    netloc = f"{userinfo}{new_host}:{new_port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def resolve_database_url() -> str:
    """Resolve a URL do banco de dados de forma híbrida (Docker, Postgres Local ou SQLite Local):

    1. Se `DATABASE_URL` for SQLite (`sqlite:///...`), utiliza diretamente.
    2. Se o hostname da URL for `database` (rede interna do Docker):
       - Dentro do container Docker (`database` resolvível via DNS), mantém `@database:5432`.
       - Fora do Docker (execução local no host), substitui `@database:5432` por `@localhost:<porta>`.
    3. Se a conexão configurada for PostgreSQL mas o servidor PostgreSQL não estiver acessível
       localmente (e não estivermos dentro de um container Docker), faz fallback automático
       para o banco local SQLite (`backend/nfse.db`), a menos que `DB_FALLBACK_SQLITE=0`.
    """
    default_pg_url = (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    raw_url = os.getenv("DATABASE_URL", default_pg_url).strip()

    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if raw_url.startswith("sqlite"):
        return raw_url

    parsed = urlparse(raw_url)
    url_host = parsed.hostname or POSTGRES_HOST
    url_port = parsed.port or int(POSTGRES_PORT or 5434)

    # Caso a URL aponte para o container "database" mas estejamos rodando no host fora do Docker
    if url_host == "database" and not _can_resolve_host("database"):
        local_host = POSTGRES_HOST if POSTGRES_HOST != "database" else "localhost"
        candidate_ports = []
        for p in (POSTGRES_PORT, 5434, 5432):
            try:
                p_int = int(p)
                if p_int not in candidate_ports:
                    candidate_ports.append(p_int)
            except (TypeError, ValueError):
                pass

        chosen_port = candidate_ports[0] if candidate_ports else 5434
        for p_int in candidate_ports:
            if _is_tcp_port_open(local_host, p_int):
                chosen_port = p_int
                break

        raw_url = _replace_url_host_port(raw_url, local_host, chosen_port)
        url_host = local_host
        url_port = chosen_port

    # Se estivermos fora do Docker e o PostgreSQL local/Docker não estiver rodando,
    # permite fallback transparente para a base local SQLite
    in_docker = Path("/.dockerenv").exists()
    fallback_enabled = os.getenv("DB_FALLBACK_SQLITE", "1").strip().lower() not in ("0", "false", "no")
    if not in_docker and fallback_enabled and not _is_tcp_port_open(url_host, int(url_port)):
        sqlite_path = get_sqlite_db_path()
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        logger.warning(
            f"PostgreSQL indisponível em {url_host}:{url_port}. Utilizando base local SQLite em: {sqlite_path}"
        )
        return f"sqlite:///{sqlite_path}"

    return raw_url


DATABASE_URL = resolve_database_url()
SQLALCHEMY_DATABASE_URL = DATABASE_URL

is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
if is_sqlite and not SQLALCHEMY_DATABASE_URL.endswith(":memory:"):
    raw_sqlite_file = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)
    if raw_sqlite_file:
        Path(raw_sqlite_file).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

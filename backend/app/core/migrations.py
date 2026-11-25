"""Motor de migrações de banco de dados e comandos administrativos estilo Django (`manage.py`).

Suporta:
- `makemigrations`: compara `Base.metadata` (SQLAlchemy) com o snapshot das migrações em `backend/migrations/versions/`
  e gera automaticamente um novo arquivo numerado (`0002_...py`) quando novas tabelas ou colunas são detectadas.
- `migrate`: aplica as migrações pendentes e registra na tabela `schema_migrations`.
- `showmigrations`: lista todas as migrações marcadas com `[X]` (aplicadas) ou `[ ]` (pendentes).
- `create_admin`: cria ou atualiza um superusuário administrador na tabela `users`.
"""

from __future__ import annotations

import datetime
import importlib.util
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text

from app.core.security import encrypt_secret, hash_password, is_encrypted
from app.database import Base, SessionLocal, engine
from app.models import User

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = BACKEND_DIR / "migrations" / "versions"


def _col_to_sql_type(col) -> str:
    t_name = col.type.__class__.__name__.upper()
    if "INT" in t_name:
        return "INTEGER"
    if "FLOAT" in t_name or "NUMERIC" in t_name or "DOUBLE" in t_name:
        return "DOUBLE PRECISION"
    if "DATE" in t_name or "TIME" in t_name:
        return "TIMESTAMP"
    return "VARCHAR"


def get_models_schema_snapshot() -> Dict[str, Dict[str, str]]:
    """Retorna o mapa `{table_name: {col_name: sql_type}}` a partir do `Base.metadata` atual."""
    snapshot: Dict[str, Dict[str, str]] = {}
    for table_name, table in Base.metadata.tables.items():
        if table_name == "schema_migrations":
            continue
        snapshot[table_name] = {col.name: _col_to_sql_type(col) for col in table.columns}
    return snapshot


def _load_migration_module(file_path: Path):
    spec = importlib.util.spec_from_file_location(f"nfse_mig_{file_path.stem}", str(file_path))
    if not spec or not spec.loader:
        raise RuntimeError(f"Não foi possível carregar a migração: {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def list_migration_files(migrations_dir: Optional[Path] = None) -> List[Path]:
    mdir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    mdir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in mdir.glob("[0-9][0-9][0-9][0-9]_*.py") if p.is_file())
    return files


def get_cumulative_migrations_snapshot(migrations_dir: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Reconstrói o estado acumulado das tabelas/colunas a partir dos arquivos de migração existentes."""
    state: Dict[str, Dict[str, str]] = {}
    for fpath in list_migration_files(migrations_dir):
        mod = _load_migration_module(fpath)
        for op in getattr(mod, "operations", []):
            kind = op.get("op")
            tname = op.get("table")
            if kind == "create_table" and tname:
                state[tname] = dict(op.get("columns") or {})
            elif kind == "add_column" and tname:
                state.setdefault(tname, {})[op["column"]] = op.get("sql_type", "VARCHAR")
            elif kind == "drop_column" and tname and tname in state:
                state[tname].pop(op.get("column", ""), None)
    return state


def makemigrations(
    name: Optional[str] = None,
    migrations_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Detecta diferenças entre `Base.metadata` e o histórico de migrações e gera um novo arquivo de migração."""
    mdir = migrations_dir or DEFAULT_MIGRATIONS_DIR
    mdir.mkdir(parents=True, exist_ok=True)

    existing_files = list_migration_files(mdir)
    prev_state = get_cumulative_migrations_snapshot(mdir)
    current_state = get_models_schema_snapshot()

    operations: List[Dict[str, Any]] = []
    for table_name, cols in current_state.items():
        if table_name not in prev_state:
            operations.append(
                {
                    "op": "create_table",
                    "table": table_name,
                    "columns": cols,
                }
            )
        else:
            prev_cols = prev_state[table_name]
            for col_name, sql_type in cols.items():
                if col_name not in prev_cols:
                    operations.append(
                        {
                            "op": "add_column",
                            "table": table_name,
                            "column": col_name,
                            "sql_type": sql_type,
                        }
                    )

    if not operations:
        return None

    next_num = len(existing_files) + 1
    version_str = f"{next_num:04d}"
    if not name:
        if next_num == 1:
            slug = "initial"
        else:
            first_op = operations[0]
            if first_op["op"] == "create_table":
                slug = f"create_{first_op['table']}"
            else:
                slug = f"add_{first_op['column']}_to_{first_op['table']}"
    else:
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_") or "auto"

    filename = f"{version_str}_{slug}.py"
    target_path = mdir / filename
    timestamp_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    content = f'''"""Migração {version_str}_{slug} gerada automaticamente em {timestamp_str}."""

from sqlalchemy import inspect, text

version = "{version_str}"
name = "{slug}"

operations = {repr(operations)}


def upgrade(conn, db_engine):
    """Aplica as operações desta migração no banco de dados."""
    from app.database import Base

    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())

    for op in operations:
        if op["op"] == "create_table":
            tname = op["table"]
            if tname not in existing_tables and tname in Base.metadata.tables:
                Base.metadata.tables[tname].create(bind=db_engine, checkfirst=True)
                existing_tables.add(tname)
        elif op["op"] == "add_column":
            tname = op["table"]
            col = op["column"]
            sql_type = op.get("sql_type", "VARCHAR")
            if tname in existing_tables:
                existing_cols = {{c["name"] for c in inspector.get_columns(tname)}}
                if col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {{tname}} ADD COLUMN {{col}} {{sql_type}}"))
                    conn.commit()


def downgrade(conn, db_engine):
    """Reverte as operações desta migração quando suportado pelo banco."""
    for op in reversed(operations):
        if op["op"] == "add_column":
            tname = op["table"]
            col = op["column"]
            try:
                conn.execute(text(f"ALTER TABLE {{tname}} DROP COLUMN {{col}}"))
                conn.commit()
            except Exception:
                pass
'''
    target_path.write_text(content, encoding="utf-8")
    return target_path


def _ensure_migrations_table(db_engine=None) -> None:
    eng = db_engine or engine
    Base.metadata.tables["schema_migrations"].create(bind=eng, checkfirst=True)


def get_applied_versions(db_engine=None) -> Set[str]:
    eng = db_engine or engine
    _ensure_migrations_table(eng)
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
        return {str(r[0]) for r in rows}


def showmigrations(migrations_dir: Optional[Path] = None, db_engine=None) -> List[Tuple[str, str, bool]]:
    """Retorna a lista `(version, name, is_applied)` de todas as migrações."""
    applied = get_applied_versions(db_engine)
    result: List[Tuple[str, str, bool]] = []
    for fpath in list_migration_files(migrations_dir):
        mod = _load_migration_module(fpath)
        ver = str(getattr(mod, "version", fpath.stem[:4]))
        nm = str(getattr(mod, "name", fpath.stem[5:]))
        result.append((ver, nm, ver in applied))
    return result


def migrate(migrations_dir: Optional[Path] = None, db_engine=None) -> List[str]:
    """Executa todas as migrações pendentes e atualiza a tabela `schema_migrations`."""
    eng = db_engine or engine
    _ensure_migrations_table(eng)
    applied = get_applied_versions(eng)
    newly_applied: List[str] = []

    files = list_migration_files(migrations_dir)
    if not files:
        # Se ainda não houver arquivos na pasta, garante ao menos a criação do schema atual
        Base.metadata.create_all(bind=eng)
        return newly_applied

    with eng.connect() as conn:
        for fpath in files:
            mod = _load_migration_module(fpath)
            ver = str(getattr(mod, "version", fpath.stem[:4]))
            nm = str(getattr(mod, "name", fpath.stem[5:]))
            if ver in applied:
                continue

            mod.upgrade(conn, eng)
            conn.execute(
                text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, :dt)"),
                {"v": ver, "n": nm, "dt": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")},
            )
            conn.commit()
            newly_applied.append(f"{ver}_{nm}")

        # Garante também a criptografia em repouso de quaisquer senhas legadas em texto puro
        try:
            rows = conn.execute(text("SELECT id, password, cert_password, smtp_password FROM clients")).fetchall()
            for row in rows:
                row_id, pwd, cert_pwd, smtp_pwd = row[0], row[1], row[2], row[3]
                needs_update = False
                new_pwd, new_cert_pwd, new_smtp_pwd = pwd, cert_pwd, smtp_pwd
                if pwd and not is_encrypted(pwd):
                    new_pwd = encrypt_secret(pwd)
                    needs_update = True
                if cert_pwd and not is_encrypted(cert_pwd):
                    new_cert_pwd = encrypt_secret(cert_pwd)
                    needs_update = True
                if smtp_pwd and not is_encrypted(smtp_pwd):
                    new_smtp_pwd = encrypt_secret(smtp_pwd)
                    needs_update = True
                if needs_update:
                    conn.execute(
                        text(
                            "UPDATE clients SET password = :p, cert_password = :cp, smtp_password = :sp WHERE id = :id"
                        ),
                        {"p": new_pwd, "cp": new_cert_pwd, "sp": new_smtp_pwd, "id": row_id},
                    )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.warning("Aviso durante migração de credenciais criptografadas: %s", exc)

    return newly_applied


def create_admin_user(
    username: str,
    email: Optional[str],
    password: str,
    full_name: Optional[str] = "Administrador",
) -> User:
    """Cria ou atualiza um usuário administrador na tabela `users`."""
    uname = (username or "").strip()
    if not uname:
        raise ValueError("O username do administrador é obrigatório.")
    if not password or len(password) < 4:
        raise ValueError("A senha do administrador deve ter pelo menos 4 caracteres.")

    email_clean = (email or "").strip().lower() or None
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == uname).first()
        pwd_hash = hash_password(password)
        if user:
            user.email = email_clean
            user.password_hash = pwd_hash
            user.role = "admin"
            user.is_active = 1
            if full_name:
                user.full_name = full_name
        else:
            user = User(
                username=uname,
                email=email_clean,
                full_name=full_name,
                password_hash=pwd_hash,
                role="admin",
                is_active=1,
            )
            db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()

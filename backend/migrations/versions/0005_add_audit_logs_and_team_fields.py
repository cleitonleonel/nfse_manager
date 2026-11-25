"""Migração 0005_add_audit_logs_and_team_fields."""

from sqlalchemy import inspect, text

version = "0005"
name = "add_audit_logs_and_team_fields"

operations = [
    {
        "op": "create_table",
        "table": "audit_logs",
        "columns": {
            "id": "INTEGER",
            "created_at": "TIMESTAMP",
            "actor_user_id": "INTEGER",
            "actor_username": "VARCHAR",
            "actor_role": "VARCHAR",
            "client_id": "INTEGER",
            "action": "VARCHAR",
            "entity_type": "VARCHAR",
            "entity_id": "VARCHAR",
            "summary": "VARCHAR",
            "details_json": "VARCHAR",
            "status": "VARCHAR",
            "ip_address": "VARCHAR",
        },
    },
    {
        "op": "add_column",
        "table": "users",
        "column": "last_login_at",
        "sql_type": "TIMESTAMP",
    },
]


def upgrade(conn, db_engine):
    """Aplica a tabela audit_logs, users.last_login_at, índices aditivos e paridade de FKs PG 16."""
    from app.database import Base
    from app.models import PG_FK_PARITY_SPECS, ensure_additive_indexes, ensure_pg_fk_ondelete

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    for op in operations:
        if op["op"] == "create_table":
            tname = op["table"]
            if tname not in existing_tables and tname in Base.metadata.tables:
                Base.metadata.tables[tname].create(bind=conn, checkfirst=True)
                conn.commit()
                existing_tables.add(tname)
        elif op["op"] == "add_column":
            tname = op["table"]
            col = op["column"]
            sql_type = op.get("sql_type", "VARCHAR")
            if tname in existing_tables:
                existing_cols = {c["name"] for c in inspect(conn).get_columns(tname)}
                if col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {tname} ADD COLUMN {col} {sql_type}"))
                    conn.commit()

    ensure_additive_indexes(conn)

    if db_engine.dialect.name == "postgresql":
        for spec in PG_FK_PARITY_SPECS:
            ensure_pg_fk_ondelete(conn, *spec)


def downgrade(conn, db_engine):
    """Reverte as operações desta migração quando suportado pelo banco."""
    for op in reversed(operations):
        if op["op"] == "add_column":
            tname = op["table"]
            col = op["column"]
            try:
                conn.execute(text(f"ALTER TABLE {tname} DROP COLUMN {col}"))
                conn.commit()
            except Exception:
                conn.rollback()
        elif op["op"] == "create_table":
            tname = op["table"]
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {tname}"))
                conn.commit()
            except Exception:
                conn.rollback()

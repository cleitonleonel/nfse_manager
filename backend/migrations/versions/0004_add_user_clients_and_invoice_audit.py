"""Migração 0004_add_user_clients_and_invoice_audit gerada automaticamente em 2026-11-24 17:35:47 UTC."""

from sqlalchemy import inspect, text

version = "0004"
name = "add_user_clients_and_invoice_audit"

operations = [{'op': 'create_table', 'table': 'user_clients', 'columns': {'id': 'INTEGER', 'user_id': 'INTEGER', 'client_id': 'INTEGER', 'access_level': 'VARCHAR', 'created_at': 'TIMESTAMP'}}, {'op': 'add_column', 'table': 'invoices', 'column': 'created_by_user_id', 'sql_type': 'INTEGER'}, {'op': 'add_column', 'table': 'invoices', 'column': 'created_by_username', 'sql_type': 'VARCHAR'}, {'op': 'add_column', 'table': 'invoices', 'column': 'ambiente', 'sql_type': 'VARCHAR'}]


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
                existing_cols = {c["name"] for c in inspector.get_columns(tname)}
                if col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {tname} ADD COLUMN {col} {sql_type}"))
                    conn.commit()


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
                pass

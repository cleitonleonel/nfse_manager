import datetime
import logging
import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, UniqueConstraint, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator
from app.core.security import decrypt_secret, encrypt_secret, is_encrypted
from app.database import Base, engine

logger = logging.getLogger(__name__)


class EncryptedString(TypeDecorator):
    """
    Tipo SQLAlchemy que armazena dados criptografados em repouso (AES/Fernet)
    e decifra automaticamente ao carregar em memória.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value != "":
            return encrypt_secret(str(value))
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value != "":
            return decrypt_secret(str(value))
        return value


class User(Base):
    """Operador / Administrador do sistema (criado via `python manage.py create_admin`)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="admin")  # admin | operador
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    last_login_at = Column(DateTime, nullable=True)

    client_links = relationship("UserClient", back_populates="user", cascade="all, delete-orphan")

    @property
    def client_ids(self) -> list[int]:
        return [int(link.client_id) for link in (self.client_links or []) if link.client_id is not None]


class UserClient(Base):
    """Vínculo N:N entre usuários (operadores) e empresas (Client) autorizadas."""

    __tablename__ = "user_clients"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_user_clients_user_client"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    access_level = Column(String, nullable=False, default="operator")  # manager | operator
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))

    user = relationship("User", back_populates="client_links")
    client = relationship("Client", back_populates="user_links")


class SchemaMigration(Base):
    """Histórico de migrações aplicadas pelo `python manage.py migrate`."""

    __tablename__ = "schema_migrations"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    applied_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    cnpj = Column(String, unique=True, index=True)
    razao_social = Column(String)
    username = Column(String)
    password = Column(EncryptedString, nullable=True)
    cert_path = Column(String, nullable=True)
    cert_password = Column(EncryptedString, nullable=True)
    description = Column(String, nullable=True)
    save_path = Column(String, nullable=True)
    path_structure = Column(String, nullable=True)

    # Campos fiscais para emissão ADN / Sefin Nacional v1.01
    inscricao_municipal = Column(String, nullable=True)
    codigo_municipio = Column(String, nullable=True, default="3201308")
    uf = Column(String, nullable=True, default="ES")
    cep = Column(String, nullable=True)
    logradouro = Column(String, nullable=True)
    numero = Column(String, nullable=True)
    complemento = Column(String, nullable=True)
    bairro = Column(String, nullable=True)
    telefone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    regime_tributario = Column(String, nullable=True, default="normal")  # normal | simples | mei
    regime_apuracao_sn = Column(String, nullable=True, default="1")
    regime_especial = Column(String, nullable=True, default="0")
    serie_dps_padrao = Column(String, nullable=True, default="900")
    ultimo_numero_dps = Column(Integer, nullable=True, default=0)
    ambiente_padrao = Column(String, nullable=True, default="homologacao")
    ultimo_nsu_adn = Column(Integer, nullable=True, default=0)

    # Configurações de E-mail (SMTP próprio por Prestador)
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, nullable=True, default=587)
    smtp_user = Column(String, nullable=True)
    smtp_password = Column(EncryptedString, nullable=True)
    smtp_from = Column(String, nullable=True)
    smtp_tls = Column(Integer, nullable=True, default=1)
    enviar_email_automatico = Column(Integer, nullable=True, default=0)

    # Metadados de validade do Certificado Digital A1 (.pfx)
    cert_valid_until = Column(DateTime, nullable=True)
    cert_subject = Column(String, nullable=True)

    invoices = relationship("Invoice", back_populates="client", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="client", cascade="all, delete-orphan")
    service_items = relationship("ServiceItem", back_populates="client", cascade="all, delete-orphan")
    user_links = relationship("UserClient", back_populates="client", cascade="all, delete-orphan")
    batch_imports = relationship("BatchImport", back_populates="client", cascade="all, delete-orphan")

    @property
    def dias_para_vencer(self) -> int | None:
        if not self.cert_valid_until:
            return None
        now = datetime.datetime.now(datetime.UTC)
        valid_dt = self.cert_valid_until
        if valid_dt.tzinfo is None:
            valid_dt = valid_dt.replace(tzinfo=datetime.UTC)
        return (valid_dt - now).days

    @property
    def status_certificado(self) -> str:
        if not self.cert_path:
            return "sem_certificado"
        dias = self.dias_para_vencer
        if dias is None:
            return "configurado"
        if dias <= 0:
            return "vencido"
        if dias <= 30:
            return "expirando"
        return "valido"

    @property
    def smtp_configurado(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)


class Customer(Base):
    """Cadastro recorrente de Tomadores de Serviço (clientes para quem se emite NFS-e)."""

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    documento = Column(String, index=True)  # CPF ou CNPJ
    razao_social = Column(String)
    inscricao_municipal = Column(String, nullable=True)
    email = Column(String, nullable=True)
    telefone = Column(String, nullable=True)
    cep = Column(String, nullable=True)
    logradouro = Column(String, nullable=True)
    numero = Column(String, nullable=True)
    complemento = Column(String, nullable=True)
    bairro = Column(String, nullable=True)
    codigo_municipio = Column(String, nullable=True, default="3201308")
    uf = Column(String, nullable=True, default="ES")

    client = relationship("Client", back_populates="customers")


class ServiceItem(Base):
    """Cadastro recorrente de Serviços para emissão rápida de NFS-e em poucos cliques."""

    __tablename__ = "service_items"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    codigo_interno = Column(String, nullable=True)
    titulo = Column(String)
    descricao = Column(String)
    valor_unitario = Column(Float, nullable=True, default=0.0)
    c_trib_nac = Column(String, nullable=True, default="010101")
    c_nbs = Column(String, nullable=True)
    c_class_trib = Column(String, nullable=True, default="000001")
    cst_ibscbs = Column(String, nullable=True, default="000")
    c_ind_op = Column(String, nullable=True, default="100301")
    aliquota_iss = Column(Float, nullable=True, default=2.0)
    iss_retido = Column(Integer, nullable=True, default=0)
    reter_federais = Column(Integer, nullable=True, default=0)

    client = relationship("Client", back_populates="service_items")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    data_emissao = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    numero = Column(String)
    chave = Column(String, unique=True, index=True)
    status = Column(String)
    tipo = Column(String)  # emitidas or recebidas
    valor = Column(Float, nullable=True)  # Valor da nota em R$
    xml_path = Column(String, nullable=True)
    pdf_path = Column(String, nullable=True)
    download_url_xml = Column(String, nullable=True)
    download_url_pdf = Column(String, nullable=True)

    # Campos de Emissão, Substituição, Cancelamento e Tributação IBS/CBS
    id_dps = Column(String, nullable=True, index=True)
    serie_dps = Column(String, nullable=True)
    numero_dps = Column(Integer, nullable=True)
    chave_substituida = Column(String, nullable=True)
    chave_substituta = Column(String, nullable=True)
    motivo_cancelamento = Column(String, nullable=True)
    data_cancelamento = Column(DateTime, nullable=True)
    xml_dps_path = Column(String, nullable=True)
    xml_evento_path = Column(String, nullable=True)
    valor_iss = Column(Float, nullable=True)
    valor_ibs = Column(Float, nullable=True)
    valor_cbs = Column(Float, nullable=True)
    valor_liquido = Column(Float, nullable=True)
    c_trib_nac = Column(String, nullable=True)
    c_nbs = Column(String, nullable=True)
    c_class_trib = Column(String, nullable=True)
    cst_ibscbs = Column(String, nullable=True)
    tomador_documento = Column(String, nullable=True)
    tomador_nome = Column(String, nullable=True)
    tomador_email = Column(String, nullable=True)
    tentativas_envio = Column(Integer, nullable=True, default=0)
    ultimo_erro_envio = Column(String, nullable=True)
    payload_dps_json = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_username = Column(String, nullable=True)
    ambiente = Column(String, nullable=True)

    client = relationship("Client", back_populates="invoices")


class BatchImport(Base):
    """Lote persistente de importação de notas NFS-e via CSV/XLSX."""

    __tablename__ = "batch_imports"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, index=True)
    ambiente = Column(String, nullable=False, default="homologacao")
    status = Column(String, nullable=False, default="IMPORTED", index=True)
    total_items = Column(Integer, nullable=False, default=0)
    valid_items = Column(Integer, nullable=False, default=0)
    invalid_items = Column(Integer, nullable=False, default=0)
    processed_items = Column(Integer, nullable=False, default=0)
    authorized_items = Column(Integer, nullable=False, default=0)
    rejected_items = Column(Integer, nullable=False, default=0)
    unknown_items = Column(Integer, nullable=False, default=0)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    completed_at = Column(DateTime, nullable=True)

    client = relationship("Client", back_populates="batch_imports")
    items = relationship("BatchImportItem", back_populates="batch", cascade="all, delete-orphan")


class BatchImportItem(Base):
    """Item individual de um lote de emissão NFS-e importado via planilha."""

    __tablename__ = "batch_import_items"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(String, ForeignKey("batch_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    raw_data_json = Column(String, nullable=True)
    payload_json = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING", index=True)
    validation_errors_json = Column(String, nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    id_dps = Column(String, nullable=True, index=True)
    serie_dps = Column(String, nullable=True)
    numero_dps = Column(Integer, nullable=True)
    chave_acesso = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    processed_at = Column(DateTime, nullable=True)

    batch = relationship("BatchImport", back_populates="items")
    invoice = relationship("Invoice")


class BackgroundTask(Base):
    """Estado persistente de tarefas em background compartilhado entre múltiplos workers."""

    __tablename__ = "background_tasks"

    id = Column(String, primary_key=True, index=True)
    kind = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="running", index=True)
    message = Column(String, nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    result_json = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )


class SchedulerLock(Base):
    """Lease lock distribuído no banco para eleição de líder do worker agendado (fallback SQLite)."""

    __tablename__ = "scheduler_locks"

    lock_name = Column(String, primary_key=True, index=True)
    owner_id = Column(String, nullable=False)
    locked_until = Column(DateTime, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )


class AuditLog(Base):
    """Trilha de auditoria administrativa de ações críticas no sistema."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        nullable=False,
        index=True,
    )
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_username = Column(String, nullable=True, index=True)
    actor_role = Column(String, nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=True, index=True)
    summary = Column(String, nullable=False)
    details_json = Column(String, nullable=True)
    status = Column(String, nullable=False, default="success", index=True)
    ip_address = Column(String, nullable=True)

    actor_user = relationship("User")
    client = relationship("Client")


PG_FK_PARITY_SPECS = (
    ("batch_import_items", "batch_id", "batch_imports", "id", "CASCADE"),
    ("batch_import_items", "invoice_id", "invoices", "id", "SET NULL"),
    ("customers", "client_id", "clients", "id", "CASCADE"),
    ("service_items", "client_id", "clients", "id", "CASCADE"),
    ("invoices", "client_id", "clients", "id", "CASCADE"),
    ("invoices", "created_by_user_id", "users", "id", "SET NULL"),
    ("batch_imports", "client_id", "clients", "id", "CASCADE"),
    ("audit_logs", "actor_user_id", "users", "id", "SET NULL"),
    ("audit_logs", "client_id", "clients", "id", "SET NULL"),
)

ADDITIVE_INDEX_SPECS = (
    ("invoices", "ix_invoices_client_id", "client_id"),
    ("invoices", "ix_invoices_created_by_user_id", "created_by_user_id"),
    ("batch_import_items", "ix_batch_import_items_invoice_id", "invoice_id"),
    ("audit_logs", "ix_audit_logs_id", "id"),
    ("audit_logs", "ix_audit_logs_created_at", "created_at"),
    ("audit_logs", "ix_audit_logs_actor_user_id", "actor_user_id"),
    ("audit_logs", "ix_audit_logs_actor_username", "actor_username"),
    ("audit_logs", "ix_audit_logs_client_id", "client_id"),
    ("audit_logs", "ix_audit_logs_action", "action"),
    ("audit_logs", "ix_audit_logs_entity_type", "entity_type"),
    ("audit_logs", "ix_audit_logs_entity_id", "entity_id"),
    ("audit_logs", "ix_audit_logs_status", "status"),
)


def ensure_pg_fk_ondelete(
    conn,
    table_name: str,
    col_name: str,
    ref_table: str,
    ref_col: str,
    ondelete: str,
) -> None:
    """Reconcilia uma FK no PostgreSQL 16 garantindo `ON DELETE <ondelete>` sem falhar em transações."""
    from sqlalchemy import inspect

    if conn.dialect.name != "postgresql":
        return

    insp = inspect(conn)
    tables = set(insp.get_table_names())
    if table_name not in tables or ref_table not in tables:
        return
    cols = {c["name"] for c in insp.get_columns(table_name)}
    if col_name not in cols:
        return

    matching_fks = [
        fk
        for fk in insp.get_foreign_keys(table_name)
        if fk.get("constrained_columns") == [col_name] and fk.get("referred_table") == ref_table
    ]
    target_rule = ondelete.upper()
    if (
        len(matching_fks) == 1
        and ((matching_fks[0].get("options") or {}).get("ondelete") or "").upper() == target_rule
    ):
        return

    try:
        for fk in matching_fks:
            fk_name = fk.get("name")
            if fk_name:
                conn.execute(text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{fk_name}"'))
        conn.execute(text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{table_name}_{col_name}_fkey"'))

        if target_rule == "SET NULL":
            conn.execute(
                text(
                    f'UPDATE "{table_name}" SET "{col_name}" = NULL '
                    f'WHERE "{col_name}" IS NOT NULL '
                    f'AND NOT EXISTS (SELECT 1 FROM "{ref_table}" r WHERE r."{ref_col}" = "{table_name}"."{col_name}")'
                )
            )
        elif target_rule == "CASCADE":
            conn.execute(
                text(
                    f'DELETE FROM "{table_name}" '
                    f'WHERE "{col_name}" IS NOT NULL '
                    f'AND NOT EXISTS (SELECT 1 FROM "{ref_table}" r WHERE r."{ref_col}" = "{table_name}"."{col_name}")'
                )
            )

        conn.execute(
            text(
                f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{table_name}_{col_name}_fkey" '
                f'FOREIGN KEY ("{col_name}") REFERENCES "{ref_table}" ("{ref_col}") ON DELETE {target_rule}'
            )
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("Aviso ao reconciliar FK %s.%s: %s", table_name, col_name, exc)


def ensure_additive_indexes(conn) -> None:
    """Cria índices aditivos faltantes de forma idempotente em SQLite e PostgreSQL."""
    from sqlalchemy import inspect

    insp = inspect(conn)
    tables = set(insp.get_table_names())
    for table_name, idx_name, col_name in ADDITIVE_INDEX_SPECS:
        if table_name not in tables:
            continue
        existing_cols = {c["name"] for c in insp.get_columns(table_name)}
        if col_name not in existing_cols:
            continue
        existing_idx = {idx["name"] for idx in insp.get_indexes(table_name)}
        if idx_name not in existing_idx:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({col_name})"))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.warning("Aviso ao criar índice %s em %s: %s", idx_name, table_name, exc)


def init_db():
    import time
    from sqlalchemy import inspect
    from sqlalchemy.exc import OperationalError

    user_migrations = [
        ("last_login_at", "TIMESTAMP"),
    ]

    client_migrations = [
        ("inscricao_municipal", "VARCHAR"),
        ("codigo_municipio", "VARCHAR"),
        ("uf", "VARCHAR"),
        ("cep", "VARCHAR"),
        ("logradouro", "VARCHAR"),
        ("numero", "VARCHAR"),
        ("complemento", "VARCHAR"),
        ("bairro", "VARCHAR"),
        ("telefone", "VARCHAR"),
        ("email", "VARCHAR"),
        ("regime_tributario", "VARCHAR"),
        ("regime_apuracao_sn", "VARCHAR"),
        ("regime_especial", "VARCHAR"),
        ("serie_dps_padrao", "VARCHAR"),
        ("ultimo_numero_dps", "INTEGER"),
        ("ambiente_padrao", "VARCHAR"),
        ("ultimo_nsu_adn", "INTEGER"),
        ("smtp_host", "VARCHAR"),
        ("smtp_port", "INTEGER"),
        ("smtp_user", "VARCHAR"),
        ("smtp_password", "VARCHAR"),
        ("smtp_from", "VARCHAR"),
        ("smtp_tls", "INTEGER"),
        ("enviar_email_automatico", "INTEGER"),
        ("cert_valid_until", "TIMESTAMP"),
        ("cert_subject", "VARCHAR"),
        ("save_path", "VARCHAR"),
        ("path_structure", "VARCHAR"),
    ]

    invoice_migrations = [
        ("valor", "DOUBLE PRECISION"),
        ("id_dps", "VARCHAR"),
        ("serie_dps", "VARCHAR"),
        ("numero_dps", "INTEGER"),
        ("chave_substituida", "VARCHAR"),
        ("chave_substituta", "VARCHAR"),
        ("motivo_cancelamento", "VARCHAR"),
        ("data_cancelamento", "TIMESTAMP"),
        ("xml_dps_path", "VARCHAR"),
        ("xml_evento_path", "VARCHAR"),
        ("valor_iss", "DOUBLE PRECISION"),
        ("valor_ibs", "DOUBLE PRECISION"),
        ("valor_cbs", "DOUBLE PRECISION"),
        ("valor_liquido", "DOUBLE PRECISION"),
        ("c_trib_nac", "VARCHAR"),
        ("c_nbs", "VARCHAR"),
        ("c_class_trib", "VARCHAR"),
        ("cst_ibscbs", "VARCHAR"),
        ("tomador_documento", "VARCHAR"),
        ("tomador_nome", "VARCHAR"),
        ("tomador_email", "VARCHAR"),
        ("tentativas_envio", "INTEGER"),
        ("ultimo_erro_envio", "VARCHAR"),
        ("payload_dps_json", "VARCHAR"),
        ("created_by_user_id", "INTEGER"),
        ("created_by_username", "VARCHAR"),
        ("ambiente", "VARCHAR"),
    ]

    for attempt in range(1, 31):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError as exc:
            if attempt == 30:
                raise
            logger.info("Aguardando banco de dados ficar disponível (%d/30): %s", attempt, exc)
            time.sleep(2.0)

    inspector = inspect(engine)
    with engine.connect() as conn:
        for table_name, migrations in (
            ("users", user_migrations),
            ("clients", client_migrations),
            ("invoices", invoice_migrations),
        ):
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col, col_type in migrations:
                if col not in existing_cols:
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}"))
                        conn.commit()
                    except Exception as exc:
                        logger.warning("Aviso ao adicionar coluna %s.%s: %s", table_name, col, exc)
                        conn.rollback()

        try:
            ensure_additive_indexes(conn)
        except Exception as exc:
            conn.rollback()
            logger.warning("Aviso ao garantir índices aditivos: %s", exc)

        if engine.dialect.name == "postgresql":
            for spec in PG_FK_PARITY_SPECS:
                try:
                    ensure_pg_fk_ondelete(conn, *spec)
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Aviso ao garantir FK %s.%s: %s", spec[0], spec[1], exc)

        # Migração transparente de senhas legadas para o formato criptografado em repouso
        try:
            rows = conn.execute(text("SELECT id, password, cert_password, smtp_password FROM clients")).fetchall()
            for row in rows:
                row_id = row[0]
                pwd = row[1]
                cert_pwd = row[2]
                smtp_pwd = row[3]
                needs_update = False
                new_pwd = pwd
                new_cert_pwd = cert_pwd
                new_smtp_pwd = smtp_pwd

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
        except Exception as e:
            conn.rollback()
            logger.warning(f"Aviso durante verificação/migração de credenciais criptografadas: {e}")

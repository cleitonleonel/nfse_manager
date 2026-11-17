import datetime
import logging
import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, text
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
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
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
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
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
    client_id = Column(Integer, ForeignKey("clients.id"))
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

    client = relationship("Client", back_populates="invoices")


class BatchImport(Base):
    """Lote persistente de importação de notas NFS-e via CSV/XLSX."""

    __tablename__ = "batch_imports"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
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

    client = relationship("Client")
    items = relationship("BatchImportItem", back_populates="batch", cascade="all, delete-orphan")


class BatchImportItem(Base):
    """Item individual de um lote de emissão NFS-e importado via planilha."""

    __tablename__ = "batch_import_items"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(String, ForeignKey("batch_imports.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    raw_data_json = Column(String, nullable=True)
    payload_json = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING", index=True)
    validation_errors_json = Column(String, nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    id_dps = Column(String, nullable=True, index=True)
    serie_dps = Column(String, nullable=True)
    numero_dps = Column(Integer, nullable=True)
    chave_acesso = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    processed_at = Column(DateTime, nullable=True)

    batch = relationship("BatchImport", back_populates="items")
    invoice = relationship("Invoice")


def init_db():
    import time
    from sqlalchemy import inspect
    from sqlalchemy.exc import OperationalError

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
        for table_name, migrations in (("clients", client_migrations), ("invoices", invoice_migrations)):
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col, col_type in migrations:
                if col not in existing_cols:
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}"))
                        conn.commit()
                    except Exception:
                        pass

        # Migração transparente de senhas legadas para o formato criptografado em repouso
        try:
            rows = conn.execute(text("SELECT id, password, cert_password FROM clients")).fetchall()
            for row in rows:
                row_id = row[0]
                pwd = row[1]
                cert_pwd = row[2]
                needs_update = False
                new_pwd = pwd
                new_cert_pwd = cert_pwd

                if pwd and not is_encrypted(pwd):
                    new_pwd = encrypt_secret(pwd)
                    needs_update = True
                if cert_pwd and not is_encrypted(cert_pwd):
                    new_cert_pwd = encrypt_secret(cert_pwd)
                    needs_update = True

                if needs_update:
                    conn.execute(
                        text("UPDATE clients SET password = :p, cert_password = :cp WHERE id = :id"),
                        {"p": new_pwd, "cp": new_cert_pwd, "id": row_id},
                    )
            conn.commit()
        except Exception as e:
            logger.warning(f"Aviso durante verificação/migração de credenciais criptografadas: {e}")

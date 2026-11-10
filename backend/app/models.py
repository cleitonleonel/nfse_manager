from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, text
from sqlalchemy.orm import relationship
import datetime
from app.database import Base, engine


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    cnpj = Column(String, unique=True, index=True)
    razao_social = Column(String)
    username = Column(String)
    password = Column(String)
    cert_path = Column(String, nullable=True)
    cert_password = Column(String, nullable=True)
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

    invoices = relationship("Invoice", back_populates="client")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    data_emissao = Column(DateTime, default=datetime.datetime.utcnow)
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

    client = relationship("Client", back_populates="invoices")


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
    ]

    for attempt in range(1, 11):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError:
            if attempt == 10:
                raise
            time.sleep(1.5)

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

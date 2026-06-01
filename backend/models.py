from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, text
from sqlalchemy.orm import relationship
import datetime
from backend.database import Base, engine


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

    client = relationship("Client", back_populates="invoices")


def init_db():
    with engine.connect() as conn:
        """try:
            conn.execute(text("ALTER TABLE notes RENAME TO invoices"))
            conn.commit()
        except Exception:
            pass"""

        try:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN valor FLOAT"))
            conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text("ALTER TABLE clients ADD COLUMN save_path STRING"))
            conn.execute(text("ALTER TABLE clients ADD COLUMN path_structure STRING"))
            conn.commit()
        except Exception:
            pass

    Base.metadata.create_all(bind=engine)

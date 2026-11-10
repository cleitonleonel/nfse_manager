"""Router de Clientes - CRUD de clientes NFSe."""

from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client
from app.schemas import ClientResponse

BACKEND_DIR = Path(__file__).resolve().parents[3]
CERTIFICADOS_DIR = BACKEND_DIR / "certificados"

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("", response_model=List[ClientResponse])
def list_clients(db: Session = Depends(get_db)):
    """Listar todos os clientes cadastrados."""
    return db.query(Client).all()


@router.post("", response_model=ClientResponse)
def create_client(
    cnpj: str = Form(...),
    razao_social: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    description: str = Form(""),
    cert_password: str = Form(""),
    save_path: Optional[str] = Form(None),
    path_structure: Optional[str] = Form(None),
    inscricao_municipal: Optional[str] = Form(None),
    codigo_municipio: Optional[str] = Form("3201308"),
    uf: Optional[str] = Form("ES"),
    cep: Optional[str] = Form(None),
    logradouro: Optional[str] = Form(None),
    numero: Optional[str] = Form(None),
    complemento: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    telefone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    regime_tributario: Optional[str] = Form("normal"),
    regime_apuracao_sn: Optional[str] = Form("1"),
    regime_especial: Optional[str] = Form("0"),
    serie_dps_padrao: Optional[str] = Form("900"),
    ultimo_numero_dps: Optional[int] = Form(0),
    ambiente_padrao: Optional[str] = Form("homologacao"),
    cert_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Criar novo cliente com certificado e dados fiscais opcionais."""
    cert_path = None
    if cert_file and cert_file.filename:
        CERTIFICADOS_DIR.mkdir(parents=True, exist_ok=True)
        safe_filename = "".join(c for c in cert_file.filename if c.isalnum() or c in "._- ")
        safe_cnpj = cnpj.replace("/", "").replace(".", "").replace("-", "")
        cert_file_path = CERTIFICADOS_DIR / f"{safe_cnpj}_{safe_filename}"
        cert_file_path.write_bytes(cert_file.file.read())
        cert_path = str(cert_file_path)

    db_client = Client(
        cnpj=cnpj,
        razao_social=razao_social,
        username=username,
        password=password,
        description=description,
        cert_password=cert_password,
        cert_path=cert_path or "",
        save_path=save_path or "",
        path_structure=path_structure or "",
        inscricao_municipal=inscricao_municipal,
        codigo_municipio=codigo_municipio or "3201308",
        uf=uf or "ES",
        cep=cep,
        logradouro=logradouro,
        numero=numero,
        complemento=complemento,
        bairro=bairro,
        telefone=telefone,
        email=email,
        regime_tributario=regime_tributario or "normal",
        regime_apuracao_sn=regime_apuracao_sn or "1",
        regime_especial=regime_especial or "0",
        serie_dps_padrao=serie_dps_padrao or "900",
        ultimo_numero_dps=ultimo_numero_dps or 0,
        ambiente_padrao=ambiente_padrao or "homologacao",
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    """Remover cliente pelo ID."""
    db_client = db.query(Client).filter(Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(db_client)
    db.commit()
    return {"message": "Client deleted"}


@router.put("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: int,
    razao_social: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    cert_password: Optional[str] = Form(None),
    save_path: Optional[str] = Form(None),
    path_structure: Optional[str] = Form(None),
    inscricao_municipal: Optional[str] = Form(None),
    codigo_municipio: Optional[str] = Form(None),
    uf: Optional[str] = Form(None),
    cep: Optional[str] = Form(None),
    logradouro: Optional[str] = Form(None),
    numero: Optional[str] = Form(None),
    complemento: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    telefone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    regime_tributario: Optional[str] = Form(None),
    regime_apuracao_sn: Optional[str] = Form(None),
    regime_especial: Optional[str] = Form(None),
    serie_dps_padrao: Optional[str] = Form(None),
    ultimo_numero_dps: Optional[int] = Form(None),
    ambiente_padrao: Optional[str] = Form(None),
    cert_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Atualizar dados do cliente."""
    db_client = db.query(Client).filter(Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")

    update_fields = {
        "razao_social": razao_social,
        "username": username,
        "password": password,
        "description": description,
        "cert_password": cert_password,
        "save_path": save_path,
        "path_structure": path_structure,
        "inscricao_municipal": inscricao_municipal,
        "codigo_municipio": codigo_municipio,
        "uf": uf,
        "cep": cep,
        "logradouro": logradouro,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "telefone": telefone,
        "email": email,
        "regime_tributario": regime_tributario,
        "regime_apuracao_sn": regime_apuracao_sn,
        "regime_especial": regime_especial,
        "serie_dps_padrao": serie_dps_padrao,
        "ultimo_numero_dps": ultimo_numero_dps,
        "ambiente_padrao": ambiente_padrao,
    }
    for field, value in update_fields.items():
        if value is not None:
            setattr(db_client, field, value)

    if cert_file and cert_file.filename:
        CERTIFICADOS_DIR.mkdir(parents=True, exist_ok=True)
        safe_filename = "".join(c for c in cert_file.filename if c.isalnum() or c in "._- ")
        safe_cnpj = db_client.cnpj.replace("/", "").replace(".", "").replace("-", "")
        cert_file_path = CERTIFICADOS_DIR / f"{safe_cnpj}_{safe_filename}"
        cert_file_path.write_bytes(cert_file.file.read())
        db_client.cert_path = str(cert_file_path)

    db.commit()
    db.refresh(db_client)
    return db_client

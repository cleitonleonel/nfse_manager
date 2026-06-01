"""Router de Clientes - CRUD de clientes NFSe."""

import os
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Client
from backend.schemas import ClientResponse

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
    cert_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Criar novo cliente com certificado opcional."""
    cert_path = None
    if cert_file and cert_file.filename:
        os.makedirs("certificados", exist_ok=True)
        safe_filename = "".join(c for c in cert_file.filename if c.isalnum() or c in "._- ")
        safe_cnpj = cnpj.replace("/", "").replace(".", "").replace("-", "")
        cert_path = f"certificados/{safe_cnpj}_{safe_filename}"
        with open(cert_path, "wb") as buffer:
            buffer.write(cert_file.file.read())

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
    }
    for field, value in update_fields.items():
        if value is not None:
            setattr(db_client, field, value)

    if cert_file and cert_file.filename:
        os.makedirs("certificados", exist_ok=True)
        safe_filename = "".join(c for c in cert_file.filename if c.isalnum() or c in "._- ")
        safe_cnpj = db_client.cnpj.replace("/", "").replace(".", "").replace("-", "")
        cert_path = f"certificados/{safe_cnpj}_{safe_filename}"
        with open(cert_path, "wb") as buffer:
            buffer.write(cert_file.file.read())
        db_client.cert_path = cert_path

    db.commit()
    db.refresh(db_client)
    return db_client

"""Router de Clientes - CRUD de clientes NFSe."""

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.constants import (
    DEFAULT_AMBIENTE,
    DEFAULT_CODIGO_MUNICIPIO,
    DEFAULT_REGIME_APURACAO_SN,
    DEFAULT_REGIME_ESPECIAL,
    DEFAULT_REGIME_TRIBUTARIO,
    DEFAULT_SERIE_DPS,
    DEFAULT_UF,
)
from app.database import get_db
from app.models import Client, Invoice
from app.schemas import ClientResponse

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[3]
CERTIFICADOS_DIR = BACKEND_DIR / "certificados"
DOWNLOADS_DIR = BACKEND_DIR / "downloads"


def salvar_arquivo_certificado(cert_file: UploadFile, cnpj: str) -> Optional[str]:
    """
    Salva com segurança o arquivo de certificado do cliente em uma pasta dedicada por CNPJ
    (ex: backend/certificados/{safe_cnpj}/{safe_filename}).
    """
    if not cert_file or not cert_file.filename:
        return None

    safe_cnpj = re.sub(r"\D", "", cnpj or "")
    if not safe_cnpj:
        safe_cnpj = "cliente_sem_cnpj"

    client_cert_dir = CERTIFICADOS_DIR / safe_cnpj
    client_cert_dir.mkdir(parents=True, exist_ok=True)

    # Limpa certificados anteriores na pasta do cliente para não acumular arquivos
    for existing_file in client_cert_dir.iterdir():
        if existing_file.is_file():
            try:
                existing_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Erro ao remover certificado anterior {existing_file}: {e}")

    safe_filename = "".join(c for c in cert_file.filename if c.isalnum() or c in "._- ")
    if not safe_filename:
        safe_filename = "certificado.pfx"

    cert_file_path = client_cert_dir / safe_filename
    cert_file_path.write_bytes(cert_file.file.read())

    # Limpa também possíveis certificados legados na raiz de CERTIFICADOS_DIR
    for legacy in CERTIFICADOS_DIR.glob(f"{safe_cnpj}_*"):
        if legacy.is_file():
            try:
                legacy.unlink(missing_ok=True)
            except Exception:
                pass

    return str(cert_file_path)


def remover_arquivos_e_pastas_cliente(client: Client, invoices: List[Invoice]) -> Dict[str, Any]:
    """
    Remove todos os arquivos físicos e pastas vinculados ao cliente:
    - Certificados (pasta específica por CNPJ e arquivos legados)
    - Arquivos das notas fiscais (XMLs, PDFs, DPS e eventos)
    - Pastas de downloads do cliente em downloads/{CNPJ} ou com o nome da empresa
    - Pasta dedicada de downloads se client.save_path for exclusivo
    """
    safe_cnpj = re.sub(r"\D", "", client.cnpj or "")
    arquivos_removidos = 0
    pastas_removidas: List[str] = []

    # 1. Remover arquivos individuais vinculados às notas fiscais
    for inv in invoices:
        for attr in ("xml_path", "pdf_path", "xml_dps_path", "xml_evento_path"):
            path_str = getattr(inv, attr, None)
            if path_str:
                p = Path(path_str)
                if p.is_file():
                    try:
                        p.unlink(missing_ok=True)
                        arquivos_removidos += 1
                    except Exception as e:
                        logger.warning(f"Erro ao remover arquivo de nota fiscal {p}: {e}")

    # 2. Remover diretório e arquivos de certificados
    if safe_cnpj:
        client_cert_dir = CERTIFICADOS_DIR / safe_cnpj
        if client_cert_dir.exists() and client_cert_dir.is_dir():
            try:
                shutil.rmtree(client_cert_dir, ignore_errors=True)
                pastas_removidas.append(str(client_cert_dir))
            except Exception as e:
                logger.warning(f"Erro ao remover diretório de certificados {client_cert_dir}: {e}")

        # Limpar certificados legados salvos na raiz de CERTIFICADOS_DIR
        for legacy in CERTIFICADOS_DIR.glob(f"{safe_cnpj}_*"):
            if legacy.is_file():
                try:
                    legacy.unlink(missing_ok=True)
                    arquivos_removidos += 1
                except Exception:
                    pass

    if client.cert_path:
        cp = Path(client.cert_path)
        if cp.is_file():
            try:
                cp.unlink(missing_ok=True)
                arquivos_removidos += 1
            except Exception:
                pass

    # 3. Remover diretórios de downloads do cliente em DOWNLOADS_DIR
    if DOWNLOADS_DIR.exists():
        alvos = set()
        if safe_cnpj:
            alvos.add(safe_cnpj)
        if client.cnpj:
            alvos.add(client.cnpj.strip())
        if client.razao_social:
            alvos.add(client.razao_social.strip())

        for item in DOWNLOADS_DIR.iterdir():
            if item.is_dir():
                clean_name = item.name.strip()
                # Verifica se é a pasta do cliente (por CNPJ, razão social ou prefixo)
                if clean_name in alvos or (safe_cnpj and clean_name.startswith(safe_cnpj)):
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                        pastas_removidas.append(str(item))
                    except Exception as e:
                        logger.warning(f"Erro ao remover pasta de download {item}: {e}")

    # 4. Se client.save_path foi configurado de forma personalizada e dedicada ao cliente
    if client.save_path:
        sp = Path(client.save_path)
        # Proteção estrita contra remoção de diretórios protegidos do sistema ou do app
        diretorios_protegidos = (
            BACKEND_DIR,
            DOWNLOADS_DIR,
            CERTIFICADOS_DIR,
            Path("/"),
            Path.home(),
            BACKEND_DIR.parent,
        )
        if (
            sp.exists()
            and sp.is_dir()
            and sp not in diretorios_protegidos
            and (safe_cnpj in sp.name or (client.razao_social and client.razao_social.strip() in sp.name))
        ):
            try:
                shutil.rmtree(sp, ignore_errors=True)
                pastas_removidas.append(str(sp))
            except Exception as e:
                logger.warning(f"Erro ao remover pasta de download personalizada {sp}: {e}")

    return {
        "arquivos_removidos": arquivos_removidos,
        "pastas_removidas": pastas_removidas,
    }


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
    codigo_municipio: Optional[str] = Form(DEFAULT_CODIGO_MUNICIPIO),
    uf: Optional[str] = Form(DEFAULT_UF),
    cep: Optional[str] = Form(None),
    logradouro: Optional[str] = Form(None),
    numero: Optional[str] = Form(None),
    complemento: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    telefone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    regime_tributario: Optional[str] = Form(DEFAULT_REGIME_TRIBUTARIO),
    regime_apuracao_sn: Optional[str] = Form(DEFAULT_REGIME_APURACAO_SN),
    regime_especial: Optional[str] = Form(DEFAULT_REGIME_ESPECIAL),
    serie_dps_padrao: Optional[str] = Form(DEFAULT_SERIE_DPS),
    ultimo_numero_dps: Optional[int] = Form(0),
    ambiente_padrao: Optional[str] = Form(DEFAULT_AMBIENTE),
    cert_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Criar novo cliente com certificado e dados fiscais opcionais."""
    cert_path = salvar_arquivo_certificado(cert_file, cnpj)

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
        codigo_municipio=codigo_municipio or DEFAULT_CODIGO_MUNICIPIO,
        uf=uf or DEFAULT_UF,
        cep=cep,
        logradouro=logradouro,
        numero=numero,
        complemento=complemento,
        bairro=bairro,
        telefone=telefone,
        email=email,
        regime_tributario=regime_tributario or DEFAULT_REGIME_TRIBUTARIO,
        regime_apuracao_sn=regime_apuracao_sn or DEFAULT_REGIME_APURACAO_SN,
        regime_especial=regime_especial or DEFAULT_REGIME_ESPECIAL,
        serie_dps_padrao=serie_dps_padrao or DEFAULT_SERIE_DPS,
        ultimo_numero_dps=ultimo_numero_dps or 0,
        ambiente_padrao=ambiente_padrao or DEFAULT_AMBIENTE,
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    """
    Remove o cliente, todas as suas notas associadas no banco de dados e todos os
    arquivos físicos (certificados e downloads) no servidor.
    """
    db_client = db.query(Client).filter(Client.id == client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")

    invoices = db.query(Invoice).filter(Invoice.client_id == client_id).all()

    # 1. Deletar arquivos físicos e pastas do cliente (certificados e downloads)
    info_remocao = remover_arquivos_e_pastas_cliente(db_client, invoices)

    # 2. Deletar notas associadas no banco de dados
    for inv in invoices:
        db.delete(inv)

    # 3. Deletar cliente no banco de dados
    db.delete(db_client)
    db.commit()

    return {
        "message": "Cliente, configurações, notas e arquivos físicos excluídos com sucesso.",
        "client_id": client_id,
        "notas_excluidas": len(invoices),
        "arquivos_removidos": info_remocao["arquivos_removidos"],
        "pastas_removidas": info_remocao["pastas_removidas"],
    }


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

    saved_cert_path = salvar_arquivo_certificado(cert_file, db_client.cnpj)
    if saved_cert_path:
        db_client.cert_path = saved_cert_path

    db.commit()
    db.refresh(db_client)
    return db_client

"""Router de Cadastros Recorrentes (Tomadores e Serviços) e Consultas Automáticas (CNPJ e CEP)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Customer, ServiceItem
from app.schemas import (
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    ServiceItemCreate,
    ServiceItemResponse,
    ServiceItemUpdate,
)
from app.services.lookup_service import LookupService
from pynfse.adn import buscar_correlacoes_anexo_viii, clean_digits, obter_cclasstrib

router = APIRouter(prefix="/api", tags=["registry", "lookup"])


# ==============================================================================
# 1. Consultas Automáticas de CNPJ e CEP (BrasilAPI / ViaCEP / ReceitaWS)
# ==============================================================================


@router.get("/lookup/cnpj/{cnpj:path}")
async def lookup_cnpj(cnpj: str):
    """Consulta dados cadastrais, regime tributário (Simples/MEI) e código IBGE de 7 dígitos pelo CNPJ."""
    return await LookupService.consultar_cnpj(cnpj)


@router.get("/lookup/cep/{cep}")
async def lookup_cep(cep: str):
    """Consulta logradouro, bairro, UF e código IBGE de 7 dígitos pelo CEP."""
    return await LookupService.consultar_cep(cep)


# ==============================================================================
# 2. CRUD de Tomadores Recorrentes (/api/customers)
# ==============================================================================


@router.get("/customers", response_model=List[CustomerResponse])
def list_customers(
    client_id: Optional[int] = Query(None, description="ID do Prestador (retorna os vinculados e os globais)"),
    q: Optional[str] = Query(None, description="Busca por documento ou razão social"),
    db: Session = Depends(get_db),
):
    """Lista os tomadores recorrentes cadastrados."""
    query = db.query(Customer)
    if client_id is not None:
        query = query.filter(or_(Customer.client_id == client_id, Customer.client_id.is_(None)))
    if q:
        termo = f"%{q.strip()}%"
        query = query.filter(or_(Customer.razao_social.ilike(termo), Customer.documento.ilike(termo)))
    return query.order_by(Customer.razao_social.asc()).all()


@router.post("/customers", response_model=CustomerResponse)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    """Cadastra um novo tomador recorrente."""
    doc_limpo = clean_digits(payload.documento)
    if len(doc_limpo) not in (11, 14):
        raise HTTPException(status_code=400, detail="Documento do tomador deve ser CPF (11) ou CNPJ (14).")

    customer = Customer(
        client_id=payload.client_id,
        documento=doc_limpo,
        razao_social=payload.razao_social.strip(),
        inscricao_municipal=payload.inscricao_municipal,
        email=payload.email,
        telefone=payload.telefone,
        cep=clean_digits(payload.cep) if payload.cep else None,
        logradouro=payload.logradouro,
        numero=payload.numero,
        complemento=payload.complemento,
        bairro=payload.bairro,
        codigo_municipio=clean_digits(payload.codigo_municipio or "3201308") or "3201308",
        uf=(payload.uf or "ES").upper(),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)):
    """Atualiza um tomador recorrente."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Tomador não encontrado.")

    data = payload.model_dump(exclude_unset=True)
    if "documento" in data and data["documento"]:
        data["documento"] = clean_digits(data["documento"])
    if "cep" in data and data["cep"]:
        data["cep"] = clean_digits(data["cep"])
    if "codigo_municipio" in data and data["codigo_municipio"]:
        data["codigo_municipio"] = clean_digits(data["codigo_municipio"])

    for k, v in data.items():
        setattr(customer, k, v)

    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """Remove um tomador recorrente."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Tomador não encontrado.")
    db.delete(customer)
    db.commit()
    return {"message": "Tomador removido com sucesso."}


# ==============================================================================
# 3. CRUD de Serviços Recorrentes (/api/service-items) com Autocompletar Anexo VIII
# ==============================================================================


def _enriquecer_servico_pelo_anexo_viii(
    c_trib_nac: Optional[str],
    c_nbs: Optional[str],
    c_class_trib: Optional[str],
    cst_ibscbs: Optional[str],
    c_ind_op: Optional[str],
) -> tuple[str, str, str, str, str]:
    ctrib = clean_digits(c_trib_nac or "010101").zfill(6)
    nbs = clean_digits(c_nbs or "")
    cclass = clean_digits(c_class_trib or "").zfill(6) if c_class_trib else ""
    indop = clean_digits(c_ind_op or "")
    cst = clean_digits(cst_ibscbs or "").zfill(3) if cst_ibscbs else ""

    correlacoes = buscar_correlacoes_anexo_viii(c_trib_nac=ctrib, limite=5)
    if correlacoes:
        primeira = correlacoes[0]
        if not nbs:
            nbs = clean_digits(primeira.get("cNBS") or primeira.get("c_nbs") or primeira.get("nbs") or "")
        if not cclass:
            cclass = clean_digits(primeira.get("cClassTrib") or primeira.get("c_class_trib") or "000001").zfill(6)
        if not indop:
            indop = clean_digits(primeira.get("indop") or primeira.get("cIndOp") or "100301").zfill(6)

    if not cclass:
        cclass = "000001"
    if not indop:
        indop = "100301"

    meta_class = obter_cclasstrib(cclass)
    if meta_class and not cst:
        cst = str(meta_class.get("cst") or "000").zfill(3)
    elif not cst:
        cst = "000"

    return ctrib, nbs, cclass, cst, indop


@router.get("/service-items", response_model=List[ServiceItemResponse])
def list_service_items(
    client_id: Optional[int] = Query(None, description="ID do Prestador (retorna os vinculados e os globais)"),
    q: Optional[str] = Query(None, description="Busca por título, descrição ou cTribNac"),
    db: Session = Depends(get_db),
):
    """Lista os serviços recorrentes cadastrados."""
    query = db.query(ServiceItem)
    if client_id is not None:
        query = query.filter(or_(ServiceItem.client_id == client_id, ServiceItem.client_id.is_(None)))
    if q:
        termo = f"%{q.strip()}%"
        query = query.filter(
            or_(
                ServiceItem.titulo.ilike(termo),
                ServiceItem.descricao.ilike(termo),
                ServiceItem.c_trib_nac.ilike(termo),
            )
        )
    return query.order_by(ServiceItem.titulo.asc()).all()


@router.post("/service-items", response_model=ServiceItemResponse)
def create_service_item(payload: ServiceItemCreate, db: Session = Depends(get_db)):
    """Cadastra um novo serviço recorrente com preenchimento automático da matriz Anexo VIII."""
    ctrib, nbs, cclass, cst, indop = _enriquecer_servico_pelo_anexo_viii(
        payload.c_trib_nac,
        payload.c_nbs,
        payload.c_class_trib,
        payload.cst_ibscbs,
        payload.c_ind_op,
    )

    item = ServiceItem(
        client_id=payload.client_id,
        codigo_interno=payload.codigo_interno,
        titulo=payload.titulo.strip(),
        descricao=payload.descricao.strip(),
        valor_unitario=float(payload.valor_unitario or 0.0),
        c_trib_nac=ctrib,
        c_nbs=nbs,
        c_class_trib=cclass,
        cst_ibscbs=cst,
        c_ind_op=indop,
        aliquota_iss=float(payload.aliquota_iss if payload.aliquota_iss is not None else 2.0),
        iss_retido=1 if payload.iss_retido else 0,
        reter_federais=1 if payload.reter_federais else 0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/service-items/{item_id}", response_model=ServiceItemResponse)
def update_service_item(item_id: int, payload: ServiceItemUpdate, db: Session = Depends(get_db)):
    """Atualiza um serviço recorrente."""
    item = db.query(ServiceItem).filter(ServiceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Serviço não encontrado.")

    data = payload.model_dump(exclude_unset=True)
    if "iss_retido" in data and data["iss_retido"] is not None:
        data["iss_retido"] = 1 if data["iss_retido"] else 0
    if "reter_federais" in data and data["reter_federais"] is not None:
        data["reter_federais"] = 1 if data["reter_federais"] else 0

    for k, v in data.items():
        setattr(item, k, v)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/service-items/{item_id}")
def delete_service_item(item_id: int, db: Session = Depends(get_db)):
    """Remove um serviço recorrente."""
    item = db.query(ServiceItem).filter(ServiceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Serviço não encontrado.")
    db.delete(item)
    db.commit()
    return {"message": "Serviço removido com sucesso."}

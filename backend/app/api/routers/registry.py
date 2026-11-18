"""Router de Cadastros Recorrentes (Tomadores e Serviços) e Consultas Automáticas (CNPJ e CEP)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.routers.auth import get_current_user
from app.core.spreadsheets import (
    build_template_response as _build_template_response,
    clean_doc as _clean_doc,
    parse_bool as _parse_bool,
    parse_float as _parse_float,
    parse_spreadsheet_rows as _parse_spreadsheet_rows,
)
from app.database import get_db
from app.models import Customer, ServiceItem
from app.schemas import (
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    RegistryBatchDeleteRequest,
    ServiceItemCreate,
    ServiceItemResponse,
    ServiceItemUpdate,
    TaxValidationRequest,
)
from app.services.adn_service import AdnService
from app.services.lookup_service import LookupService
from pynfse.adn import buscar_correlacoes_anexo_viii, clean_digits, obter_cclasstrib

router = APIRouter(prefix="/api", tags=["registry", "lookup"], dependencies=[Depends(get_current_user)])


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
    doc_limpo = _clean_doc(payload.documento)
    if len(doc_limpo) not in (11, 14):
        raise HTTPException(status_code=400, detail="Documento do tomador deve ser CNPJ (14) ou CPF (11).")

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
        data["documento"] = _clean_doc(data["documento"])
    if "cep" in data and data["cep"]:
        data["cep"] = clean_digits(data["cep"])
    if "codigo_municipio" in data and data["codigo_municipio"]:
        data["codigo_municipio"] = clean_digits(data["codigo_municipio"])

    for k, v in data.items():
        setattr(customer, k, v)

    db.commit()
    db.refresh(customer)
    return customer


def _delete_registry_batch(model, req: RegistryBatchDeleteRequest, db: Session) -> dict:
    """Helper compartilhado para exclusão em lote de tomadores ou serviços."""
    q = db.query(model)
    if req.delete_all:
        if req.client_id is not None:
            q = q.filter(or_(model.client_id == req.client_id, model.client_id.is_(None)))
    elif req.ids:
        q = q.filter(model.id.in_(req.ids))
    else:
        raise HTTPException(status_code=400, detail="Informe ids ou delete_all=true.")

    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """Remove um tomador recorrente."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Tomador não encontrado.")
    db.delete(customer)
    db.commit()
    return {"message": "Tomador removido com sucesso."}


@router.post("/customers/delete-batch")
def delete_customers_batch(req: RegistryBatchDeleteRequest, db: Session = Depends(get_db)):
    """Remove múltiplos tomadores recorrentes selecionados ou todos."""
    return _delete_registry_batch(Customer, req, db)


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
    """Cadastra um novo serviço recorrente com preenchimento automático e validação NBS × cClassTrib × cIndOp."""
    cst_input = payload.cst_ibscbs if "cst_ibscbs" in payload.model_fields_set else None
    ctrib, nbs, cclass, cst, indop = _enriquecer_servico_pelo_anexo_viii(
        payload.c_trib_nac,
        payload.c_nbs,
        payload.c_class_trib,
        cst_input,
        payload.c_ind_op,
    )

    val_res = AdnService.validar_ibscbs(
        TaxValidationRequest(
            cClassTrib=cclass,
            cst=cst,
            cIndOp=indop,
            cTribNac=ctrib,
            cNBS=nbs or None,
        )
    )
    if not val_res.get("valido"):
        raise HTTPException(
            status_code=422,
            detail={
                "mensagem": "Combinação tributária IBS/CBS inválida para cadastro do serviço.",
                "erros": val_res.get("erros") or [],
            },
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
    resp = ServiceItemResponse.model_validate(item)
    resp.avisos_fiscais = val_res.get("avisos") or []
    return resp


@router.put("/service-items/{item_id}", response_model=ServiceItemResponse)
def update_service_item(item_id: int, payload: ServiceItemUpdate, db: Session = Depends(get_db)):
    """Atualiza um serviço recorrente validando regras IBS/CBS e compatibilidade com a NBS."""
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

    val_res = AdnService.validar_ibscbs(
        TaxValidationRequest(
            cClassTrib=item.c_class_trib or "000001",
            cst=item.cst_ibscbs or "000",
            cIndOp=item.c_ind_op or "100301",
            cTribNac=item.c_trib_nac or "010101",
            cNBS=item.c_nbs or None,
        )
    )
    if not val_res.get("valido"):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "mensagem": "Combinação tributária IBS/CBS inválida para atualização do serviço.",
                "erros": val_res.get("erros") or [],
            },
        )

    db.commit()
    db.refresh(item)
    resp = ServiceItemResponse.model_validate(item)
    resp.avisos_fiscais = val_res.get("avisos") or []
    return resp


@router.delete("/service-items/{item_id}")
def delete_service_item(item_id: int, db: Session = Depends(get_db)):
    """Remove um serviço recorrente."""
    item = db.query(ServiceItem).filter(ServiceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Serviço não encontrado.")
    db.delete(item)
    db.commit()
    return {"message": "Serviço removido com sucesso."}


@router.post("/service-items/delete-batch")
def delete_service_items_batch(req: RegistryBatchDeleteRequest, db: Session = Depends(get_db)):
    """Remove múltiplos serviços recorrentes selecionados ou todos."""
    return _delete_registry_batch(ServiceItem, req, db)


# ==============================================================================
# 4. Importação em Lote via CSV / XLSX + Templates
# ==============================================================================


@router.get("/customers/import/template")
def download_customers_template(format: str = Query("xlsx", description="csv ou xlsx")):
    """Baixa planilha modelo pronta para importação de tomadores recorrentes."""
    headers = [
        "documento",
        "razao_social",
        "email",
        "telefone",
        "cep",
        "logradouro",
        "numero",
        "complemento",
        "bairro",
        "codigo_municipio",
        "uf",
        "inscricao_municipal",
    ]
    sample = [
        "12.345.678/0001-95",
        "EMPRESA EXEMPLO LTDA",
        "financeiro@exemplo.com.br",
        "27999990000",
        "29140000",
        "AV CENTRAL",
        "100",
        "SALA 01",
        "CENTRO",
        "3201308",
        "ES",
        "123456",
    ]
    return _build_template_response(headers, sample, "modelo_importacao_tomadores", format)


@router.post("/customers/import")
async def import_customers_batch(
    file: UploadFile = File(...),
    client_id: Optional[int] = Form(None),
    atualizar_existentes: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Importa tomadores recorrentes em lote a partir de planilha CSV ou XLSX."""
    content = await file.read()
    try:
        rows = _parse_spreadsheet_rows(content, file.filename or "import.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a planilha: {exc}") from exc

    criados = 0
    atualizados = 0
    ignorados = 0
    erros: List[Dict[str, Any]] = []

    for row in rows:
        linha = row.get("_linha")
        doc_raw = row.get("documento") or row.get("cnpj") or row.get("cpf_cnpj") or row.get("cpf")
        doc = _clean_doc(doc_raw)
        razao = str(row.get("razao_social") or row.get("nome") or row.get("tomador") or "").strip()

        if len(doc) not in (11, 14):
            erros.append({"linha": linha, "erro": f"Documento inválido ('{doc_raw or ''}')."})
            continue
        if not razao:
            erros.append({"linha": linha, "erro": f"Razão social obrigatória para o documento {doc}."})
            continue

        existing_q = db.query(Customer).filter(Customer.documento == doc)
        if client_id is not None:
            existing_q = existing_q.filter(Customer.client_id == client_id)
        else:
            existing_q = existing_q.filter(Customer.client_id.is_(None))
        existing = existing_q.first()

        fields = {
            "razao_social": razao,
            "inscricao_municipal": str(row.get("inscricao_municipal") or "").strip() or None,
            "email": str(row.get("email") or "").strip() or None,
            "telefone": clean_digits(str(row.get("telefone") or "")) or None,
            "cep": clean_digits(str(row.get("cep") or "")) or None,
            "logradouro": str(row.get("logradouro") or row.get("endereco") or "").strip() or None,
            "numero": str(row.get("numero") or "S/N").strip() or "S/N",
            "complemento": str(row.get("complemento") or "").strip() or None,
            "bairro": str(row.get("bairro") or "").strip() or None,
            "codigo_municipio": clean_digits(str(row.get("codigo_municipio") or row.get("ibge") or "3201308")) or "3201308",
            "uf": (str(row.get("uf") or "ES").strip() or "ES")[:2].upper(),
        }

        if existing:
            if not atualizar_existentes:
                ignorados += 1
                continue
            for k, v in fields.items():
                if v is not None:
                    setattr(existing, k, v)
            atualizados += 1
        else:
            db.add(Customer(client_id=client_id, documento=doc, **fields))
            criados += 1

    db.commit()
    return {
        "total_lidas": len(rows),
        "criados": criados,
        "atualizados": atualizados,
        "ignorados": ignorados,
        "erros": erros,
    }


@router.get("/service-items/import/template")
def download_services_template(format: str = Query("xlsx", description="csv ou xlsx")):
    """Baixa planilha modelo pronta para importação de serviços recorrentes."""
    headers = [
        "titulo",
        "descricao",
        "valor_unitario",
        "c_trib_nac",
        "c_nbs",
        "c_class_trib",
        "cst_ibscbs",
        "c_ind_op",
        "aliquota_iss",
        "iss_retido",
        "reter_federais",
        "codigo_interno",
    ]
    sample = [
        "Consultoria Mensal em TI",
        "Prestação de serviços contínuos de suporte e desenvolvimento de sistemas",
        "2500.00",
        "010101",
        "115022000",
        "000001",
        "000",
        "100301",
        "2.0",
        "nao",
        "nao",
        "SRV-001",
    ]
    return _build_template_response(headers, sample, "modelo_importacao_servicos", format)


@router.post("/service-items/import")
async def import_services_batch(
    file: UploadFile = File(...),
    client_id: Optional[int] = Form(None),
    atualizar_existentes: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Importa serviços recorrentes em lote via CSV ou XLSX com preenchimento automático pelo Anexo VIII."""
    content = await file.read()
    try:
        rows = _parse_spreadsheet_rows(content, file.filename or "import.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a planilha: {exc}") from exc

    criados = 0
    atualizados = 0
    ignorados = 0
    erros: List[Dict[str, Any]] = []

    for row in rows:
        linha = row.get("_linha")
        titulo = str(row.get("titulo") or row.get("nome") or row.get("servico") or "").strip()
        descricao = str(row.get("descricao") or titulo).strip()
        if not titulo:
            erros.append({"linha": linha, "erro": "Título do serviço é obrigatório."})
            continue

        try:
            valor = _parse_float(row.get("valor_unitario") or row.get("valor"), 0.0)
            aliq_iss = _parse_float(row.get("aliquota_iss") or row.get("iss"), 2.0)
        except ValueError:
            erros.append({"linha": linha, "erro": f"Valor ou alíquota inválidos no serviço '{titulo}'."})
            continue

        ctrib, nbs, cclass, cst, indop = _enriquecer_servico_pelo_anexo_viii(
            row.get("c_trib_nac") or row.get("ctribnac") or "010101",
            row.get("c_nbs") or row.get("cnbs") or row.get("nbs"),
            row.get("c_class_trib") or row.get("cclasstrib"),
            row.get("cst_ibscbs") or row.get("cst"),
            row.get("c_ind_op") or row.get("cindop") or row.get("indop"),
        )

        existing_q = db.query(ServiceItem).filter(ServiceItem.titulo == titulo)
        if client_id is not None:
            existing_q = existing_q.filter(ServiceItem.client_id == client_id)
        else:
            existing_q = existing_q.filter(ServiceItem.client_id.is_(None))
        existing = existing_q.first()

        fields = {
            "codigo_interno": str(row.get("codigo_interno") or "").strip() or None,
            "descricao": descricao,
            "valor_unitario": valor,
            "c_trib_nac": ctrib,
            "c_nbs": nbs,
            "c_class_trib": cclass,
            "cst_ibscbs": cst,
            "c_ind_op": indop,
            "aliquota_iss": aliq_iss,
            "iss_retido": 1 if _parse_bool(row.get("iss_retido")) else 0,
            "reter_federais": 1 if _parse_bool(row.get("reter_federais")) else 0,
        }

        if existing:
            if not atualizar_existentes:
                ignorados += 1
                continue
            for k, v in fields.items():
                setattr(existing, k, v)
            atualizados += 1
        else:
            db.add(ServiceItem(client_id=client_id, titulo=titulo, **fields))
            criados += 1

    db.commit()
    return {
        "total_lidas": len(rows),
        "criados": criados,
        "atualizados": atualizados,
        "ignorados": ignorados,
        "erros": erros,
    }

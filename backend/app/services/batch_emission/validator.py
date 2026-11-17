"""Validador em 3 níveis (Estrutural, Cadastral e Fiscal/XSD) para itens do lote NFS-e."""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.spreadsheets import clean_doc, parse_date_iso, validate_cpf_cnpj
from app.models import BatchImport, BatchImportItem, Client, Customer, ServiceItem
from app.schemas import TaxCalculationRequest, TaxValidationRequest
from app.services.adn_service import AdnService
from pynfse.adn import (
    XsdValidator,
    build_dps_xml,
    buscar_correlacoes_anexo_viii,
    obter_cclasstrib,
    obter_servico_ctribnac,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _lookup_customer(db: Session, client_id: int, doc_clean: str) -> Optional[Customer]:
    if not doc_clean:
        return None
    return (
        db.query(Customer)
        .filter(
            Customer.documento == doc_clean,
            or_(Customer.client_id == client_id, Customer.client_id.is_(None)),
        )
        .order_by(Customer.client_id.desc())
        .first()
    )


def _lookup_service_item(db: Session, client_id: int, codigo_servico: str) -> Optional[ServiceItem]:
    code = (codigo_servico or "").strip()
    if not code:
        return None
    filters = [
        ServiceItem.codigo_interno == code,
        ServiceItem.titulo == code,
    ]
    if code.isdigit():
        filters.append(ServiceItem.id == int(code))
    return (
        db.query(ServiceItem)
        .filter(
            or_(ServiceItem.client_id == client_id, ServiceItem.client_id.is_(None)),
            or_(*filters),
        )
        .order_by(ServiceItem.client_id.desc())
        .first()
    )


def build_emission_context_for_item(
    db: Session,
    client_db: Client,
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Optional[Customer], Optional[ServiceItem]]:
    """Resolve tomador, serviço e tributação reutilizando cadastros internos e Anexo VIII."""
    doc_clean = clean_doc(payload.get("documento_tomador"))
    customer = _lookup_customer(db, client_db.id, doc_clean)
    service_item = _lookup_service_item(db, client_db.id, payload.get("codigo_servico") or "")

    prestador = {
        "cnpj": clean_doc(client_db.cnpj),
        "inscricao_municipal": client_db.inscricao_municipal,
        "razao_social": client_db.razao_social,
        "codigo_municipio": client_db.codigo_municipio or "3201308",
        "regime": client_db.regime_tributario or "normal",
        "reg_ap_trib_sn": client_db.regime_apuracao_sn or "1",
        "reg_esp_trib": client_db.regime_especial or "0",
        "email": client_db.email,
        "fone": client_db.telefone,
        "endereco": (
            {
                "codigo_municipio": client_db.codigo_municipio or "3201308",
                "cep": client_db.cep,
                "logradouro": client_db.logradouro,
                "numero": client_db.numero or "S/N",
                "complemento": client_db.complemento,
                "bairro": client_db.bairro,
            }
            if client_db.logradouro and client_db.cep
            else None
        ),
    }

    mun_tomador = (
        payload.get("municipio_tomador")
        or (customer.codigo_municipio if customer else None)
        or payload.get("municipio_prestacao")
        or client_db.codigo_municipio
        or "3201308"
    )
    cep_tomador = payload.get("cep_tomador") or (customer.cep if customer else None)
    logr_tomador = payload.get("logradouro_tomador") or (customer.logradouro if customer else None)
    num_tomador = payload.get("numero_tomador") or (customer.numero if customer else None) or "S/N"
    bairro_tomador = payload.get("bairro_tomador") or (customer.bairro if customer else None)

    tomador_addr = (
        {
            "codigo_municipio": str(mun_tomador),
            "cep": str(cep_tomador),
            "logradouro": str(logr_tomador),
            "numero": str(num_tomador),
            "bairro": str(bairro_tomador),
        }
        if cep_tomador and logr_tomador and bairro_tomador
        else None
    )

    tomador = {
        "documento": doc_clean,
        "razao_social": payload.get("nome_tomador") or (customer.razao_social if customer else "") or "Tomador",
        "email": payload.get("email_tomador") or (customer.email if customer else None) or None,
        "endereco": tomador_addr,
    }

    c_trib_nac = str(
        payload.get("c_trib_nac")
        or (service_item.c_trib_nac if service_item else None)
        or ""
    ).strip()
    c_nbs = str(
        payload.get("c_nbs")
        or (service_item.c_nbs if service_item else None)
        or ""
    ).strip() or None
    c_class_trib = str(
        payload.get("cclasstrib")
        or (service_item.c_class_trib if service_item else None)
        or "000001"
    ).strip()
    cst = str(
        payload.get("cst_ibs_cbs")
        or (service_item.cst_ibscbs if service_item else None)
        or ""
    ).strip() or None
    indop = str(
        payload.get("indop")
        or (service_item.c_ind_op if service_item else None)
        or ""
    ).strip() or None

    # Enriquecimento via Anexo VIII caso c_trib_nac exista e campos estejam omissos
    if c_trib_nac and (not c_nbs or not indop):
        corrs = buscar_correlacoes_anexo_viii(c_trib_nac=c_trib_nac, limite=1)
        if corrs:
            corr = corrs[0]
            c_nbs = c_nbs or corr.get("cNBS")
            c_class_trib = payload.get("cclasstrib") or corr.get("cClassTrib") or c_class_trib
            cst = cst or corr.get("cst")
            indop = indop or corr.get("indop")

    if not cst and c_class_trib:
        meta_ct = obter_cclasstrib(c_class_trib)
        if meta_ct:
            cst = meta_ct.get("cst")

    descricao = (
        payload.get("discriminacao")
        or payload.get("descricao_servico")
        or (service_item.descricao if service_item else None)
        or "Prestação de serviços"
    )
    valor_bruto = float(payload.get("valor_servico") or 0.0)
    desconto_total = float(payload.get("valor_desconto") or 0.0) + float(payload.get("valor_deducao") or 0.0)
    aliq_iss = payload.get("aliquota_iss")
    if aliq_iss is None and service_item is not None:
        aliq_iss = service_item.aliquota_iss
    iss_retido = payload.get("iss_retido")
    if iss_retido is None and service_item is not None:
        iss_retido = bool(service_item.iss_retido)
    reter_fed = payload.get("reter_federais")
    if reter_fed is None and service_item is not None:
        reter_fed = bool(service_item.reter_federais)

    servico = {
        "valor": valor_bruto,
        "cTribNac": c_trib_nac or "010101",
        "cNBS": c_nbs or "115021000",
        "cClassTrib": c_class_trib or "000001",
        "cst": cst or "000",
        "indop": indop or "100301",
        "descricao": descricao,
        "codigo_municipio_prestacao": str(
            payload.get("municipio_prestacao") or client_db.codigo_municipio or "3201308"
        ),
        "aliquota_iss": float(aliq_iss) if aliq_iss is not None else 2.0,
        "iss_retido": bool(iss_retido),
        "reter_federais": bool(reter_fed),
        "desconto_incondicionado": desconto_total,
    }
    return prestador, tomador, servico, customer, service_item


def validate_batch_item(
    db: Session,
    client_db: Client,
    payload: Dict[str, Any],
    ambiente: str = "homologacao",
) -> List[Dict[str, str]]:
    """Executa validação em 3 níveis (Estrutural, Cadastral e Fiscal/XSD) retornando os erros por campo."""
    errors: List[Dict[str, str]] = list(payload.get("_parse_errors") or [])
    errored_fields = {e["field"] for e in errors}

    # --- Nível 1: Validação Estrutural ---
    doc_ok, doc_clean, doc_err = validate_cpf_cnpj(payload.get("documento_tomador"))
    if not doc_ok and "documento_tomador" not in errored_fields:
        errors.append({"field": "documento_tomador", "level": "estrutural", "message": doc_err or "Documento inválido."})

    if not str(payload.get("nome_tomador") or "").strip():
        errors.append({"field": "nome_tomador", "level": "estrutural", "message": "Nome/Razão Social obrigatório."})

    email = str(payload.get("email_tomador") or "").strip()
    if email and not EMAIL_RE.match(email):
        errors.append({"field": "email_tomador", "level": "estrutural", "message": f"E-mail inválido: '{email}'."})

    if "valor_servico" not in errored_fields:
        vs = payload.get("valor_servico")
        if vs is None or float(vs) <= 0:
            errors.append({"field": "valor_servico", "level": "estrutural", "message": "Valor do serviço deve ser > 0."})

    vd = float(payload.get("valor_deducao") or 0.0)
    vdesc = float(payload.get("valor_desconto") or 0.0)
    if vd < 0:
        errors.append({"field": "valor_deducao", "level": "estrutural", "message": "Dedução não pode ser negativa."})
    if vdesc < 0:
        errors.append({"field": "valor_desconto", "level": "estrutural", "message": "Desconto não pode ser negativo."})
    if (
        "valor_servico" not in errored_fields
        and payload.get("valor_servico") is not None
        and float(payload["valor_servico"]) > 0
        and (vd + vdesc) >= float(payload["valor_servico"])
    ):
        errors.append(
            {
                "field": "valor_desconto",
                "level": "estrutural",
                "message": "Soma de deduções e descontos deve ser menor que valor_servico.",
            }
        )

    comp_iso: Optional[str] = None
    if "competencia" not in errored_fields:
        try:
            comp_iso = parse_date_iso(payload.get("competencia"))
            if not comp_iso:
                errors.append({"field": "competencia", "level": "estrutural", "message": "Competência obrigatória."})
        except ValueError as exc:
            errors.append({"field": "competencia", "level": "estrutural", "message": str(exc)})

    desc_text = str(payload.get("discriminacao") or payload.get("descricao_servico") or "").strip()
    if not desc_text and not str(payload.get("codigo_servico") or "").strip():
        errors.append(
            {
                "field": "discriminacao",
                "level": "estrutural",
                "message": "Informe 'discriminacao' ou 'descricao_servico'.",
            }
        )

    # --- Nível 2: Validação Cadastral ---
    if not clean_doc(client_db.cnpj):
        errors.append({"field": "prestador", "level": "cadastral", "message": "Prestador sem CNPJ configurado."})

    cod_serv = str(payload.get("codigo_servico") or "").strip()
    c_trib_nac_raw = str(payload.get("c_trib_nac") or "").strip()
    service_item = _lookup_service_item(db, client_db.id, cod_serv)

    if cod_serv and service_item is None and not c_trib_nac_raw:
        errors.append(
            {
                "field": "codigo_servico",
                "level": "cadastral",
                "message": f"Serviço '{cod_serv}' não cadastrado para este prestador.",
            }
        )
    elif not cod_serv and not c_trib_nac_raw:
        errors.append(
            {
                "field": "codigo_servico",
                "level": "cadastral",
                "message": "Informe 'codigo_servico' cadastrado ou 'c_trib_nac' (6 dígitos).",
            }
        )

    c_trib_resolved = c_trib_nac_raw or (service_item.c_trib_nac if service_item else "")
    if c_trib_resolved and obter_servico_ctribnac(c_trib_resolved) is None:
        errors.append(
            {
                "field": "c_trib_nac",
                "level": "cadastral",
                "message": f"Código cTribNac '{c_trib_resolved}' inexistente no catálogo nacional.",
            }
        )

    mun_prest = str(payload.get("municipio_prestacao") or client_db.codigo_municipio or "").strip()
    if not re.match(r"^\d{7}$", mun_prest):
        errors.append(
            {
                "field": "municipio_prestacao",
                "level": "cadastral",
                "message": f"Código IBGE do município de prestação inválido: '{mun_prest}'.",
            }
        )

    if errors:
        return errors

    # --- Nível 3: Validação Fiscal e XSD ---
    prestador, tomador, servico, _, _ = build_emission_context_for_item(db, client_db, payload)
    ano_comp = int(comp_iso[:4]) if comp_iso else datetime.datetime.now(datetime.UTC).year

    tax_val = AdnService.validar_ibscbs(
        TaxValidationRequest(
            cClassTrib=servico["cClassTrib"],
            cst=servico["cst"],
            cTribNac=servico["cTribNac"],
            indop=servico["indop"],
        )
    )
    if not tax_val.get("valido"):
        for err in tax_val.get("erros") or []:
            errors.append(
                {
                    "field": "cclasstrib",
                    "level": "fiscal",
                    "message": f"[{err.get('codigo', 'TAX')}] {err.get('mensagem', 'Erro tributário')}",
                }
            )
        return errors

    try:
        tributacao = AdnService.calcular_tributos(
            TaxCalculationRequest(
                valor_servicos=servico["valor"],
                ano_competencia=ano_comp,
                regime_prestador=prestador.get("regime") or "normal",
                aliquota_iss_informada=servico.get("aliquota_iss"),
                iss_retido=servico["iss_retido"],
                reter_federais=servico["reter_federais"],
                desconto_incondicionado=servico.get("desconto_incondicionado") or 0.0,
                cClassTrib=servico["cClassTrib"],
            )
        )
        xml_bruto = build_dps_xml(
            prestador=prestador,
            tomador=tomador,
            servico=servico,
            tributacao=tributacao,
            serie_dps=client_db.serie_dps_padrao or "900",
            numero_dps=(client_db.ultimo_numero_dps or 0) + 1,
            data_competencia=comp_iso,
            ambiente=ambiente,
            incluir_ibscbs=True,
        )
        xsd = XsdValidator.validar_dps(xml_bruto)
        if not xsd.get("valido"):
            errors.append(
                {
                    "field": "xml_dps",
                    "level": "fiscal",
                    "message": "; ".join(xsd.get("erros") or ["Falha na validação XSD DPS v1.01."]),
                }
            )
    except (ValueError, HTTPException) as exc:
        msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        errors.append({"field": "fiscal", "level": "fiscal", "message": str(msg)})

    return errors


def recompute_batch_counters(db: Session, batch: BatchImport) -> None:
    """Recalcula contadores e estado agregado do lote com base nos estados dos itens."""
    items = db.query(BatchImportItem).filter(BatchImportItem.batch_id == batch.id).all()
    batch.total_items = len(items)
    batch.valid_items = sum(1 for it in items if it.status == "VALID")
    batch.invalid_items = sum(1 for it in items if it.status == "INVALID")
    batch.authorized_items = sum(1 for it in items if it.status == "AUTHORIZED")
    batch.rejected_items = sum(1 for it in items if it.status == "REJECTED")
    batch.unknown_items = sum(1 for it in items if it.status == "UNKNOWN")
    batch.processed_items = sum(
        1 for it in items if it.status in {"AUTHORIZED", "REJECTED", "UNKNOWN", "RETRY"}
    )

    if batch.status == "CANCELLED":
        return

    statuses = {it.status for it in items}
    if not items:
        batch.status = "IMPORTED"
    elif statuses <= {"AUTHORIZED"}:
        batch.status = "COMPLETED"
        batch.completed_at = batch.completed_at or datetime.datetime.now(datetime.UTC)
    elif statuses & {"PROCESSING"}:
        batch.status = "PROCESSING"
    elif statuses & {"AUTHORIZED", "REJECTED", "UNKNOWN", "RETRY"}:
        has_pending_or_valid = bool(statuses & {"PENDING", "VALID", "INVALID", "RETRY"})
        if has_pending_or_valid or (statuses & {"REJECTED", "UNKNOWN"}):
            batch.status = "PARTIAL"
        else:
            batch.status = "COMPLETED"
            batch.completed_at = batch.completed_at or datetime.datetime.now(datetime.UTC)
    elif statuses == {"VALID"}:
        batch.status = "VALIDATED"
    elif "INVALID" in statuses and "VALID" in statuses:
        batch.status = "PARTIAL"
    elif statuses == {"INVALID"}:
        batch.status = "VALIDATED"
    else:
        batch.status = "IMPORTED"


def validate_all_batch_items(db: Session, batch: BatchImport) -> BatchImport:
    """Valida todos os itens elegíveis (`PENDING`, `VALID`, `INVALID`) de um lote."""
    client_db = db.query(Client).filter(Client.id == batch.client_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Prestador do lote não encontrado.")

    batch.status = "VALIDATING"
    db.commit()

    items = (
        db.query(BatchImportItem)
        .filter(BatchImportItem.batch_id == batch.id)
        .order_by(BatchImportItem.row_number.asc())
        .all()
    )
    for item in items:
        if item.status in {"AUTHORIZED", "PROCESSING", "UNKNOWN", "CANCELLED"}:
            continue
        payload = json.loads(item.payload_json)
        errors = validate_batch_item(db, client_db, payload, ambiente=batch.ambiente)
        item.validation_errors_json = json.dumps(errors, ensure_ascii=False)
        item.status = "INVALID" if errors else "VALID"
        db.add(item)

    recompute_batch_counters(db, batch)
    db.commit()
    db.refresh(batch)
    return batch

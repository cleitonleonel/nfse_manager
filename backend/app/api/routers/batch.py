"""Router do Módulo Persistente de Importação e Emissão de NFS-e em Lote (`/api/batch-emission`)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.permissions import assert_client_access, is_admin_user
from app.api.routers.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    BatchImportItemResponse,
    BatchImportItemUpdateRequest,
    BatchImportResponse,
    BatchItemsDeleteRequest,
    BatchProcessRequest,
    BatchRetryRequest,
)
from app.services.audit_service import AuditService, get_client_ip
from app.services.batch_emission import BatchEmissionService, serialize_batch, serialize_batch_item
from app.services.batch_emission.exporters import export_batch_results
from app.services.batch_emission.importer import build_batch_template
from app.services.batch_emission.processor import process_batch_items, resolve_unknown_and_retry_batch
from app.services.batch_emission.validator import validate_all_batch_items

router = APIRouter(
    prefix="/api/batch-emission",
    tags=["batch-emission"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/template")
def download_batch_template(
    format: str = Query("xlsx", description="Formato do modelo: csv ou xlsx"),
):
    """Baixa o modelo padrão de planilha CSV ou XLSX para importação de notas em lote."""
    return build_batch_template(fmt=format)


@router.post("/import", response_model=BatchImportResponse)
async def import_batch_spreadsheet(
    request: Request,
    client_id: int = Form(..., description="ID do Prestador responsável pelo lote"),
    file: UploadFile = File(..., description="Planilha CSV ou XLSX com as notas"),
    delimiter: Optional[str] = Form(None, description="Delimitador opcional para CSV (';' ou ',')"),
    ambiente: Optional[str] = Form(None, description="homologacao | producao (padrão do prestador se omitido)"),
    auto_validate: bool = Form(True, description="Executar validação em 3 níveis logo após importar"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Importa e normaliza planilha de notas em lote sem realizar nenhuma transmissão fiscal."""
    assert_client_access(db, current_user, client_id, allow_none_for_admin=False)
    content = await file.read()
    batch = BatchEmissionService.import_spreadsheet(
        db=db,
        client_id=client_id,
        filename=file.filename or "lote.csv",
        content=content,
        delimiter=delimiter,
        ambiente=ambiente,
        created_by=current_user.username,
        auto_validate=auto_validate,
        include_global_registry=is_admin_user(current_user),
    )
    AuditService.record(
        db,
        action="batch.import",
        entity_type="batch_import",
        entity_id=batch.id,
        client_id=client_id,
        current_user=current_user,
        summary=f"Importação de lote '{batch.filename}' ({batch.total_items} itens, status={batch.status}).",
        details={
            "filename": batch.filename,
            "ambiente": batch.ambiente,
            "total_items": batch.total_items,
            "valid_items": batch.valid_items,
            "invalid_items": batch.invalid_items,
            "status": batch.status,
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return serialize_batch(db, batch)


@router.get("", response_model=List[BatchImportResponse])
def list_batches(
    client_id: Optional[int] = Query(None, description="Filtrar lotes pelo ID do prestador"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista os lotes de importação registrados (mais recentes primeiro)."""
    allowed_ids = assert_client_access(db, current_user, client_id, allow_none_for_admin=True)
    if client_id is None and allowed_ids is not None and not allowed_ids:
        return []
    batches = BatchEmissionService.list_batches(
        db,
        client_id=client_id,
        limit=limit,
        allowed_client_ids=allowed_ids,
    )
    return [serialize_batch(db, b) for b in batches]


def _get_authorized_batch(db: Session, current_user: User, batch_id: str):
    batch = BatchEmissionService.get_batch_or_404(db, batch_id)
    assert_client_access(db, current_user, batch.client_id, allow_none_for_admin=False)
    return batch


@router.get("/{batch_id}", response_model=BatchImportResponse)
def get_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consulta metadados e contadores de um lote específico."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    return serialize_batch(db, batch)


@router.post("/{batch_id}/validate", response_model=BatchImportResponse)
def validate_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Executa validação estrutural, cadastral e fiscal/XSD nos itens pendentes/editados do lote."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    batch = validate_all_batch_items(db, batch, include_global=is_admin_user(current_user))
    return serialize_batch(db, batch)


@router.get("/{batch_id}/items", response_model=List[BatchImportItemResponse])
def list_batch_items(
    batch_id: str,
    status: Optional[str] = Query(None, description="Filtrar itens por estado (VALID, INVALID, AUTHORIZED, REJECTED, UNKNOWN, RETRY...)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todas as linhas/itens do lote para pré-visualização, revisão e acompanhamento."""
    _get_authorized_batch(db, current_user, batch_id)
    items = BatchEmissionService.list_items(db, batch_id, status_filter=status)
    return [serialize_batch_item(it) for it in items]


@router.patch("/{batch_id}/items/{item_id}", response_model=BatchImportItemResponse)
def update_batch_item(
    batch_id: str,
    item_id: str,
    req: BatchImportItemUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Corrige campos de uma linha específica do lote e reexecuta os 3 níveis de validação."""
    _get_authorized_batch(db, current_user, batch_id)
    item = BatchEmissionService.update_item_and_revalidate(
        db,
        batch_id,
        item_id,
        req,
        include_global_registry=is_admin_user(current_user),
    )
    return serialize_batch_item(item)


@router.post("/{batch_id}/process", response_model=BatchImportResponse)
async def process_batch(
    batch_id: str,
    request: Request,
    req: Optional[BatchProcessRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Processa sequencialmente os itens válidos confirmados pelo usuário."""
    _get_authorized_batch(db, current_user, batch_id)
    body = req or BatchProcessRequest()
    batch = await process_batch_items(
        db=db,
        batch_id=batch_id,
        item_ids=body.item_ids,
        transmitir=body.transmitir,
        enviar_email=body.enviar_email,
        current_user=current_user,
    )
    AuditService.record(
        db,
        action="batch.process",
        entity_type="batch_import",
        entity_id=batch.id,
        client_id=batch.client_id,
        current_user=current_user,
        summary=(
            f"Processamento do lote '{batch.filename}' concluído "
            f"(status={batch.status}, autorizadas={batch.authorized_items}, rejeitadas={batch.rejected_items})."
        ),
        details={
            "transmitir": body.transmitir,
            "enviar_email": body.enviar_email,
            "status": batch.status,
            "authorized_items": batch.authorized_items,
            "rejected_items": batch.rejected_items,
            "unknown_items": batch.unknown_items,
        },
        status="success" if batch.rejected_items == 0 else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return serialize_batch(db, batch)


@router.post("/{batch_id}/cancel", response_model=BatchImportResponse)
def cancel_batch(
    batch_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancela o lote e marca itens ainda não transmitidos como CANCELLED."""
    _get_authorized_batch(db, current_user, batch_id)
    batch = BatchEmissionService.cancel_pending_items(db, batch_id)
    AuditService.record(
        db,
        action="batch.cancel",
        entity_type="batch_import",
        entity_id=batch.id,
        client_id=batch.client_id,
        current_user=current_user,
        summary=f"Lote '{batch.filename}' cancelado.",
        details={"status": batch.status, "total_items": batch.total_items},
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return serialize_batch(db, batch)


@router.post("/{batch_id}/retry", response_model=BatchImportResponse)
async def retry_batch(
    batch_id: str,
    request: Request,
    req: Optional[BatchRetryRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consulta itens `UNKNOWN` no ADN antes de reenviar e reprocessa itens `RETRY`."""
    _get_authorized_batch(db, current_user, batch_id)
    body = req or BatchRetryRequest()
    batch = await resolve_unknown_and_retry_batch(
        db=db,
        batch_id=batch_id,
        item_ids=body.item_ids,
        transmitir=body.transmitir,
        enviar_email=body.enviar_email,
        current_user=current_user,
    )
    AuditService.record(
        db,
        action="batch.retry",
        entity_type="batch_import",
        entity_id=batch.id,
        client_id=batch.client_id,
        current_user=current_user,
        summary=(
            f"Reprocessamento do lote '{batch.filename}' "
            f"(status={batch.status}, autorizadas={batch.authorized_items}, rejeitadas={batch.rejected_items})."
        ),
        details={
            "transmitir": body.transmitir,
            "enviar_email": body.enviar_email,
            "status": batch.status,
            "authorized_items": batch.authorized_items,
            "rejected_items": batch.rejected_items,
            "unknown_items": batch.unknown_items,
        },
        status="success" if batch.rejected_items == 0 else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return serialize_batch(db, batch)


@router.get("/{batch_id}/export")
def export_batch(
    batch_id: str,
    format: str = Query("xlsx", description="csv ou xlsx"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exporta resumo e detalhamento dos resultados do lote em CSV ou XLSX."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    items = BatchEmissionService.list_items(db, batch_id)
    return export_batch_results(batch, items, fmt=format)


@router.delete("/{batch_id}")
def delete_batch(
    batch_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exclui um lote completo de importação e seus itens de staging."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    client_id = batch.client_id
    filename = batch.filename
    res = BatchEmissionService.delete_batch(db, batch_id)
    AuditService.record(
        db,
        action="batch.delete",
        entity_type="batch_import",
        entity_id=batch_id,
        client_id=client_id,
        current_user=current_user,
        summary=f"Lote '{filename}' excluído ({res.get('deleted_items', 0)} itens).",
        details=res,
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.delete("/{batch_id}/items/{item_id}")
def delete_batch_item(
    batch_id: str,
    item_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exclui uma única linha importada do lote e recalcula os contadores."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    res = BatchEmissionService.delete_items(db, batch_id, item_ids=[item_id], delete_all=False)
    AuditService.record(
        db,
        action="batch.item_delete",
        entity_type="batch_import_item",
        entity_id=item_id,
        client_id=batch.client_id,
        current_user=current_user,
        summary=f"Item '{item_id}' excluído do lote {batch_id}.",
        details={
            "batch_id": batch_id,
            "deleted": res["deleted"],
            "removed_from_contingency": res["removed_from_contingency"],
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return {
        "deleted": res["deleted"],
        "removed_from_contingency": res["removed_from_contingency"],
        "batch": serialize_batch(db, res["batch"]),
    }


@router.post("/{batch_id}/items/delete")
def delete_batch_items(
    batch_id: str,
    req: BatchItemsDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exclui múltiplos itens selecionados ou todos os itens de um lote."""
    batch = _get_authorized_batch(db, current_user, batch_id)
    res = BatchEmissionService.delete_items(
        db,
        batch_id,
        item_ids=req.item_ids,
        delete_all=req.delete_all,
    )
    AuditService.record(
        db,
        action="batch.item_delete",
        entity_type="batch_import_item",
        entity_id=batch_id,
        client_id=batch.client_id,
        current_user=current_user,
        summary=f"Exclusão em massa de {res['deleted']} item(ns) no lote {batch_id}.",
        details={
            "batch_id": batch_id,
            "delete_all": req.delete_all,
            "item_ids": req.item_ids,
            "deleted": res["deleted"],
            "removed_from_contingency": res["removed_from_contingency"],
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return {
        "deleted": res["deleted"],
        "removed_from_contingency": res["removed_from_contingency"],
        "batch": serialize_batch(db, res["batch"]),
    }

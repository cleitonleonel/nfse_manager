"""Router do Módulo Persistente de Importação e Emissão de NFS-e em Lote (`/api/batch-emission`)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

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
    client_id: int = Form(..., description="ID do Prestador responsável pelo lote"),
    file: UploadFile = File(..., description="Planilha CSV ou XLSX com as notas"),
    delimiter: Optional[str] = Form(None, description="Delimitador opcional para CSV (';' ou ',')"),
    ambiente: Optional[str] = Form(None, description="homologacao | producao (padrão do prestador se omitido)"),
    auto_validate: bool = Form(True, description="Executar validação em 3 níveis logo após importar"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Importa e normaliza planilha de notas em lote sem realizar nenhuma transmissão fiscal."""
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
    )
    return serialize_batch(db, batch)


@router.get("", response_model=List[BatchImportResponse])
def list_batches(
    client_id: Optional[int] = Query(None, description="Filtrar lotes pelo ID do prestador"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Lista os lotes de importação registrados (mais recentes primeiro)."""
    batches = BatchEmissionService.list_batches(db, client_id=client_id, limit=limit)
    return [serialize_batch(db, b) for b in batches]


@router.get("/{batch_id}", response_model=BatchImportResponse)
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    """Consulta metadados e contadores de um lote específico."""
    batch = BatchEmissionService.get_batch_or_404(db, batch_id)
    return serialize_batch(db, batch)


@router.post("/{batch_id}/validate", response_model=BatchImportResponse)
def validate_batch(batch_id: str, db: Session = Depends(get_db)):
    """Executa validação estrutural, cadastral e fiscal/XSD nos itens pendentes/editados do lote."""
    batch = BatchEmissionService.get_batch_or_404(db, batch_id)
    batch = validate_all_batch_items(db, batch)
    return serialize_batch(db, batch)


@router.get("/{batch_id}/items", response_model=List[BatchImportItemResponse])
def list_batch_items(
    batch_id: str,
    status: Optional[str] = Query(None, description="Filtrar itens por estado (VALID, INVALID, AUTHORIZED, REJECTED, UNKNOWN, RETRY...)"),
    db: Session = Depends(get_db),
):
    """Lista todas as linhas/itens do lote para pré-visualização, revisão e acompanhamento."""
    items = BatchEmissionService.list_items(db, batch_id, status_filter=status)
    return [serialize_batch_item(it) for it in items]


@router.patch("/{batch_id}/items/{item_id}", response_model=BatchImportItemResponse)
def update_batch_item(
    batch_id: str,
    item_id: str,
    req: BatchImportItemUpdateRequest,
    db: Session = Depends(get_db),
):
    """Corrige campos de uma linha específica do lote e reexecuta os 3 níveis de validação."""
    item = BatchEmissionService.update_item_and_revalidate(db, batch_id, item_id, req)
    return serialize_batch_item(item)


@router.post("/{batch_id}/process", response_model=BatchImportResponse)
async def process_batch(
    batch_id: str,
    req: Optional[BatchProcessRequest] = None,
    db: Session = Depends(get_db),
):
    """Processa sequencialmente os itens válidos confirmados pelo usuário."""
    body = req or BatchProcessRequest()
    batch = await process_batch_items(
        db=db,
        batch_id=batch_id,
        item_ids=body.item_ids,
        transmitir=body.transmitir,
        enviar_email=body.enviar_email,
    )
    return serialize_batch(db, batch)


@router.post("/{batch_id}/cancel", response_model=BatchImportResponse)
def cancel_batch(batch_id: str, db: Session = Depends(get_db)):
    """Cancela o lote e marca itens ainda não transmitidos como CANCELLED."""
    batch = BatchEmissionService.cancel_pending_items(db, batch_id)
    return serialize_batch(db, batch)


@router.post("/{batch_id}/retry", response_model=BatchImportResponse)
async def retry_batch(
    batch_id: str,
    req: Optional[BatchRetryRequest] = None,
    db: Session = Depends(get_db),
):
    """Consulta itens `UNKNOWN` no ADN antes de reenviar e reprocessa itens `RETRY`."""
    body = req or BatchRetryRequest()
    batch = await resolve_unknown_and_retry_batch(
        db=db,
        batch_id=batch_id,
        item_ids=body.item_ids,
        transmitir=body.transmitir,
        enviar_email=body.enviar_email,
    )
    return serialize_batch(db, batch)


@router.get("/{batch_id}/export")
def export_batch(
    batch_id: str,
    format: str = Query("xlsx", description="csv ou xlsx"),
    db: Session = Depends(get_db),
):
    """Exporta resumo e detalhamento dos resultados do lote em CSV ou XLSX."""
    batch = BatchEmissionService.get_batch_or_404(db, batch_id)
    items = BatchEmissionService.list_items(db, batch_id)
    return export_batch_results(batch, items, fmt=format)


@router.delete("/{batch_id}")
def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    """Exclui um lote completo de importação e seus itens de staging."""
    return BatchEmissionService.delete_batch(db, batch_id)


@router.delete("/{batch_id}/items/{item_id}")
def delete_batch_item(batch_id: str, item_id: str, db: Session = Depends(get_db)):
    """Exclui uma única linha importada do lote e recalcula os contadores."""
    res = BatchEmissionService.delete_items(db, batch_id, item_ids=[item_id], delete_all=False)
    return {
        "deleted": res["deleted"],
        "removed_from_contingency": res["removed_from_contingency"],
        "batch": serialize_batch(db, res["batch"]),
    }


@router.post("/{batch_id}/items/delete")
def delete_batch_items(
    batch_id: str,
    req: BatchItemsDeleteRequest,
    db: Session = Depends(get_db),
):
    """Exclui múltiplos itens selecionados ou todos os itens de um lote."""
    res = BatchEmissionService.delete_items(
        db,
        batch_id,
        item_ids=req.item_ids,
        delete_all=req.delete_all,
    )
    return {
        "deleted": res["deleted"],
        "removed_from_contingency": res["removed_from_contingency"],
        "batch": serialize_batch(db, res["batch"]),
    }

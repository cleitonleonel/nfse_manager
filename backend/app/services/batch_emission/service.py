"""Camada de orquestração do módulo persistente de importação e emissão em lote."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.spreadsheets import clean_doc, parse_date_iso
from app.models import BatchImport, BatchImportItem, Client, Invoice
from app.schemas import (
    BatchImportItemResponse,
    BatchImportItemUpdateRequest,
    BatchImportResponse,
)
from app.services.batch_emission.importer import (
    TAX_CODE_PAD_WIDTHS,
    normalize_tax_code_field,
    parse_batch_file,
)
from app.services.batch_emission.processor import recover_stale_processing_batch
from app.services.batch_emission.validator import (
    recompute_batch_counters,
    validate_all_batch_items,
    validate_batch_item,
)


def serialize_batch(db: Session, batch: BatchImport) -> BatchImportResponse:
    client_db = db.query(Client).filter(Client.id == batch.client_id).first()
    return BatchImportResponse(
        id=batch.id,
        client_id=batch.client_id,
        prestador_nome=client_db.razao_social if client_db else None,
        filename=batch.filename,
        file_hash=batch.file_hash,
        ambiente=batch.ambiente,
        status=batch.status,
        total_items=batch.total_items,
        valid_items=batch.valid_items,
        invalid_items=batch.invalid_items,
        processed_items=batch.processed_items,
        authorized_items=batch.authorized_items,
        rejected_items=batch.rejected_items,
        unknown_items=batch.unknown_items,
        created_by=batch.created_by,
        created_at=batch.created_at,
        completed_at=batch.completed_at,
    )


def serialize_batch_item(item: BatchImportItem) -> BatchImportItemResponse:
    payload = json.loads(item.payload_json or "{}")
    payload.pop("_parse_errors", None)
    errors = json.loads(item.validation_errors_json or "[]")
    return BatchImportItemResponse(
        id=item.id,
        batch_id=item.batch_id,
        row_number=item.row_number,
        status=item.status,
        payload=payload,
        validation_errors=errors,
        invoice_id=item.invoice_id,
        id_dps=item.id_dps,
        serie_dps=item.serie_dps,
        numero_dps=item.numero_dps,
        chave_acesso=item.chave_acesso,
        attempts=item.attempts,
        last_error=item.last_error,
        processed_at=item.processed_at,
    )


PENDING_CONTINGENCY_STATUSES = {"dps_gerada", "fila_contingencia", "rejeitada"}


def _cleanup_orphan_contingency_invoices(db: Session, candidate_invoice_ids: List[int]) -> int:
    """Remove notas ainda pendentes na Fila de Contingência quando desvinculadas do lote."""
    removed = 0
    for inv_id in {iid for iid in candidate_invoice_ids if iid}:
        still_linked = db.query(BatchImportItem.id).filter(BatchImportItem.invoice_id == inv_id).first()
        if still_linked:
            continue
        inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        if inv and (inv.status or "") in PENDING_CONTINGENCY_STATUSES:
            db.delete(inv)
            removed += 1
    return removed


class BatchEmissionService:
    """Orquestrador HTTP/DB para lotes importados via CSV/XLSX."""

    @staticmethod
    def get_batch_or_404(db: Session, batch_id: str) -> BatchImport:
        batch = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Lote de importação não encontrado.")
        return batch

    @classmethod
    def import_spreadsheet(
        cls,
        db: Session,
        *,
        client_id: int,
        filename: str,
        content: bytes,
        delimiter: Optional[str] = None,
        ambiente: Optional[str] = None,
        created_by: Optional[str] = None,
        auto_validate: bool = True,
        include_global_registry: bool = False,
    ) -> BatchImport:
        client_db = db.query(Client).filter(Client.id == client_id).first()
        if not client_db:
            raise HTTPException(status_code=404, detail="Prestador não encontrado.")

        max_bytes = int(os.getenv("BATCH_MAX_FILE_BYTES") or str(10 * 1024 * 1024))
        max_rows = int(os.getenv("BATCH_MAX_ROWS") or "2000")
        parsed = parse_batch_file(
            content=content,
            filename=filename,
            delimiter=delimiter,
            max_bytes=max_bytes,
            max_rows=max_rows,
        )

        amb = (ambiente or client_db.ambiente_padrao or "homologacao").strip().lower()
        batch = BatchImport(
            client_id=client_id,
            filename=filename,
            file_hash=parsed["file_hash"],
            ambiente=amb,
            status="IMPORTED",
            total_items=len(parsed["items"]),
            created_by=created_by,
        )
        db.add(batch)
        db.flush()

        for row in parsed["items"]:
            item = BatchImportItem(
                batch_id=batch.id,
                row_number=row["row_number"],
                raw_data_json=json.dumps(row["raw_data"], ensure_ascii=False),
                payload_json=json.dumps(row["payload"], ensure_ascii=False),
                status="PENDING",
                validation_errors_json="[]",
            )
            db.add(item)

        db.commit()
        db.refresh(batch)

        if auto_validate:
            batch = validate_all_batch_items(db, batch, include_global=include_global_registry)
        return batch

    @classmethod
    def list_batches(
        cls,
        db: Session,
        client_id: Optional[int] = None,
        limit: int = 50,
        allowed_client_ids: Optional[List[int]] = None,
    ) -> List[BatchImport]:
        q = db.query(BatchImport)
        if client_id is not None:
            q = q.filter(BatchImport.client_id == client_id)
        elif allowed_client_ids is not None:
            if not allowed_client_ids:
                return []
            q = q.filter(BatchImport.client_id.in_(allowed_client_ids))
        return q.order_by(BatchImport.created_at.desc()).limit(limit).all()

    @classmethod
    def list_items(
        cls,
        db: Session,
        batch_id: str,
        status_filter: Optional[str] = None,
    ) -> List[BatchImportItem]:
        cls.get_batch_or_404(db, batch_id)
        q = db.query(BatchImportItem).filter(BatchImportItem.batch_id == batch_id)
        if status_filter:
            q = q.filter(BatchImportItem.status == status_filter.strip().upper())
        return q.order_by(BatchImportItem.row_number.asc()).all()

    @classmethod
    def update_item_and_revalidate(
        cls,
        db: Session,
        batch_id: str,
        item_id: str,
        req: BatchImportItemUpdateRequest,
        *,
        include_global_registry: bool = False,
    ) -> BatchImportItem:
        batch = cls.get_batch_or_404(db, batch_id)
        recover_stale_processing_batch(db, batch)
        if batch.status == "PROCESSING":
            raise HTTPException(status_code=409, detail="Não é possível editar itens durante processamento ativo.")

        item = (
            db.query(BatchImportItem)
            .filter(BatchImportItem.id == item_id, BatchImportItem.batch_id == batch_id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Item do lote não encontrado.")
        if item.status in {"AUTHORIZED", "PROCESSING", "UNKNOWN"}:
            raise HTTPException(
                status_code=409,
                detail=f"Itens em estado '{item.status}' não podem ser alterados.",
            )

        client_db = db.query(Client).filter(Client.id == batch.client_id).first()
        payload: Dict[str, Any] = json.loads(item.payload_json or "{}")
        updates = req.model_dump(exclude_unset=True)

        # Remove antigos erros de parse dos campos corrigidos manualmente
        parse_errors = [
            e for e in (payload.get("_parse_errors") or []) if e.get("field") not in updates
        ]
        for k, v in updates.items():
            if k == "documento_tomador" and v is not None:
                payload[k] = clean_doc(v) or str(v).strip()
            elif k in TAX_CODE_PAD_WIDTHS and v is not None:
                payload[k] = normalize_tax_code_field(k, v)
            elif k == "competencia" and v is not None:
                try:
                    payload[k] = parse_date_iso(v)
                except ValueError as exc:
                    payload[k] = str(v).strip()
                    parse_errors.append({"field": "competencia", "level": "estrutural", "message": str(exc)})
            else:
                payload[k] = v
        payload["_parse_errors"] = parse_errors

        errors = validate_batch_item(
            db,
            client_db,
            payload,
            ambiente=batch.ambiente,
            include_global=include_global_registry,
        )
        item.payload_json = json.dumps(payload, ensure_ascii=False)
        item.validation_errors_json = json.dumps(errors, ensure_ascii=False)
        item.status = "INVALID" if errors else "VALID"
        item.last_error = None
        db.add(item)
        recompute_batch_counters(db, batch)
        db.commit()
        db.refresh(item)
        return item

    @classmethod
    def cancel_pending_items(cls, db: Session, batch_id: str) -> BatchImport:
        batch = cls.get_batch_or_404(db, batch_id)
        recover_stale_processing_batch(db, batch)
        if batch.status == "COMPLETED":
            raise HTTPException(status_code=409, detail="Lote já concluído não pode ser cancelado.")

        items = db.query(BatchImportItem).filter(BatchImportItem.batch_id == batch_id).all()
        for it in items:
            if it.status in {"PENDING", "VALID", "INVALID", "RETRY"}:
                it.status = "CANCELLED"
                db.add(it)

        batch.status = "CANCELLED"
        recompute_batch_counters(db, batch)
        db.commit()
        db.refresh(batch)
        return batch

    @classmethod
    def delete_batch(cls, db: Session, batch_id: str) -> Dict[str, Any]:
        """Exclui um lote importado, seus itens e eventuais notas ainda pendentes na fila de contingência."""
        batch = cls.get_batch_or_404(db, batch_id)
        recover_stale_processing_batch(db, batch)
        if batch.status == "PROCESSING":
            raise HTTPException(status_code=409, detail="Não é possível excluir um lote em processamento ativo.")

        items = db.query(BatchImportItem).filter(BatchImportItem.batch_id == batch_id).all()
        candidate_inv_ids = [it.invoice_id for it in items if it.invoice_id]
        deleted_items = len(items)
        for it in items:
            db.delete(it)
        db.flush()

        removed_contingency = _cleanup_orphan_contingency_invoices(db, candidate_inv_ids)
        db.delete(batch)
        db.commit()
        return {
            "deleted_batch_id": batch_id,
            "deleted_items": deleted_items,
            "removed_from_contingency": removed_contingency,
        }

    @classmethod
    def delete_items(
        cls,
        db: Session,
        batch_id: str,
        item_ids: Optional[List[str]] = None,
        delete_all: bool = False,
    ) -> Dict[str, Any]:
        """Exclui 1, múltiplos ou todos os itens do lote e limpa pendências correspondentes na fila de contingência."""
        batch = cls.get_batch_or_404(db, batch_id)
        recover_stale_processing_batch(db, batch)
        if batch.status == "PROCESSING":
            raise HTTPException(status_code=409, detail="Não é possível excluir itens durante processamento ativo.")

        q = db.query(BatchImportItem).filter(
            BatchImportItem.batch_id == batch_id,
            BatchImportItem.status != "PROCESSING",
        )
        if not delete_all:
            if not item_ids:
                raise HTTPException(status_code=400, detail="Informe item_ids ou delete_all=true para excluir itens.")
            q = q.filter(BatchImportItem.id.in_(item_ids))

        targets = q.all()
        if not targets and not delete_all:
            raise HTTPException(status_code=404, detail="Nenhum item removível encontrado para os IDs informados.")

        candidate_inv_ids = [it.invoice_id for it in targets if it.invoice_id]
        for item in targets:
            db.delete(item)
        db.flush()

        removed_contingency = _cleanup_orphan_contingency_invoices(db, candidate_inv_ids)
        recompute_batch_counters(db, batch)
        db.commit()
        db.refresh(batch)
        return {
            "deleted": len(targets),
            "removed_from_contingency": removed_contingency,
            "batch": batch,
        }

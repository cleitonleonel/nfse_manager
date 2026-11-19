"""Router de Notas - Sincronização e listagem de NFSe."""

import os
import logging
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import BatchImportItem, Client, Invoice, User
from app.schemas import SyncRequest, InvoiceResponse
from app.api.deps import get_nfse_client
from app.api.routers.auth import get_current_user
from app.api.state import TaskStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=["invoices", "sync"], dependencies=[Depends(get_current_user)])


def background_sync(
    sync_id: str,
    client_id: int,
    data_inicio: str,
    data_fim: str,
    tipo: str,
    created_by: Optional[str] = None,
):
    """Executa sincronização em background."""
    db = SessionLocal()
    try:
        TaskStore.set_task(
            sync_id,
            {"status": "running", "message": "Iniciando processo...", "progress": 0},
            kind="sync",
            created_by=created_by,
        )

        clients_to_sync = []
        if client_id:
            c = db.query(Client).filter(Client.id == client_id).first()
            if c:
                clients_to_sync.append(c)
        else:
            clients_to_sync = db.query(Client).all()

        if not clients_to_sync:
            TaskStore.set_task(
                sync_id,
                {"status": "failed", "message": "Nenhum cliente encontrado.", "progress": 0},
                kind="sync",
                created_by=created_by,
            )
            return

        new_count_total = 0
        total_clients = len(clients_to_sync)
        for idx, client_db in enumerate(clients_to_sync):
            client_start = int((idx / total_clients) * 100)
            client_end = int(((idx + 1) / total_clients) * 100)
            client_span = max(1, client_end - client_start)
            try:
                TaskStore.update_task(
                    sync_id,
                    message=f"[{idx + 1}/{len(clients_to_sync)}] Autenticando {client_db.razao_social}...",
                    progress=min(client_start + 10, 95),
                )
                nfse = get_nfse_client(client_db)
                nfse.autenticar()

                TaskStore.update_task(
                    sync_id,
                    message=f"[{idx + 1}/{len(clients_to_sync)}] Buscando notas {tipo} para {client_db.razao_social}...",
                    progress=min(client_start + 20, 95),
                )

                if tipo == "emitidas":
                    resultado = nfse.listar_notas_emitidas(data_inicio, data_fim)
                else:
                    resultado = nfse.listar_notas_recebidas(data_inicio, data_fim)

                if "erro" in resultado:
                    logger.warning(f"Erro no cliente {client_db.razao_social}: {resultado['erro']}")
                    continue

                notas = resultado.get("notas", [])
                new_count = 0
                current_client_id = client_db.id
                total_notas = max(1, len(notas))

                for note_idx, nota_data in enumerate(notas):
                    note_progress = client_start + int(client_span * (0.3 + 0.65 * ((note_idx + 1) / total_notas)))
                    TaskStore.update_task(
                        sync_id,
                        message=f"[{idx + 1}/{len(clients_to_sync)}] Processando nota {note_idx + 1}/{len(notas)} de {client_db.razao_social}...",
                        progress=min(note_progress, client_end),
                    )

                    xml_url = nota_data.get("download_xml")
                    if not xml_url:
                        continue

                    chave = xml_url.split("/")[-1]
                    valor_str = nota_data.get("valor", "0").replace("R$", "").replace(".", "").replace(",", ".").strip()
                    try:
                        valor = float(valor_str)
                    except ValueError:
                        valor = 0.0

                    dt_emissao = datetime.datetime.now()
                    raw_date = nota_data.get("data_emissao")
                    if raw_date:
                        try:
                            dt_emissao = datetime.datetime.strptime(raw_date, "%d/%m/%Y")
                        except ValueError:
                            pass

                    existing = db.query(Invoice).filter(Invoice.chave == chave).first()
                    if not existing:
                        new_invoice = Invoice(
                            client_id=current_client_id,
                            chave=chave,
                            numero=nota_data.get("numero") or chave,
                            status=nota_data.get("status_danfs-e", "unknown"),
                            data_emissao=dt_emissao,
                            tipo=tipo,
                            valor=valor,
                            download_url_xml=xml_url,
                            download_url_pdf=nota_data.get("download_danfs-e"),
                            xml_path=nota_data.get("xml_path_saved"),
                        )
                        db.add(new_invoice)
                        new_count += 1
                    else:
                        if not existing.xml_path and nota_data.get("xml_path_saved"):
                            existing.xml_path = nota_data.get("xml_path_saved")
                        if (existing.valor is None or existing.valor == 0.0) and valor > 0.0:
                            existing.valor = valor
                        if (not existing.numero or existing.numero == existing.chave) and nota_data.get("numero"):
                            existing.numero = nota_data.get("numero")

                db.commit()
                new_count_total += new_count
                TaskStore.update_task(
                    sync_id,
                    message=f"[{idx + 1}/{len(clients_to_sync)}] Concluído para {client_db.razao_social}.",
                    progress=client_end,
                )
            except Exception as ce:
                logger.error(f"Erro no cliente {client_db.razao_social}: {ce}")
                cur_task = TaskStore.get_task(sync_id) or {}
                TaskStore.update_task(
                    sync_id,
                    message=f"[{idx + 1}/{len(clients_to_sync)}] Falha ao processar {client_db.razao_social}: {ce}",
                    progress=max(client_start, int(cur_task.get("progress", 0))),
                )

        TaskStore.set_task(
            sync_id,
            {
                "status": "completed",
                "message": f"Sincronização concluída. {new_count_total} novas notas.",
                "progress": 100,
            },
            kind="sync",
            created_by=created_by,
        )
    except Exception as e:
        logger.error(f"Sync error: {e}")
        TaskStore.set_task(
            sync_id,
            {"status": "failed", "message": str(e), "progress": 0},
            kind="sync",
            created_by=created_by,
        )
    finally:
        db.close()


@router.post("/api/sync")
def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Iniciar sincronização de notas em background."""
    sync_id = f"sync_{request.client_id or 0}_{os.urandom(4).hex()}"
    background_tasks.add_task(
        background_sync,
        sync_id,
        request.client_id or 0,
        request.data_inicio,
        request.data_fim,
        request.tipo,
        current_user.username,
    )
    return {"task_id": sync_id}


@router.get("/api/tasks/{task_id}")
def get_task_status(task_id: str):
    """Obter status de uma tarefa em background."""
    status = TaskStore.get_task(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


class ClearLocalInvoicesRequest(BaseModel):
    invoice_ids: Optional[List[int]] = None
    client_id: Optional[int] = None
    tipo: Optional[str] = None
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None


def _apply_invoice_filters(
    query,
    client_id: Optional[int] = None,
    tipo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
):
    if client_id:
        query = query.filter(Invoice.client_id == client_id)
    if tipo:
        query = query.filter(Invoice.tipo == tipo)

    if data_inicio and data_fim:
        try:
            dt_inicio = datetime.datetime.strptime(data_inicio, "%d/%m/%Y").replace(hour=0, minute=0, second=0)
            dt_fim = datetime.datetime.strptime(data_fim, "%d/%m/%Y").replace(hour=23, minute=59, second=59)
            query = query.filter(Invoice.data_emissao >= dt_inicio, Invoice.data_emissao <= dt_fim)
        except Exception as e:
            logger.warning(f"Erro ao filtrar datas: {e}")

    return query


def _delete_invoices_by_ids(db: Session, invoice_ids: List[int]) -> int:
    if not invoice_ids:
        return 0
    db.query(BatchImportItem).filter(BatchImportItem.invoice_id.in_(invoice_ids)).update(
        {BatchImportItem.invoice_id: None},
        synchronize_session=False,
    )
    deleted_count = (
        db.query(Invoice)
        .filter(Invoice.id.in_(invoice_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted_count or 0)


@router.get("/api/invoices", response_model=List[InvoiceResponse])
def list_invoices(
    client_id: Optional[int] = None,
    tipo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Listar notas com filtros opcionais."""
    query = _apply_invoice_filters(
        db.query(Invoice),
        client_id=client_id,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    return query.order_by(Invoice.data_emissao.desc()).all()


@router.post("/api/invoices/limpar-local")
def clear_local_invoices(
    payload: ClearLocalInvoicesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove registros de notas apenas da base local (sem cancelar na Sefin/ADN) para permitir resincronização limpa."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem limpar notas da base local.")

    ids = [int(i) for i in (payload.invoice_ids or []) if i]
    if ids:
        target_rows = db.query(Invoice.id).filter(Invoice.id.in_(ids)).all()
    else:
        has_filter = any([payload.client_id, payload.tipo, payload.data_inicio and payload.data_fim])
        if not has_filter:
            raise HTTPException(
                status_code=400,
                detail="Informe `invoice_ids` ou pelo menos um filtro (`client_id`, `tipo` ou período) para limpar.",
            )
        query = _apply_invoice_filters(
            db.query(Invoice.id),
            client_id=payload.client_id,
            tipo=payload.tipo,
            data_inicio=payload.data_inicio,
            data_fim=payload.data_fim,
        )
        target_rows = query.all()

    target_ids = [row[0] for row in target_rows]
    removed = _delete_invoices_by_ids(db, target_ids)
    return {
        "removidas": removed,
        "message": f"{removed} nota(s) removida(s) da base local.",
    }


@router.delete("/api/invoices/{invoice_id}")
def delete_local_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove uma nota específica apenas da base local (sem cancelar na Sefin/ADN)."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem remover notas da base local.")

    exists = db.query(Invoice.id).filter(Invoice.id == invoice_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Nota não encontrada.")

    removed = _delete_invoices_by_ids(db, [invoice_id])
    return {
        "removidas": removed,
        "message": "Nota removida da base local.",
    }

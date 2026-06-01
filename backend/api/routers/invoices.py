"""Router de Notas - Sincronização e listagem de NFSe."""

import os
import logging
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal
from backend.models import Client, Invoice
from backend.schemas import SyncRequest, InvoiceResponse
from backend.api.deps import get_nfse_client
from backend.api.state import tasks_status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["invoices", "sync"])


def background_sync(sync_id: str, client_id: int, data_inicio: str, data_fim: str, tipo: str):
    """Executa sincronização em background."""
    db = SessionLocal()
    try:
        tasks_status[sync_id] = {"status": "running", "message": "Iniciando processo...", "progress": 0}

        clients_to_sync = []
        if client_id:
            c = db.query(Client).filter(Client.id == client_id).first()
            if c:
                clients_to_sync.append(c)
        else:
            clients_to_sync = db.query(Client).all()

        if not clients_to_sync:
            tasks_status[sync_id] = {"status": "failed", "message": "Nenhum cliente encontrado.", "progress": 0}
            return

        new_count_total = 0
        total_clients = len(clients_to_sync)
        for idx, client_db in enumerate(clients_to_sync):
            client_start = int((idx / total_clients) * 100)
            client_end = int(((idx + 1) / total_clients) * 100)
            client_span = max(1, client_end - client_start)
            try:
                tasks_status[sync_id].update(
                    {
                        "message": f"[{idx + 1}/{len(clients_to_sync)}] Autenticando {client_db.razao_social}...",
                        "progress": min(client_start + 10, 95),
                    }
                )
                nfse = get_nfse_client(client_db)
                nfse.autenticar()

                tasks_status[sync_id].update(
                    {
                        "message": f"[{idx + 1}/{len(clients_to_sync)}] Buscando notas {tipo} para {client_db.razao_social}...",
                        "progress": min(client_start + 20, 95),
                    }
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
                    tasks_status[sync_id].update(
                        {
                            "message": f"[{idx + 1}/{len(clients_to_sync)}] Processando nota {note_idx + 1}/{len(notas)} de {client_db.razao_social}...",
                            "progress": min(note_progress, client_end),
                        }
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
                        )
                        db.add(new_invoice)
                        new_count += 1

                db.commit()
                new_count_total += new_count
                tasks_status[sync_id].update(
                    {
                        "message": f"[{idx + 1}/{len(clients_to_sync)}] Concluído para {client_db.razao_social}.",
                        "progress": client_end,
                    }
                )
            except Exception as ce:
                logger.error(f"Erro no cliente {client_db.razao_social}: {ce}")
                tasks_status[sync_id].update(
                    {
                        "message": f"[{idx + 1}/{len(clients_to_sync)}] Falha ao processar {client_db.razao_social}: {ce}",
                        "progress": max(client_start, tasks_status[sync_id].get("progress", 0)),
                    }
                )

        tasks_status[sync_id] = {
            "status": "completed",
            "message": f"Sincronização concluída. {new_count_total} novas notas.",
            "progress": 100,
        }
    except Exception as e:
        logger.error(f"Sync error: {e}")
        tasks_status[sync_id] = {"status": "failed", "message": str(e), "progress": 0}
    finally:
        db.close()


@router.post("/api/sync")
def trigger_sync(request: SyncRequest, background_tasks: BackgroundTasks):
    """Iniciar sincronização de notas em background."""
    sync_id = f"sync_{request.client_id or 0}_{os.urandom(4).hex()}"
    background_tasks.add_task(
        background_sync, sync_id, request.client_id or 0, request.data_inicio, request.data_fim, request.tipo
    )
    return {"task_id": sync_id}


@router.get("/api/tasks/{task_id}")
def get_task_status(task_id: str):
    """Obter status de uma tarefa em background."""
    status = tasks_status.get(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("/api/invoices", response_model=List[InvoiceResponse])
def list_invoices(
    client_id: Optional[int] = None,
    tipo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Listar notas com filtros opcionais."""
    query = db.query(Invoice)
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

    return query.order_by(Invoice.data_emissao.desc()).all()

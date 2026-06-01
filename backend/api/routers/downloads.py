"""Router de Downloads - Sincronização com portal e download de arquivos."""

import logging
import os
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_

from backend.api.deps import get_nfse_client
from backend.api.state import tasks_status
from backend.database import SessionLocal
from backend.models import Client, Invoice
from backend.schemas import DownloadRequest
from core.xml_parser import extrair_dados_nfse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/download", tags=["download"])


def _path_candidates(path: str) -> List[str]:
    """Gera variações úteis de um caminho para tentar localizar o arquivo no disco."""
    raw = (path or "").strip()
    if not raw:
        return []

    candidates = [raw, os.path.normpath(raw)]

    stripped_parts = []
    for part in Path(raw).parts:
        if part in (os.sep, ""):
            continue
        stripped = part.strip()
        if stripped:
            stripped_parts.append(stripped)

    if stripped_parts:
        if raw.startswith(os.sep):
            candidates.append(os.sep + os.path.join(*stripped_parts))
        else:
            candidates.append(os.path.join(*stripped_parts))

    unique_candidates = []
    for candidate in candidates:
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def _resolve_existing_path(path: str) -> Optional[str]:
    """Retorna o primeiro caminho existente dentre as variações tentadas."""
    for candidate in _path_candidates(path):
        if Path(candidate).exists():
            return candidate
    return None


def _find_invoice_by_path(db, path: str) -> Optional[Invoice]:
    """Procura uma nota cujo XML/PDF corresponda ao caminho informado."""
    candidates = _path_candidates(path)
    if not candidates:
        return None

    return db.query(Invoice).filter(or_(Invoice.xml_path.in_(candidates), Invoice.pdf_path.in_(candidates))).first()


def _infer_file_kind(path: str, invoice: Optional[Invoice] = None) -> Optional[str]:
    """Tenta identificar se o arquivo é XML ou PDF."""
    lower_path = (path or "").lower()
    if lower_path.endswith(".xml"):
        return "xml"
    if lower_path.endswith(".pdf"):
        return "pdf"

    if invoice:
        if invoice.xml_path and path == invoice.xml_path:
            return "xml"
        if invoice.pdf_path and path == invoice.pdf_path:
            return "pdf"
    return None


def _clear_stale_reference(db, invoice: Invoice, kind: str) -> None:
    """Remove a referência antiga do arquivo no banco antes de baixar novamente."""
    if kind == "xml":
        invoice.xml_path = None
    elif kind == "pdf":
        invoice.pdf_path = None
    db.add(invoice)
    db.commit()


def _download_invoice_file(db, invoice: Invoice, requested_path: str) -> Optional[str]:
    """Baixa novamente o XML/PDF da nota usando o portal, se houver URL salva."""
    client_db = db.query(Client).filter(Client.id == invoice.client_id).first()
    if not client_db:
        logger.warning(f"Cliente {invoice.client_id} não encontrado para recuperar {requested_path}")
        return None

    nfse = get_nfse_client(client_db)
    nfse.autenticar()
    nfse.define_tipo_consulta(invoice.tipo or "outros")

    kind = _infer_file_kind(requested_path, invoice)
    if not kind:
        return None

    _clear_stale_reference(db, invoice, kind)

    if kind == "xml" and invoice.download_url_xml:
        new_path = nfse.baixar_xml(invoice.download_url_xml, invoice.status or "gerada", invoice.data_emissao)
    elif kind == "pdf" and invoice.download_url_pdf:
        new_path = nfse.baixar_pdf(invoice.download_url_pdf, invoice.status or "gerada", invoice.data_emissao)
    else:
        return None

    if new_path:
        if kind == "xml":
            invoice.xml_path = new_path
        if kind == "pdf":
            invoice.pdf_path = new_path
        db.add(invoice)
        db.commit()

    return new_path or None


def _ensure_file_available(db, path: str) -> Optional[str]:
    """Tenta localizar o arquivo no disco ou recuperá-lo pelo portal."""
    existing = _resolve_existing_path(path)
    if existing:
        return existing

    invoice = _find_invoice_by_path(db, path)
    if not invoice:
        return None

    try:
        recovered = _download_invoice_file(db, invoice, path)
        if recovered:
            return _resolve_existing_path(recovered) or recovered
    except Exception as exc:
        logger.warning(f"Falha ao recuperar arquivo '{path}' do portal: {exc}")

    return None


def background_download(task_id: str, invoice_ids: List[int], client_id: int, action_type: str):
    """Executa downloads em background."""
    db = SessionLocal()
    try:
        tasks_status[task_id] = {"status": "running", "message": "Iniciando downloads...", "progress": 0}

        clients_cache = {}

        invoices = db.query(Invoice).filter(Invoice.id.in_(invoice_ids)).all()
        total = len(invoices)

        if total == 0:
            tasks_status[task_id] = {
                "status": "failed",
                "message": "Nenhuma nota encontrada para baixar.",
                "progress": 0,
            }
            return

        for idx, invoice in enumerate(invoices):
            try:
                actual_client_id = invoice.client_id
                invoice_base = int((idx / total) * 100)
                invoice_end = int(((idx + 1) / total) * 100)
                invoice_span = max(1, invoice_end - invoice_base)

                if actual_client_id not in clients_cache:
                    client_db = db.query(Client).filter(Client.id == actual_client_id).first()
                    if not client_db:
                        logger.warning(f"Cliente {actual_client_id} não encontrado para a nota {invoice.id}")
                        continue

                    tasks_status[task_id]["message"] = f"Autenticando {client_db.razao_social}..."
                    nfse = get_nfse_client(client_db)
                    nfse.autenticar()
                    nfse.define_tipo_consulta(action_type)
                    clients_cache[actual_client_id] = nfse

                nfse = clients_cache[actual_client_id]
                tasks_status[task_id].update(
                    {
                        "message": f"Baixando nota {invoice.numero} ({idx + 1}/{total})...",
                        "progress": min(invoice_base + 5, 95),
                    }
                )

                if invoice.download_url_xml and not invoice.xml_path:
                    tasks_status[task_id].update(
                        {
                            "message": f"Baixando XML da nota {invoice.numero} ({idx + 1}/{total})...",
                            "progress": min(invoice_base + int(invoice_span * 0.35), 95),
                        }
                    )
                    invoice.xml_path = nfse.baixar_xml(invoice.download_url_xml, invoice.status, invoice.data_emissao)
                    if invoice.xml_path:
                        try:
                            dados = extrair_dados_nfse(invoice.xml_path)
                            if dados.get("valor", 0) > 0:
                                invoice.valor = dados.get("valor")
                            if dados.get("numero"):
                                invoice.numero = dados.get("numero")
                            db.add(invoice)
                        except Exception:
                            pass

                if invoice.download_url_pdf and not invoice.pdf_path:
                    tasks_status[task_id].update(
                        {
                            "message": f"Baixando PDF da nota {invoice.numero} ({idx + 1}/{total})...",
                            "progress": min(invoice_base + int(invoice_span * 0.75), 95),
                        }
                    )
                    invoice.pdf_path = nfse.baixar_pdf(invoice.download_url_pdf, invoice.status, invoice.data_emissao)
                    db.add(invoice)

                db.commit()
                tasks_status[task_id].update(
                    {"progress": invoice_end, "message": f"Nota {invoice.numero} concluída ({idx + 1}/{total})."}
                )
            except Exception as ne:
                logger.error(f"Erro na nota {invoice.id}: {ne}")
                continue

        tasks_status[task_id] = {"status": "completed", "message": "Downloads concluídos com sucesso.", "progress": 100}
    except Exception as e:
        logger.error(f"Download error: {e}")
        tasks_status[task_id] = {"status": "failed", "message": str(e), "progress": 0}
    finally:
        db.close()


@router.post("/sync-portal")
def sync_portal_download(payload: DownloadRequest, background_tasks: BackgroundTasks):
    """Dispara download de notas do portal para o disco em background."""
    task_id = f"dl_{payload.client_id}_{os.urandom(4).hex()}"
    background_tasks.add_task(background_download, task_id, payload.invoice_ids, payload.client_id, payload.action_type)
    return {"task_id": task_id}


@router.get("/file")
def download_file(path: str):
    """Servir arquivo do disco para o navegador."""
    db = SessionLocal()
    try:
        resolved_path = _ensure_file_available(db, path)
    finally:
        db.close()

    if not resolved_path:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no servidor e não pôde ser recuperado.")

    filename = os.path.basename(resolved_path)
    return FileResponse(
        resolved_path, filename=filename, headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/batch")
def create_batch_zip(payload: dict):
    """Criar arquivo ZIP temporário com arquivos selecionados."""
    paths = payload.get("arquivos", [])
    if not paths:
        raise HTTPException(status_code=400, detail="Nenhum arquivo selecionado.")

    db = SessionLocal()
    try:
        resolved_paths = []
        for path in paths:
            if not path:
                continue
            resolved = _ensure_file_available(db, path)
            if resolved:
                resolved_paths.append(resolved)
    finally:
        db.close()

    if not resolved_paths:
        raise HTTPException(status_code=404, detail="Nenhum arquivo pôde ser recuperado para gerar o lote.")

    os.makedirs("downloads/temp", exist_ok=True)
    zip_name = f"lote_{os.urandom(4).hex()}.zip"
    zip_path = os.path.join("downloads/temp", zip_name)

    with zipfile.ZipFile(zip_path, "w") as zipf:
        for p in resolved_paths:
            if p and os.path.exists(p):
                ext = p.split(".")[-1].upper()
                zipf.write(p, f"{ext}/{os.path.basename(p)}")

    return {"zip_path": zip_path}

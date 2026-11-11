"""Router de Downloads - Sincronização com portal e download de arquivos."""

import logging
import os
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_

from app.api.deps import BACKEND_DIR, DOWNLOADS_DIR, get_nfse_client, has_valid_certificate
from app.api.state import tasks_status
from app.database import SessionLocal
from app.models import Client, Invoice
from app.schemas import DownloadRequest, HtmlToXmlRequest, XmlToPdfRequest
from app.services.html_xml_service import (
    converter_arquivo_html_para_xml,
    converter_html_para_xml,
    converter_xml_para_pdf_pynfse,
    enriquecer_nota_com_xml,
    extrair_chave_do_xml,
    obter_html_e_gerar_xml_pdf,
)
from pynfse.xml_parser import extrair_dados_nfse

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

    expanded_candidates = list(candidates)
    for c in candidates:
        p = Path(c)
        if not p.is_absolute():
            expanded_candidates.append(str(BACKEND_DIR / p))

    unique_candidates = []
    for candidate in expanded_candidates:
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
    """Tenta identificar se o arquivo é XML ou PDF (incluindo HTML fallback)."""
    lower_path = (path or "").lower()
    if lower_path.endswith(".xml"):
        return "xml"
    if lower_path.endswith(".pdf") or lower_path.endswith(".html"):
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


def _converter_html_para_xml_local(invoice: Optional[Invoice], html_path: str) -> Optional[str]:
    """Converte um arquivo HTML de impressão baixado em XML padrão SPED e enriquece a nota."""
    resolved_html = _resolve_existing_path(html_path) or html_path
    if not resolved_html or not Path(resolved_html).exists():
        return None

    try:
        xml_path = converter_arquivo_html_para_xml(resolved_html)
        if invoice and xml_path:
            enriquecer_nota_com_xml(invoice, xml_path=xml_path)
        return xml_path
    except Exception as e:
        logger.error(f"Erro ao converter HTML '{resolved_html}' para XML: {e}")
        return None


def _gerar_pdf_local(invoice: Invoice) -> Optional[str]:
    """Gera o PDF localmente a partir do XML da nota utilizando DanfseGenerator do pynfse."""
    if not invoice.xml_path:
        return None
    resolved_xml = _resolve_existing_path(str(invoice.xml_path))
    if not resolved_xml:
        return None

    try:
        res = converter_xml_para_pdf_pynfse(
            xml_path=resolved_xml,
            status=invoice.status or "NORMAL",
        )
        return res.get("pdf_path")
    except Exception as e:
        logger.error(f"Erro ao gerar PDF local a partir do XML para a nota {invoice.numero}: {e}")
        return None


def _usa_usuario_senha_sem_certificado(nfse, client_db: Optional[Client] = None) -> bool:
    """Verifica se o cliente utiliza autenticação por usuário e senha e não possui certificado digital."""
    if hasattr(nfse, "usa_apenas_credenciais"):
        return bool(nfse.usa_apenas_credenciais())
    if getattr(nfse, "caminho_pfx", None) and getattr(nfse, "senha_pfx", None):
        return False
    return not has_valid_certificate(client_db)


def _obter_xml_e_pdf_via_html_impressao(nfse, invoice: Invoice) -> dict:
    """
    Obtém diretamente o HTML de impressão da nota (evitando chamadas diretas de download
    de XML/PDF que falham com 403) e gera o XML e o PDF localmente.
    """
    if (
        invoice.pdf_path
        and invoice.pdf_path.lower().endswith(".html")
        and (not invoice.xml_path or not _resolve_existing_path(invoice.xml_path))
    ):
        existing_html = _resolve_existing_path(invoice.pdf_path)
        if existing_html:
            _converter_html_para_xml_local(invoice, existing_html)

    existing_xml = _resolve_existing_path(invoice.xml_path) if invoice.xml_path else None
    existing_pdf = (
        _resolve_existing_path(invoice.pdf_path)
        if invoice.pdf_path and not invoice.pdf_path.lower().endswith(".html")
        else None
    )

    if existing_xml and not existing_pdf:
        generated_pdf = _gerar_pdf_local(invoice)
        if generated_pdf:
            invoice.pdf_path = generated_pdf
            existing_pdf = generated_pdf

    if existing_xml and existing_pdf:
        return {"xml_path": existing_xml, "pdf_path": existing_pdf}

    ref_chave = invoice.chave or invoice.download_url_xml or invoice.download_url_pdf
    if not ref_chave:
        return {"xml_path": invoice.xml_path, "pdf_path": invoice.pdf_path}

    res = obter_html_e_gerar_xml_pdf(
        nfse=nfse,
        url_ou_chave=ref_chave,
        status=invoice.status or "gerada",
        data_emissao=invoice.data_emissao,
    )

    xml_path = res.get("xml_path")
    pdf_path = res.get("pdf_path")
    dados = res.get("dados") or {}

    if xml_path:
        enriquecer_nota_com_xml(invoice, xml_path=xml_path, dados=dados)

    if pdf_path:
        invoice.pdf_path = pdf_path
    elif invoice.xml_path:
        generated_pdf = _gerar_pdf_local(invoice)
        if generated_pdf:
            invoice.pdf_path = generated_pdf

    return {"xml_path": invoice.xml_path, "pdf_path": invoice.pdf_path}


def _sincronizar_arquivos_nota_certificado(
    nfse,
    invoice: Invoice,
    baixar_xml: bool = True,
    baixar_pdf: bool = True,
    old_pdf_path: Optional[str] = None,
    on_progress=None,
) -> None:
    """Executa o download de XML e/ou PDF para clientes com certificado, com fallbacks locais."""
    status_nota = invoice.status or "gerada"

    if baixar_xml and invoice.download_url_xml and not invoice.xml_path:
        if on_progress:
            on_progress("xml")
        xml_path = nfse.baixar_xml(invoice.download_url_xml, status_nota, invoice.data_emissao)
        if not xml_path and old_pdf_path and old_pdf_path.lower().endswith(".html"):
            xml_path = _converter_html_para_xml_local(invoice, old_pdf_path)
        elif xml_path:
            enriquecer_nota_com_xml(invoice, xml_path=xml_path)

    if baixar_pdf:
        if invoice.download_url_pdf and not invoice.pdf_path:
            if on_progress:
                on_progress("pdf")
            try:
                invoice.pdf_path = nfse.baixar_pdf(invoice.download_url_pdf, status_nota, invoice.data_emissao)
            except Exception as e:
                logger.warning(f"Falha ao baixar PDF da nota {invoice.numero}: {e}")
                invoice.pdf_path = None

        if invoice.pdf_path and invoice.pdf_path.lower().endswith(".html") and not invoice.xml_path:
            if on_progress:
                on_progress("html_to_xml")
            _converter_html_para_xml_local(invoice, invoice.pdf_path)

        if (
            not invoice.pdf_path
            or invoice.pdf_path.lower().endswith(".html")
            or not Path(invoice.pdf_path).exists()
        ) and invoice.xml_path:
            if on_progress:
                on_progress("local_pdf")
            generated_pdf = _gerar_pdf_local(invoice)
            if generated_pdf:
                invoice.pdf_path = generated_pdf


def _download_invoice_file(db, invoice: Invoice, requested_path: str) -> Optional[str]:
    """Baixa novamente o XML/PDF da nota usando o portal, se houver URL salva."""
    client_db = db.query(Client).filter(Client.id == invoice.client_id).first()
    if not client_db:
        logger.warning(f"Cliente {invoice.client_id} não encontrado para recuperar {requested_path}")
        return None

    kind = _infer_file_kind(requested_path, invoice)
    if not kind:
        return None

    old_pdf_path = invoice.pdf_path
    old_xml_path = invoice.xml_path

    # Se já temos HTML ou XML local, tenta gerar localmente antes de autenticar no portal
    if kind == "xml" and old_pdf_path and old_pdf_path.lower().endswith(".html"):
        existing_html = _resolve_existing_path(old_pdf_path)
        if existing_html:
            xml_local = _converter_html_para_xml_local(invoice, existing_html)
            if xml_local:
                db.add(invoice)
                db.commit()
                return xml_local

    nfse = get_nfse_client(client_db)
    if kind == "pdf" and old_xml_path and _resolve_existing_path(old_xml_path):
        if _usa_usuario_senha_sem_certificado(nfse, client_db):
            pdf_local = _gerar_pdf_local(invoice)
            if pdf_local:
                invoice.pdf_path = pdf_local
                db.add(invoice)
                db.commit()
                return pdf_local

    nfse.autenticar()
    nfse.define_tipo_consulta(invoice.tipo or "outros")

    _clear_stale_reference(db, invoice, kind)

    if _usa_usuario_senha_sem_certificado(nfse, client_db):
        if old_pdf_path and old_pdf_path.lower().endswith(".html") and not invoice.pdf_path:
            invoice.pdf_path = old_pdf_path
        if old_xml_path and not invoice.xml_path:
            invoice.xml_path = old_xml_path
        _obter_xml_e_pdf_via_html_impressao(nfse, invoice)
    else:
        _sincronizar_arquivos_nota_certificado(
            nfse,
            invoice,
            baixar_xml=(kind == "xml"),
            baixar_pdf=(kind == "pdf"),
            old_pdf_path=old_pdf_path,
        )

    db.add(invoice)
    db.commit()
    return invoice.xml_path if kind == "xml" else invoice.pdf_path


def _ensure_file_available(db, path: str) -> Optional[str]:
    """Tenta localizar o arquivo no disco ou recuperá-lo pelo portal."""
    existing = _resolve_existing_path(path)
    if existing:
        if existing.lower().endswith(".html"):
            invoice = _find_invoice_by_path(db, path)
            xml_conv = _converter_html_para_xml_local(invoice, existing)
            if xml_conv:
                try:
                    res = converter_xml_para_pdf_pynfse(
                        xml_path=xml_conv,
                        status=(invoice.status if invoice else "NORMAL") or "NORMAL",
                    )
                    pdf_conv = res.get("pdf_path")
                    if pdf_conv and Path(pdf_conv).exists():
                        if invoice:
                            invoice.pdf_path = pdf_conv
                            db.add(invoice)
                            db.commit()
                        return pdf_conv
                except Exception as exc:
                    logger.warning(f"Falha ao converter XML gerado para PDF via pynfse: {exc}")
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

                if _usa_usuario_senha_sem_certificado(nfse):
                    precisa_xml = not invoice.xml_path or not _resolve_existing_path(invoice.xml_path)
                    precisa_pdf = (
                        not invoice.pdf_path
                        or invoice.pdf_path.lower().endswith(".html")
                        or not _resolve_existing_path(invoice.pdf_path)
                    )
                    if precisa_xml or precisa_pdf:
                        tasks_status[task_id].update(
                            {
                                "message": f"Obtendo HTML de impressão e gerando XML/PDF da nota {invoice.numero} ({idx + 1}/{total})...",
                                "progress": min(invoice_base + int(invoice_span * 0.5), 95),
                            }
                        )
                        _obter_xml_e_pdf_via_html_impressao(nfse, invoice)
                else:
                    def _update_step(step: str, _num=invoice.numero, _i=idx + 1, _base=invoice_base, _span=invoice_span):
                        if step == "xml":
                            tasks_status[task_id].update(
                                {
                                    "message": f"Baixando XML da nota {_num} ({_i}/{total})...",
                                    "progress": min(_base + int(_span * 0.35), 95),
                                }
                            )
                        elif step == "pdf":
                            tasks_status[task_id].update(
                                {
                                    "message": f"Baixando PDF da nota {_num} ({_i}/{total})...",
                                    "progress": min(_base + int(_span * 0.75), 95),
                                }
                            )
                        elif step == "html_to_xml":
                            tasks_status[task_id]["message"] = f"Convertendo HTML da nota {_num} para XML ({_i}/{total})..."
                        elif step == "local_pdf":
                            tasks_status[task_id]["message"] = f"Gerando PDF local da nota {_num} ({_i}/{total})..."

                    _sincronizar_arquivos_nota_certificado(nfse, invoice, on_progress=_update_step)

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

    temp_dir = DOWNLOADS_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"lote_{os.urandom(4).hex()}.zip"
    zip_path = str(temp_dir / zip_name)

    with zipfile.ZipFile(zip_path, "w") as zipf:
        for p in resolved_paths:
            if p and os.path.exists(p):
                ext = p.split(".")[-1].upper()
                zipf.write(p, f"{ext}/{os.path.basename(p)}")

    return {"zip_path": zip_path}


@router.post("/html-to-xml")
def convert_html_to_xml_endpoint(payload: HtmlToXmlRequest):
    """
    Converte o HTML de impressão baixado da NFS-e em XML padrão SPED.
    Aceita `html_content`, `html_path` ou `invoice_id`.
    """
    db = SessionLocal()
    try:
        invoice: Optional[Invoice] = None
        if payload.invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()

        html_path = payload.html_path
        if not html_path and invoice and invoice.pdf_path and invoice.pdf_path.lower().endswith(".html"):
            html_path = invoice.pdf_path

        resolved_html = _resolve_existing_path(html_path) if html_path else None
        if resolved_html and not invoice:
            invoice = _find_invoice_by_path(db, html_path or resolved_html)

        xml_path: Optional[str] = None
        if payload.html_content:
            xml_content = converter_html_para_xml(payload.html_content)
            chave = extrair_chave_do_xml(xml_content)
            if payload.xml_output_path:
                out_p = Path(payload.xml_output_path)
            elif resolved_html:
                out_str = (
                    str(Path(resolved_html).with_suffix(".xml"))
                    .replace("/pdfs/", "/xmls/")
                    .replace("\\pdfs\\", "\\xmls\\")
                )
                out_p = Path(out_str)
            else:
                out_dir = DOWNLOADS_DIR / "converted" / "xmls"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_p = out_dir / f"{chave or 'nfse_convertida'}.xml"
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(xml_content, encoding="utf-8")
            xml_path = str(out_p)
        elif resolved_html and Path(resolved_html).exists():
            xml_path = converter_arquivo_html_para_xml(resolved_html, payload.xml_output_path)
            xml_content = Path(xml_path).read_text(encoding="utf-8")
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe um `html_content` válido ou um `html_path` / `invoice_id` com HTML existente.",
            )

        dados = extrair_dados_nfse(xml_path) if xml_path else {}
        if not invoice and dados.get("chave"):
            invoice = db.query(Invoice).filter(Invoice.chave == dados["chave"]).first()

        if invoice and xml_path:
            enriquecer_nota_com_xml(invoice, xml_path=xml_path, dados=dados)
            db.add(invoice)
            db.commit()

        return {
            "xml_path": xml_path,
            "xml_content": xml_content,
            "chave": dados.get("chave") or extrair_chave_do_xml(xml_content),
            "invoice_id": invoice.id if invoice else None,
            "dados": dados,
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.error(f"Erro ao converter HTML em XML: {exc}")
        raise HTTPException(status_code=500, detail=f"Falha ao converter HTML em XML: {exc}")
    finally:
        db.close()


@router.post("/xml-to-pdf")
def convert_xml_to_pdf_endpoint(payload: XmlToPdfRequest, download: bool = False):
    """
    Recebe o XML gerado (`xml_content`, `xml_path` ou `invoice_id`) e converte
    em PDF (DANFSe) utilizando `pynfse.danfse_generator.DanfseGenerator`.
    """
    db = SessionLocal()
    try:
        invoice: Optional[Invoice] = None
        if payload.invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()

        xml_path = payload.xml_path
        if not xml_path and invoice and invoice.xml_path:
            xml_path = invoice.xml_path

        resolved_xml = _resolve_existing_path(xml_path) if xml_path else None
        if resolved_xml and not invoice:
            invoice = _find_invoice_by_path(db, xml_path or resolved_xml)

        if not payload.xml_content and not resolved_xml:
            raise HTTPException(
                status_code=400,
                detail="Informe `xml_content`, `xml_path` ou `invoice_id` com XML disponível para gerar o PDF.",
            )

        status_nota = payload.status or (invoice.status if invoice else "NORMAL") or "NORMAL"
        default_dir = DOWNLOADS_DIR / "converted"

        res = converter_xml_para_pdf_pynfse(
            xml_content=payload.xml_content,
            xml_path=resolved_xml or xml_path,
            pdf_output_path=payload.pdf_output_path,
            status=status_nota,
            default_dir=default_dir,
        )

        pdf_path = res.get("pdf_path")
        saved_xml_path = res.get("xml_path")
        chave = res.get("chave")
        dados = res.get("dados") or {}

        if not invoice and chave:
            invoice = db.query(Invoice).filter(Invoice.chave == chave).first()

        if invoice:
            if pdf_path:
                invoice.pdf_path = pdf_path
            enriquecer_nota_com_xml(
                invoice,
                xml_path=saved_xml_path if (saved_xml_path and not invoice.xml_path) else None,
                dados=dados,
                apenas_se_vazio=True,
            )
            db.add(invoice)
            db.commit()

        if download and pdf_path and os.path.exists(pdf_path):
            filename = os.path.basename(pdf_path)
            return FileResponse(
                pdf_path,
                media_type="application/pdf",
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        return {
            "pdf_path": pdf_path,
            "xml_path": saved_xml_path,
            "chave": chave,
            "invoice_id": invoice.id if invoice else None,
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.error(f"Erro ao converter XML em PDF via pynfse: {exc}")
        raise HTTPException(status_code=500, detail=f"Falha ao converter XML em PDF via pynfse: {exc}")
    finally:
        db.close()

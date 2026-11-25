"""Processador sequencial, persistente e idempotente para emissão de lotes NFS-e."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.api.permissions import is_admin_user
from app.core.spreadsheets import parse_date_iso
from app.models import BatchImport, BatchImportItem, Client, Invoice, User
from app.services.adn_service import AdnService
from app.services.batch_emission.validator import (
    build_emission_context_for_item,
    calculate_batch_item_taxes,
    recompute_batch_counters,
)
from app.services.email_service import EmailService
from pynfse.adn import (
    AdnNfseClient,
    XsdValidator,
    build_dps_xml,
    clean_digits,
    formatar_id_dps,
)

logger = logging.getLogger(__name__)

_BATCH_LOCKS: Dict[str, asyncio.Lock] = {}
STALE_PROCESSING_SECONDS = int(os.getenv("BATCH_STALE_PROCESSING_SECONDS") or "300")


def _utc_now_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _get_batch_lock(batch_id: str) -> asyncio.Lock:
    if batch_id not in _BATCH_LOCKS:
        _BATCH_LOCKS[batch_id] = asyncio.Lock()
    return _BATCH_LOCKS[batch_id]


def recover_stale_processing_batch(
    db: Session,
    batch: BatchImport,
    *,
    ignore_local_lock: bool = False,
) -> bool:
    """Recupera lotes presos em `PROCESSING` após queda/reinício sem lock ativo."""
    if batch.status != "PROCESSING":
        return False
    if not ignore_local_lock and _get_batch_lock(batch.id).locked():
        return False

    items = db.query(BatchImportItem).filter(BatchImportItem.batch_id == batch.id).all()
    processing_items = [it for it in items if it.status == "PROCESSING"]
    if not processing_items:
        recompute_batch_counters(db, batch)
        db.commit()
        db.refresh(batch)
        return True

    threshold = int(os.getenv("BATCH_STALE_PROCESSING_SECONDS") or str(STALE_PROCESSING_SECONDS))
    timestamps = [it.processed_at or batch.created_at for it in processing_items if (it.processed_at or batch.created_at)]
    if not timestamps:
        return False
    last_touch = max(
        ts.astimezone(datetime.UTC).replace(tzinfo=None) if ts.tzinfo else ts
        for ts in timestamps
    )
    now_utc_naive = _utc_now_naive()
    candidate_ages = [(now_utc_naive - last_touch).total_seconds()]
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        db_local_now = db.execute(text("SELECT LOCALTIMESTAMP")).scalar()
        if db_local_now is not None:
            candidate_ages.append((db_local_now.replace(tzinfo=None) - last_touch).total_seconds())
    plausible_ages = [age for age in candidate_ages if age >= -5.0]
    effective_age = min(plausible_ages) if plausible_ages else max(candidate_ages)
    if effective_age < threshold:
        return False

    for it in processing_items:
        if it.id_dps:
            it.status = "UNKNOWN"
            it.last_error = "Processamento anterior interrompido (tempo limite/reinício). Consulte o ADN antes de reenviar."
        else:
            it.status = "RETRY"
            it.last_error = "Processamento anterior interrompido antes da reserva de DPS; liberado para reenvio."
        db.add(it)

    recompute_batch_counters(db, batch)
    db.commit()
    db.refresh(batch)
    return True


def _extract_adn_error(res: Dict[str, Any]) -> str:
    resp = res.get("resposta")
    if isinstance(resp, dict):
        erros = resp.get("erros") or resp.get("Mensagens") or resp.get("mensagens")
        if erros:
            return str(erros)[:500]
        if resp.get("mensagem"):
            return str(resp["mensagem"])[:500]
    return str(res.get("erro") or res.get("mensagem") or f"HTTP {res.get('status_code') or 0}")[:500]


def _upsert_invoice_for_item(
    db: Session,
    *,
    client_db: Client,
    item: BatchImportItem,
    prestador: Dict[str, Any],
    tomador: Dict[str, Any],
    servico: Dict[str, Any],
    tributacao_calc: Dict[str, Any],
    ambiente: str,
    comp_iso: str,
    chave_gerada: str,
    status_nota: str,
    xml_dps_path: Optional[str],
    xml_nfse_path: Optional[str],
    pdf_path: Optional[str],
    ultimo_erro: Optional[str],
    created_by_user_id: Optional[int] = None,
    created_by_username: Optional[str] = None,
) -> Invoice:
    reforma = tributacao_calc.get("reforma_tributaria") or {}
    iss_info = tributacao_calc.get("iss") or {}
    tomador_doc = clean_digits(tomador.get("documento") or "")
    payload_resumo = json.dumps(
        {
            "prestador": prestador,
            "tomador": tomador,
            "servico": servico,
            "ambiente": ambiente,
            "data_competencia": comp_iso,
        },
        ensure_ascii=False,
    )

    existing = None
    if item.invoice_id:
        existing = db.query(Invoice).filter(Invoice.id == item.invoice_id).first()
    if not existing:
        existing = db.query(Invoice).filter(Invoice.chave == chave_gerada).first()

    if existing:
        existing.status = status_nota
        existing.chave = chave_gerada
        existing.xml_path = xml_nfse_path or existing.xml_path or xml_dps_path
        existing.pdf_path = pdf_path or existing.pdf_path
        existing.xml_dps_path = xml_dps_path or existing.xml_dps_path
        existing.tentativas_envio = item.attempts
        existing.ultimo_erro_envio = ultimo_erro
        existing.payload_dps_json = payload_resumo
        if not existing.ambiente:
            existing.ambiente = ambiente
        if created_by_user_id and not existing.created_by_user_id:
            existing.created_by_user_id = created_by_user_id
        if created_by_username and not existing.created_by_username:
            existing.created_by_username = created_by_username
        db.add(existing)
        db.flush()
        return existing

    nova = Invoice(
        client_id=client_db.id,
        numero=str(item.numero_dps or 1),
        chave=chave_gerada,
        status=status_nota,
        tipo="emitidas",
        valor=float(tributacao_calc.get("valor_servicos") or 0.0),
        valor_liquido=float(tributacao_calc.get("valor_liquido") or 0.0),
        valor_iss=float(iss_info.get("valor") or 0.0),
        valor_ibs=float(reforma.get("valor_ibs") or 0.0),
        valor_cbs=float(reforma.get("valor_cbs") or 0.0),
        id_dps=item.id_dps,
        serie_dps=item.serie_dps,
        numero_dps=item.numero_dps,
        c_trib_nac=servico.get("cTribNac"),
        c_nbs=servico.get("cNBS"),
        c_class_trib=servico.get("cClassTrib"),
        cst_ibscbs=servico.get("cst"),
        tomador_documento=tomador_doc or None,
        tomador_nome=tomador.get("razao_social"),
        tomador_email=tomador.get("email"),
        xml_dps_path=xml_dps_path,
        xml_path=xml_nfse_path or xml_dps_path,
        pdf_path=pdf_path,
        tentativas_envio=item.attempts,
        ultimo_erro_envio=ultimo_erro,
        payload_dps_json=payload_resumo,
        created_by_user_id=created_by_user_id,
        created_by_username=created_by_username,
        ambiente=ambiente,
    )
    db.add(nova)
    db.flush()
    return nova


async def process_batch_items(
    db: Session,
    batch_id: str,
    item_ids: Optional[List[str]] = None,
    transmitir: bool = True,
    enviar_email: bool = False,
    allowed_statuses: Optional[set[str]] = None,
    current_user: Optional[User] = None,
) -> BatchImport:
    """Processa sequencialmente os itens selecionados de um lote sem manter transações durante chamadas HTTP."""
    lock = _get_batch_lock(batch_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="Já existe um processamento ativo para este lote.")

    eligible_statuses = allowed_statuses or {"VALID", "RETRY"}

    async with lock:
        batch = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Lote não encontrado.")
        if batch.status == "CANCELLED":
            raise HTTPException(status_code=409, detail="Este lote foi cancelado.")
        recover_stale_processing_batch(db, batch, ignore_local_lock=True)

        client_db, _, signer, ambiente = AdnService._resolver_prestador_e_certificado(
            db=db,
            client_id=batch.client_id,
            prestador_payload=None,
            cert_b64=None,
            cert_password=None,
            ambiente_req=batch.ambiente,
        )
        if not client_db:
            raise HTTPException(status_code=404, detail="Prestador do lote não encontrado.")

        q = (
            db.query(BatchImportItem.id)
            .filter(
                BatchImportItem.batch_id == batch_id,
                BatchImportItem.status.in_(eligible_statuses),
            )
            .order_by(BatchImportItem.row_number.asc())
        )
        if item_ids:
            q = q.filter(BatchImportItem.id.in_(item_ids))
        target_ids = [row[0] for row in q.all()]

        if not target_ids:
            raise HTTPException(
                status_code=400,
                detail="Nenhum item elegível ('VALID' ou 'RETRY') selecionado para processamento.",
            )

        res_upd = db.execute(
            update(BatchImport)
            .where(
                BatchImport.id == batch_id,
                BatchImport.status.notin_(["PROCESSING", "CANCELLED"]),
            )
            .values(status="PROCESSING")
        )
        if res_upd.rowcount == 0:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Este lote já está em processamento ou foi cancelado.",
            )
        db.commit()

        cert_pem = signer.get_pem_certificate() if signer else None
        key_pem = signer.get_pem_private_key() if signer else None
        assinado_com_certificado = bool(cert_pem and key_pem)
        include_global = is_admin_user(current_user) if current_user is not None else False

        try:
            for cur_item_id in target_ids:
                stage = "preparação do item"
                try:
                    # --- Transação 1: prepara contexto, reserva DPS e marca PROCESSING ---
                    db.expire_all()
                    batch_cur = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
                    if not batch_cur or batch_cur.status == "CANCELLED":
                        break

                    item = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()
                    if not item or item.status not in eligible_statuses:
                        continue

                    client_cur = db.query(Client).filter(Client.id == batch_cur.client_id).first()
                    payload = json.loads(item.payload_json)
                    comp_iso = parse_date_iso(payload.get("competencia")) or datetime.date.today().isoformat()

                    stage = "cálculo tributário SSoT"
                    prestador, tomador, servico, _, _ = build_emission_context_for_item(
                        db,
                        client_cur,
                        payload,
                        include_global=include_global,
                    )
                    tributacao_calc = calculate_batch_item_taxes(
                        prestador,
                        servico,
                        data_competencia=comp_iso,
                    )

                    stage = "reserva de numeração DPS"
                    if item.numero_dps:
                        serie = item.serie_dps or (client_cur.serie_dps_padrao or "900")
                        numero = item.numero_dps
                        id_dps = item.id_dps or formatar_id_dps(
                            prestador.get("codigo_municipio", "3201308"),
                            prestador.get("cnpj") or "",
                            serie,
                            numero,
                        )
                    else:
                        serie, numero, id_dps = AdnService.reservar_proximo_numero_dps(
                            db=db,
                            client_id=client_cur.id,
                            serie_dps=item.serie_dps or client_cur.serie_dps_padrao,
                            codigo_municipio=prestador.get("codigo_municipio"),
                            documento_prestador=prestador.get("cnpj"),
                        )
                        item = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()

                    item.serie_dps = serie
                    item.numero_dps = numero
                    item.id_dps = id_dps
                    item.attempts = (item.attempts or 0) + 1
                    item.status = "PROCESSING"
                    item.processed_at = _utc_now_naive()
                    db.add(item)
                    db.commit()  # Libera transação antes de assinar e chamar ADN

                    # Monta e assina DPS fora da transação de banco
                    stage = "geração do XML da DPS"
                    xml_bruto = build_dps_xml(
                        prestador=prestador,
                        tomador=tomador,
                        servico=servico,
                        tributacao=tributacao_calc,
                        serie_dps=serie,
                        numero_dps=numero,
                        data_competencia=comp_iso,
                        ambiente=ambiente,
                        incluir_ibscbs=True,
                    )
                    stage = "assinatura digital A1"
                    xml_assinado = signer.sign_xml(xml_bruto, tag_to_sign="infDPS") if signer is not None else xml_bruto
                    stage = "validação XSD v1.01"
                    xsd_pos = XsdValidator.validar_dps(xml_assinado)
                    if not xsd_pos.get("valido"):
                        item_upd = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()
                        item_upd.status = "REJECTED"
                        item_upd.last_error = "; ".join(
                            xsd_pos.get("erros") or ["XML assinado falhou na validação XSD v1.01."]
                        )[:500]
                        item_upd.processed_at = _utc_now_naive()
                        db.add(item_upd)
                        recompute_batch_counters(db, db.query(BatchImport).filter(BatchImport.id == batch_id).first())
                        db.commit()
                        continue

                    stage = "gravação do XML em disco"
                    xml_dps_path = AdnService._salvar_xml_disco(xml_assinado, "dps", f"{id_dps}.xml")

                    # --- Chamada externa ao ADN sem transação aberta ---
                    stage = "transmissão ao ADN"
                    final_status = "RETRY"
                    ultimo_erro: Optional[str] = None
                    chave_gerada = item.chave_acesso or id_dps.replace("DPS", "").ljust(50, "0")[:50]
                    xml_nfse_path: Optional[str] = None
                    inv_status = "dps_gerada"

                    if transmitir and assinado_com_certificado:
                        try:
                            adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
                            res_adn = await adn_client.emitir_dps(xml_assinado)
                            sc = int(res_adn.get("status_code") or 0)
                            has_transport_err = bool(res_adn.get("erro") or res_adn.get("erro_transporte"))

                            if res_adn.get("sucesso"):
                                final_status = "AUTHORIZED"
                                inv_status = "gerada"
                                chave_gerada = res_adn.get("chave_acesso") or chave_gerada
                                if res_adn.get("nfse_xml"):
                                    xml_nfse_path = AdnService._salvar_xml_disco(
                                        res_adn["nfse_xml"], "nfse", f"{chave_gerada}.xml"
                                    )
                            elif 400 <= sc < 500 and not has_transport_err:
                                final_status = "REJECTED"
                                inv_status = "rejeitada"
                                ultimo_erro = _extract_adn_error(res_adn)
                            else:
                                # Falha de transporte/timeout/5xx após envio: resultado desconhecido (exige consulta prévia)
                                final_status = "UNKNOWN"
                                inv_status = "fila_contingencia"
                                ultimo_erro = (
                                    f"Resultado incerto após transmissão ({_extract_adn_error(res_adn)}). "
                                    "Consulte o ADN antes de reenviar."
                                )
                        except Exception as exc:
                            final_status = "UNKNOWN"
                            inv_status = "fila_contingencia"
                            ultimo_erro = f"Falha de comunicação com resultado incerto: {exc}"
                    elif transmitir and not assinado_com_certificado:
                        final_status = "RETRY"
                        inv_status = "fila_contingencia"
                        ultimo_erro = "Certificado A1 (.pfx) não configurado no prestador."
                    else:
                        final_status = "RETRY"
                        inv_status = "dps_gerada"
                        ultimo_erro = "DPS gerada localmente sem transmissão (transmitir=False)."

                    xml_principal = xml_nfse_path or xml_dps_path
                    pdf_path = AdnService._gerar_pdf_danfse(xml_principal, chave_gerada, status="NORMAL")

                    # --- Transação 2: persiste resultado no item e na Invoice ---
                    stage = "persistência do resultado"
                    batch_cur = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
                    client_cur = db.query(Client).filter(Client.id == batch_cur.client_id).first()
                    item_upd = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()

                    audit_uid, audit_uname = AdnService._resolve_audit_user(db, current_user)
                    inv = _upsert_invoice_for_item(
                        db,
                        client_db=client_cur,
                        item=item_upd,
                        prestador=prestador,
                        tomador=tomador,
                        servico=servico,
                        tributacao_calc=tributacao_calc,
                        ambiente=ambiente,
                        comp_iso=comp_iso,
                        chave_gerada=chave_gerada,
                        status_nota=inv_status,
                        xml_dps_path=xml_dps_path,
                        xml_nfse_path=xml_nfse_path,
                        pdf_path=pdf_path,
                        ultimo_erro=ultimo_erro,
                        created_by_user_id=audit_uid,
                        created_by_username=audit_uname or batch_cur.created_by,
                    )

                    item_upd.invoice_id = inv.id
                    item_upd.chave_acesso = chave_gerada if final_status == "AUTHORIZED" else item_upd.chave_acesso
                    item_upd.status = final_status
                    item_upd.last_error = ultimo_erro
                    item_upd.processed_at = _utc_now_naive()
                    db.add(item_upd)
                    recompute_batch_counters(db, batch_cur)
                    db.commit()

                    if enviar_email and final_status == "AUTHORIZED" and tomador.get("email"):
                        try:
                            EmailService.enviar_nfse_por_email(
                                client_db=client_cur,
                                invoice=inv,
                                destinatario=tomador["email"],
                            )
                        except Exception as exc:
                            err_msg = getattr(exc, "detail", None) or str(exc)
                            logger.warning("Erro ao enviar e-mail automático do item %s: %s", cur_item_id, err_msg)
                except Exception as exc:
                    logger.exception("Erro ao processar item %s do lote %s na etapa '%s': %s", cur_item_id, batch_id, stage, exc)
                    db.rollback()
                    item_err = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()
                    if item_err:
                        item_err.status = "REJECTED"
                        item_err.last_error = f"Falha na {stage}: {exc}"[:500]
                        item_err.processed_at = _utc_now_naive()
                        db.add(item_err)
                    batch_err = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
                    if batch_err:
                        recompute_batch_counters(db, batch_err)
                    db.commit()
                    continue
        finally:
            try:
                stuck_items = (
                    db.query(BatchImportItem)
                    .filter(
                        BatchImportItem.batch_id == batch_id,
                        BatchImportItem.id.in_(target_ids),
                        BatchImportItem.status == "PROCESSING",
                    )
                    .all()
                )
                for st in stuck_items:
                    if st.id_dps:
                        st.status = "UNKNOWN"
                        st.last_error = "Processamento interrompido durante a execução. Consulte o ADN antes de reenviar."
                    else:
                        st.status = "RETRY"
                        st.last_error = "Processamento interrompido antes da reserva de DPS; liberado para reenvio."
                    db.add(st)
                batch_final = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
                if batch_final:
                    recompute_batch_counters(db, batch_final)
                    db.commit()
                    db.refresh(batch_final)
            except Exception:
                db.rollback()
                batch_final = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
        return batch_final


async def resolve_unknown_and_retry_batch(
    db: Session,
    batch_id: str,
    item_ids: Optional[List[str]] = None,
    transmitir: bool = True,
    enviar_email: bool = False,
    current_user: Optional[User] = None,
) -> BatchImport:
    """Consulta DPS em estado `UNKNOWN` no ADN antes de permitir reenvio, e reprocessa itens `RETRY`."""
    batch = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    if batch.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="Lote cancelado.")
    recover_stale_processing_batch(db, batch)

    client_db, _, signer, ambiente = AdnService._resolver_prestador_e_certificado(
        db=db,
        client_id=batch.client_id,
        prestador_payload=None,
        cert_b64=None,
        cert_password=None,
        ambiente_req=batch.ambiente,
    )
    cert_pem = signer.get_pem_certificate() if signer else None
    key_pem = signer.get_pem_private_key() if signer else None

    q_unk = db.query(BatchImportItem).filter(
        BatchImportItem.batch_id == batch_id,
        BatchImportItem.status == "UNKNOWN",
    )
    if item_ids:
        q_unk = q_unk.filter(BatchImportItem.id.in_(item_ids))
    unknown_items = q_unk.order_by(BatchImportItem.row_number.asc()).all()

    if unknown_items and cert_pem and key_pem:
        adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
        for unk in unknown_items:
            if not unk.id_dps:
                unk.status = "RETRY"
                db.add(unk)
                continue
            try:
                res_cons = await adn_client.consultar_dps(unk.id_dps)
            except Exception as exc:
                unk.last_error = f"Falha de rede ao consultar DPS no ADN: {exc}"[:500]
                db.add(unk)
                continue

            sc = int(res_cons.get("status_code") or 0)
            if res_cons.get("sucesso") and sc == 200:
                conteudo = res_cons.get("conteudo")
                chave_rec = None
                nfse_xml_rec = None
                if isinstance(conteudo, dict):
                    chave_rec = conteudo.get("chNFSe") or conteudo.get("chaveAcesso")
                    b64 = conteudo.get("nfseXmlGZipB64") or conteudo.get("arquivoXml")
                    if b64:
                        try:
                            nfse_xml_rec = adn_client.descompactar_xml_gzip_b64(b64)
                        except Exception:
                            nfse_xml_rec = None
                if chave_rec and not nfse_xml_rec:
                    try:
                        res_nf = await adn_client.consultar_nfse(chave_rec)
                    except Exception:
                        res_nf = {}
                    if res_nf.get("sucesso"):
                        conteudo_nf = res_nf.get("conteudo") or res_nf.get("xml")
                        if isinstance(conteudo_nf, dict):
                            b64_nf = conteudo_nf.get("nfseXmlGZipB64") or conteudo_nf.get("arquivoXml")
                            if b64_nf:
                                try:
                                    nfse_xml_rec = adn_client.descompactar_xml_gzip_b64(b64_nf)
                                except Exception:
                                    nfse_xml_rec = None
                            elif conteudo_nf.get("xml"):
                                nfse_xml_rec = conteudo_nf.get("xml")
                        elif isinstance(conteudo_nf, str) and conteudo_nf.strip():
                            nfse_xml_rec = conteudo_nf

                xml_nfse_path = None
                if nfse_xml_rec and chave_rec:
                    xml_nfse_path = AdnService._salvar_xml_disco(nfse_xml_rec, "nfse", f"{chave_rec}.xml")
                pdf_path = AdnService._gerar_pdf_danfse(xml_nfse_path, chave_rec or unk.id_dps, status="NORMAL")

                unk.status = "AUTHORIZED"
                unk.chave_acesso = chave_rec or unk.chave_acesso
                unk.last_error = None
                unk.processed_at = _utc_now_naive()
                if unk.invoice_id:
                    inv = db.query(Invoice).filter(Invoice.id == unk.invoice_id).first()
                    if inv:
                        inv.status = "gerada"
                        inv.chave = unk.chave_acesso or inv.chave
                        inv.xml_path = xml_nfse_path or inv.xml_path
                        inv.pdf_path = pdf_path or inv.pdf_path
                        inv.ultimo_erro_envio = None
                        db.add(inv)
                db.add(unk)
            elif sc == 404:
                # Confirmado que o ADN não recebeu a DPS: seguro reenviar usando o mesmo id_dps
                unk.status = "RETRY"
                unk.last_error = "DPS não localizada na Sefin (404). Liberada para reenvio seguro."
                db.add(unk)
            else:
                unk.last_error = f"Consulta prévia ao ADN indisponível (HTTP {sc}); mantida como UNKNOWN."
                db.add(unk)
        recompute_batch_counters(db, batch)
        db.commit()

    # Processa todos os itens em estado RETRY selecionados
    q_retry = db.query(BatchImportItem.id).filter(
        BatchImportItem.batch_id == batch_id,
        BatchImportItem.status == "RETRY",
    )
    if item_ids:
        q_retry = q_retry.filter(BatchImportItem.id.in_(item_ids))
    retry_ids = [r[0] for r in q_retry.all()]

    if retry_ids:
        return await process_batch_items(
            db=db,
            batch_id=batch_id,
            item_ids=retry_ids,
            transmitir=transmitir,
            enviar_email=enviar_email,
            allowed_statuses={"RETRY"},
            current_user=current_user,
        )

    db.refresh(batch)
    return batch

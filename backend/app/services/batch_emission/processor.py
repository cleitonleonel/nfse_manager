"""Processador sequencial, persistente e idempotente para emissão de lotes NFS-e."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.spreadsheets import parse_date_iso
from app.models import BatchImport, BatchImportItem, Client, Invoice
from app.services.adn_service import AdnService
from app.services.batch_emission.validator import (
    build_emission_context_for_item,
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


def _get_batch_lock(batch_id: str) -> asyncio.Lock:
    if batch_id not in _BATCH_LOCKS:
        _BATCH_LOCKS[batch_id] = asyncio.Lock()
    return _BATCH_LOCKS[batch_id]


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

        try:
            for cur_item_id in target_ids:
                # --- Transação 1: prepara XML, reserva DPS e marca PROCESSING ---
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

                prestador, tomador, servico, _, _ = build_emission_context_for_item(db, client_cur, payload)
                tributacao_calc = AdnService._calcular_tributacao_se_necessario(
                    prestador=prestador,
                    servico=servico,
                    tributacao_informada=None,
                    data_competencia=comp_iso,
                )

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
                item.processed_at = datetime.datetime.now(datetime.UTC)
                db.add(item)
                db.commit()  # Libera transação antes de assinar e chamar ADN

            # Monta e assina DPS fora da transação de banco
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
                xml_assinado = signer.sign_xml(xml_bruto, tag_to_sign="infDPS") if signer is not None else xml_bruto
                xsd_pos = XsdValidator.validar_dps(xml_assinado)
                if not xsd_pos.get("valido"):
                    item_upd = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()
                    item_upd.status = "REJECTED"
                    item_upd.last_error = "XML assinado falhou na validação XSD v1.01."
                    recompute_batch_counters(db, db.query(BatchImport).filter(BatchImport.id == batch_id).first())
                    db.commit()
                    continue

                xml_dps_path = AdnService._salvar_xml_disco(xml_assinado, "dps", f"{id_dps}.xml")

                # --- Chamada externa ao ADN sem transação aberta ---
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
                batch_cur = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
                client_cur = db.query(Client).filter(Client.id == batch_cur.client_id).first()
                item_upd = db.query(BatchImportItem).filter(BatchImportItem.id == cur_item_id).first()

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
                )

                item_upd.invoice_id = inv.id
                item_upd.chave_acesso = chave_gerada if final_status == "AUTHORIZED" else item_upd.chave_acesso
                item_upd.status = final_status
                item_upd.last_error = ultimo_erro
                item_upd.processed_at = datetime.datetime.now(datetime.UTC)
                db.add(item_upd)
                recompute_batch_counters(db, batch_cur)
                db.commit()

                if enviar_email and final_status == "AUTHORIZED" and tomador.get("email"):
                    try:
                        EmailService.send_nfse_email(
                            destinatario=tomador["email"],
                            client_db=client_cur,
                            chave_acesso=chave_gerada,
                            xml_path=xml_principal,
                            pdf_path=pdf_path,
                        )
                    except Exception as exc:
                        logger.warning("Erro ao enviar e-mail automático do item %s: %s", cur_item_id, exc)
        finally:
            batch_final = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
            if batch_final:
                recompute_batch_counters(db, batch_final)
                db.commit()
                db.refresh(batch_final)
        return batch_final


async def resolve_unknown_and_retry_batch(
    db: Session,
    batch_id: str,
    item_ids: Optional[List[str]] = None,
    transmitir: bool = True,
    enviar_email: bool = False,
) -> BatchImport:
    """Consulta DPS em estado `UNKNOWN` no ADN antes de permitir reenvio, e reprocessa itens `RETRY`."""
    batch = db.query(BatchImport).filter(BatchImport.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    if batch.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="Lote cancelado.")

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
            res_cons = await adn_client.consultar_dps(unk.id_dps)
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
                    res_nf = await adn_client.consultar_nfse(chave_rec)
                    if res_nf.get("sucesso") and res_nf.get("xml"):
                        nfse_xml_rec = res_nf["xml"]

                xml_nfse_path = None
                if nfse_xml_rec and chave_rec:
                    xml_nfse_path = AdnService._salvar_xml_disco(nfse_xml_rec, "nfse", f"{chave_rec}.xml")
                pdf_path = AdnService._gerar_pdf_danfse(xml_nfse_path, chave_rec or unk.id_dps, status="NORMAL")

                unk.status = "AUTHORIZED"
                unk.chave_acesso = chave_rec or unk.chave_acesso
                unk.last_error = None
                unk.processed_at = datetime.datetime.now(datetime.UTC)
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
        )

    db.refresh(batch)
    return batch

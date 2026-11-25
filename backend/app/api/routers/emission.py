"""Router de Emissão, Cancelamento e Substituição de NFS-e via ADN / Sefin Nacional (v1.01).

Delega toda a orquestração ao `AdnService`, que utiliza as classes e funções do pacote `pynfse.adn`
(`/home/cleiton/PyJobs/MeusProjetos/emissor_nfse`).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.permissions import assert_client_access, assert_invoice_access, is_admin_user
from app.api.routers.auth import get_current_user, require_admin_user
from app.database import get_db
from app.models import Customer, Invoice, ServiceItem, User
from app.schemas import (
    CancelarNfseRequest,
    EmitirDpsLoteRequest,
    EmitirDpsRequest,
    EnviarEmailNfseRequest,
    InvoiceResponse,
    ReenviarFilaRequest,
    SincronizarCofreAdnRequest,
    SubstituirNfseRequest,
)
from app.services.adn_service import AdnService
from app.services.audit_service import AuditService, get_client_ip
from app.services.scheduler_service import SchedulerService
from pynfse.adn import clean_digits

router = APIRouter(
    prefix="/api/adn",
    tags=["adn", "emission", "events"],
    dependencies=[Depends(get_current_user)],
)


def _assert_linked_registry_access(
    db: Session,
    current_user: User,
    customer_id: Optional[int],
    service_item_id: Optional[int],
) -> None:
    if is_admin_user(current_user):
        return
    if customer_id:
        cust = db.query(Customer).filter(Customer.id == customer_id).first()
        if cust:
            assert_client_access(db, current_user, cust.client_id, allow_none_for_admin=False)
    if service_item_id:
        s_item = db.query(ServiceItem).filter(ServiceItem.id == service_item_id).first()
        if s_item:
            assert_client_access(db, current_user, s_item.client_id, allow_none_for_admin=False)


@router.post("/dps/preview")
def preview_dps_xml(
    req: EmitirDpsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera o XML da DPS v1.01 com o cálculo tributário integrado e valida contra DPS_v1.01.xsd."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    _assert_linked_registry_access(db, current_user, req.customer_id, req.service_item_id)
    return AdnService.preview_dps(db=db, req=req)


@router.post("/dps/emitir")
async def emitir_dps_adn(
    req: EmitirDpsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera, valida XSD, assina com Certificado A1 e transmite a DPS v1.01 ao ADN / Sefin Nacional."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    _assert_linked_registry_access(db, current_user, req.customer_id, req.service_item_id)
    try:
        res = await AdnService.emitir_dps(db=db, req=req, current_user=current_user)
    except HTTPException as exc:
        AuditService.record(
            db,
            action="emission.emit_dps",
            entity_type="invoice",
            client_id=req.client_id,
            current_user=current_user,
            summary=f"Falha na emissão de DPS (HTTP {exc.status_code}).",
            details={"status_code": exc.status_code, "detail": exc.detail, "ambiente": req.ambiente},
            status="error",
            ip_address=get_client_ip(request),
            commit=True,
        )
        raise

    AuditService.record(
        db,
        action="emission.emit_dps",
        entity_type="invoice",
        entity_id=res.get("invoice_id"),
        client_id=req.client_id,
        current_user=current_user,
        summary=f"Emissão de DPS concluída (status={res.get('status_nota')}, chave={res.get('chave_acesso')}).",
        details={
            "id_dps": res.get("id_dps"),
            "chave_acesso": res.get("chave_acesso"),
            "status_nota": res.get("status_nota"),
            "transmitir": req.transmitir,
            "ambiente": req.ambiente,
            "ultimo_erro_envio": res.get("ultimo_erro_envio"),
        },
        status="success" if res.get("status_nota") != "rejeitada" else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/dps/emitir-lote")
async def emitir_dps_lote_adn(
    req: EmitirDpsLoteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Emite múltiplas DPS v1.01 em lote para o mesmo prestador, consolidando o status de cada item."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    for item in req.itens:
        _assert_linked_registry_access(db, current_user, item.customer_id, item.service_item_id)
    res = await AdnService.emitir_dps_lote(db=db, req=req, current_user=current_user)
    AuditService.record(
        db,
        action="emission.emit_lote",
        entity_type="emission_batch",
        client_id=req.client_id,
        current_user=current_user,
        summary=(
            f"Emissão em lote legado ({res.get('total', 0)} itens: "
            f"autorizadas={res.get('autorizadas', 0)}, erros={res.get('erros', 0)})."
        ),
        details={
            "total": res.get("total"),
            "autorizadas": res.get("autorizadas"),
            "fila_contingencia": res.get("fila_contingencia"),
            "geradas_offline": res.get("geradas_offline"),
            "erros": res.get("erros"),
            "ambiente": req.ambiente,
        },
        status="success" if res.get("erros", 0) == 0 else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/nfse/cancelar")
async def cancelar_nfse_adn(
    req: CancelarNfseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera o evento e101101 (<pedRegEvento versao="1.01">), valida XSD, assina e transmite o cancelamento ao ADN."""
    invoice_db: Optional[Invoice] = None
    if req.invoice_id is not None:
        invoice_db = db.query(Invoice).filter(Invoice.id == req.invoice_id).first()
        if not invoice_db:
            raise HTTPException(status_code=404, detail=f"Nota fiscal ID {req.invoice_id} não encontrada.")
    if not invoice_db and req.chave_nfse:
        chave_busca = clean_digits(req.chave_nfse)
        invoice_db = db.query(Invoice).filter(Invoice.chave == chave_busca).first()

    if invoice_db:
        assert_invoice_access(db, current_user, invoice_db)
        if req.client_id is not None and invoice_db.client_id is not None and int(invoice_db.client_id) != int(req.client_id):
            raise HTTPException(
                status_code=400,
                detail="A nota fiscal informada não pertence à empresa (client_id) selecionada.",
            )
        if req.chave_nfse and invoice_db.chave and clean_digits(req.chave_nfse) != clean_digits(invoice_db.chave):
            raise HTTPException(
                status_code=400,
                detail="A chave da NFS-e informada diverge da nota fiscal localizada no banco.",
            )

    effective_client_id = req.client_id or (invoice_db.client_id if invoice_db else None)
    assert_client_access(db, current_user, effective_client_id, allow_none_for_admin=False)
    res = await AdnService.cancelar_nfse(db=db, req=req)
    ok_adn = bool(not req.transmitir or (res.get("retorno_adn") or {}).get("sucesso"))
    AuditService.record(
        db,
        action="emission.cancel_nfse",
        entity_type="invoice",
        entity_id=res.get("invoice_id") or res.get("chave_nfse"),
        client_id=effective_client_id,
        current_user=current_user,
        summary=f"Solicitação de cancelamento da NFS-e {res.get('chave_nfse')} (ok={ok_adn}).",
        details={
            "chave_nfse": res.get("chave_nfse"),
            "transmitir": req.transmitir,
            "motivo_codigo": req.motivo_codigo,
            "retorno_adn": res.get("retorno_adn"),
        },
        status="success" if ok_adn else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/nfse/substituir")
async def substituir_nfse_adn(
    req: SubstituirNfseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Executa a Substituição de NFS-e via ADN / Sefin Nacional (v1.01)."""
    invoice_orig: Optional[Invoice] = None
    if req.invoice_id_substituida is not None:
        invoice_orig = db.query(Invoice).filter(Invoice.id == req.invoice_id_substituida).first()
        if not invoice_orig:
            raise HTTPException(
                status_code=404,
                detail=f"Nota fiscal original ID {req.invoice_id_substituida} não encontrada.",
            )
    if not invoice_orig and req.chave_nfse_substituida:
        chave_orig_busca = clean_digits(req.chave_nfse_substituida)
        invoice_orig = db.query(Invoice).filter(Invoice.chave == chave_orig_busca).first()

    if invoice_orig:
        assert_invoice_access(db, current_user, invoice_orig)
        if req.client_id is not None and invoice_orig.client_id is not None and int(invoice_orig.client_id) != int(req.client_id):
            raise HTTPException(
                status_code=400,
                detail="A nota fiscal original não pertence à empresa (client_id) selecionada.",
            )
        if (
            req.chave_nfse_substituida
            and invoice_orig.chave
            and clean_digits(req.chave_nfse_substituida) != clean_digits(invoice_orig.chave)
        ):
            raise HTTPException(
                status_code=400,
                detail="A chave da NFS-e a substituir diverge da nota fiscal original localizada no banco.",
            )

    effective_client_id = req.client_id or (invoice_orig.client_id if invoice_orig else None)
    assert_client_access(db, current_user, effective_client_id, allow_none_for_admin=False)
    res = await AdnService.substituir_nfse(db=db, req=req, current_user=current_user)
    ok_adn = bool(not req.transmitir or (res.get("envio_adn") or {}).get("sucesso"))
    AuditService.record(
        db,
        action="emission.substitute_nfse",
        entity_type="invoice",
        entity_id=res.get("invoice_id_substituta") or res.get("chave_nfse_substituida"),
        client_id=effective_client_id,
        current_user=current_user,
        summary=(
            f"Substituição da NFS-e {res.get('chave_nfse_substituida')} -> "
            f"{res.get('chave_nfse_substituta')} (status={res.get('status_nota')})."
        ),
        details={
            "invoice_id_substituida": res.get("invoice_id_substituida"),
            "invoice_id_substituta": res.get("invoice_id_substituta"),
            "chave_nfse_substituida": res.get("chave_nfse_substituida"),
            "chave_nfse_substituta": res.get("chave_nfse_substituta"),
            "status_nota": res.get("status_nota"),
            "transmitir": req.transmitir,
        },
        status="success" if ok_adn else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.get("/parametros-municipais/{cod_ibge}")
async def get_parametros_municipais(cod_ibge: str, ambiente: str = "homologacao"):
    """Consulta parâmetros municipais (convênio e alíquotas) no ADN."""
    return await AdnService.consultar_parametros_municipais(cod_ibge=cod_ibge, ambiente=ambiente)


@router.get("/fila", response_model=List[InvoiceResponse])
def listar_fila_contingencia(
    client_id: Optional[int] = Query(None, description="Filtrar fila por ID do Prestador"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todas as notas na fila de contingência / aguardando transmissão (dps_gerada ou fila_contingencia)."""
    allowed_ids = assert_client_access(db, current_user, client_id, allow_none_for_admin=True)
    return AdnService.listar_fila_contingencia(db=db, client_id=client_id, allowed_client_ids=allowed_ids)


@router.post("/fila/reenviar")
async def reenviar_fila_contingencia(
    req: ReenviarFilaRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retransmite para o ADN/Sefin Nacional as DPS pendentes na fila de contingência."""
    allowed_ids = assert_client_access(db, current_user, req.client_id, allow_none_for_admin=True)
    if allowed_ids is not None and req.invoice_ids:
        invs = db.query(Invoice).filter(Invoice.id.in_(req.invoice_ids)).all()
        for inv in invs:
            assert_invoice_access(db, current_user, inv)
    res = await AdnService.reenviar_fila_contingencia(db=db, req=req, allowed_client_ids=allowed_ids)
    AuditService.record(
        db,
        action="emission.fila_retry",
        entity_type="invoice",
        client_id=req.client_id,
        current_user=current_user,
        summary=(
            f"Reenvio da fila de contingência ({res.get('total_processadas', 0)} itens: "
            f"autorizadas={res.get('autorizadas', 0)}, falhas={res.get('falhas', 0)})."
        ),
        details={
            "invoice_ids": req.invoice_ids,
            "total_processadas": res.get("total_processadas"),
            "autorizadas": res.get("autorizadas"),
            "falhas": res.get("falhas"),
        },
        status="success" if res.get("falhas", 0) == 0 else "error",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/fila/{invoice_id}/consultar")
async def consultar_item_fila_contingencia(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consulta o status da DPS pendente diretamente no ADN/Sefin Nacional."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        assert_invoice_access(db, current_user, inv)
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Acesso negado a esta nota pendente.")
    res = await AdnService.consultar_item_fila_contingencia(db=db, invoice_id=invoice_id)
    AuditService.record(
        db,
        action="emission.fila_consultar",
        entity_type="invoice",
        entity_id=invoice_id,
        client_id=inv.client_id if inv else None,
        current_user=current_user,
        summary=f"Consulta de status da DPS na fila (invoice={invoice_id}, status={res.get('status_atual')}).",
        details=res,
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.delete("/fila/{invoice_id}")
def cancelar_item_fila_contingencia(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancela e remove um item pendente da fila de contingência."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        assert_invoice_access(db, current_user, inv)
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Acesso negado a esta nota pendente.")
    client_id = inv.client_id if inv else None
    res = AdnService.cancelar_item_fila_contingencia(db=db, invoice_id=invoice_id)
    AuditService.record(
        db,
        action="emission.fila_cancel",
        entity_type="invoice",
        entity_id=invoice_id,
        client_id=client_id,
        current_user=current_user,
        summary=f"Item pendente {invoice_id} removido da fila de contingência.",
        details=res,
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/nfse/{invoice_id}/enviar-email")
def enviar_nfse_email(
    invoice_id: int,
    req: EnviarEmailNfseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Envia o XML e o DANFSe (PDF) da NFS-e para o e-mail do tomador utilizando o SMTP do Prestador."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        assert_invoice_access(db, current_user, inv)
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Acesso negado a esta nota fiscal.")
    res = AdnService.enviar_email_nfse(db=db, invoice_id=invoice_id, req=req)
    AuditService.record(
        db,
        action="emission.send_email",
        entity_type="invoice",
        entity_id=invoice_id,
        client_id=inv.client_id if inv else None,
        current_user=current_user,
        summary=f"Envio de NFS-e {invoice_id} por e-mail para '{res.get('destinatario') or req.destinatario}'.",
        details={"destinatario": res.get("destinatario") or req.destinatario, "origem_smtp": res.get("origem_smtp")},
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.post("/cofre/sincronizar")
async def sincronizar_cofre_adn(
    req: SincronizarCofreAdnRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sincroniza o Cofre de Notas (emitidas e recebidas) diretamente do Ambiente Nacional via Certificado A1 (DistDFe/NSU)."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    try:
        res = await AdnService.sincronizar_cofre_adn(db=db, req=req)
    except HTTPException as exc:
        AuditService.record(
            db,
            action="emission.cofre_sync",
            entity_type="client",
            entity_id=req.client_id,
            client_id=req.client_id,
            current_user=current_user,
            summary=f"Falha ao sincronizar Cofre ADN (HTTP {exc.status_code}).",
            details={"status_code": exc.status_code, "detail": exc.detail},
            status="error",
            ip_address=get_client_ip(request),
            commit=True,
        )
        raise

    AuditService.record(
        db,
        action="emission.cofre_sync",
        entity_type="client",
        entity_id=req.client_id,
        client_id=req.client_id,
        current_user=current_user,
        summary=(
            f"Cofre ADN sincronizado (novas={res.get('novas_notas', 0)}, "
            f"atualizadas={res.get('notas_atualizadas', 0)}, parcial={res.get('parcial', False)})."
        ),
        details=res,
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res


@router.get("/worker/status")
def get_worker_status():
    """Retorna o status, intervalo e resultado da última execução do Worker Automático da Fila de Contingência."""
    return SchedulerService.get_status()


@router.post("/worker/trigger")
async def trigger_worker_cycle(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
):
    """Dispara imediatamente um ciclo do Worker de Retransmissão Automática da Fila de Contingência."""
    res = await SchedulerService.run_fila_retry_cycle()
    AuditService.record(
        db,
        action="system.worker_trigger",
        entity_type="system",
        current_user=_admin,
        summary=(
            f"Ciclo manual do worker disparado (processadas={res.get('total_processadas', 0)}, "
            f"autorizadas={res.get('autorizadas', 0)}, falhas={res.get('falhas', 0)})."
        ),
        details=res,
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res

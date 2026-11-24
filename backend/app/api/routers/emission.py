"""Router de Emissão, Cancelamento e Substituição de NFS-e via ADN / Sefin Nacional (v1.01).

Delega toda a orquestração ao `AdnService`, que utiliza as classes e funções do pacote `pynfse.adn`
(`/home/cleiton/PyJobs/MeusProjetos/emissor_nfse`).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera, valida XSD, assina com Certificado A1 e transmite a DPS v1.01 ao ADN / Sefin Nacional."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    _assert_linked_registry_access(db, current_user, req.customer_id, req.service_item_id)
    return await AdnService.emitir_dps(db=db, req=req, current_user=current_user)


@router.post("/dps/emitir-lote")
async def emitir_dps_lote_adn(
    req: EmitirDpsLoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Emite múltiplas DPS v1.01 em lote para o mesmo prestador, consolidando o status de cada item."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    for item in req.itens:
        _assert_linked_registry_access(db, current_user, item.customer_id, item.service_item_id)
    return await AdnService.emitir_dps_lote(db=db, req=req, current_user=current_user)


@router.post("/nfse/cancelar")
async def cancelar_nfse_adn(
    req: CancelarNfseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gera o evento e101101 (<pedRegEvento versao="1.01">), valida XSD, assina e transmite o cancelamento ao ADN."""
    invoice_db: Optional[Invoice] = None
    if req.invoice_id:
        invoice_db = db.query(Invoice).filter(Invoice.id == req.invoice_id).first()
    if not invoice_db and req.chave_nfse:
        chave_busca = clean_digits(req.chave_nfse)
        invoice_db = db.query(Invoice).filter(Invoice.chave == chave_busca).first()

    if invoice_db:
        assert_invoice_access(db, current_user, invoice_db)
    effective_client_id = req.client_id or (invoice_db.client_id if invoice_db else None)
    assert_client_access(db, current_user, effective_client_id, allow_none_for_admin=False)
    return await AdnService.cancelar_nfse(db=db, req=req)


@router.post("/nfse/substituir")
async def substituir_nfse_adn(
    req: SubstituirNfseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Executa a Substituição de NFS-e via ADN / Sefin Nacional (v1.01)."""
    invoice_orig: Optional[Invoice] = None
    if req.invoice_id_substituida:
        invoice_orig = db.query(Invoice).filter(Invoice.id == req.invoice_id_substituida).first()
    if not invoice_orig and req.chave_nfse_substituida:
        chave_orig_busca = clean_digits(req.chave_nfse_substituida)
        invoice_orig = db.query(Invoice).filter(Invoice.chave == chave_orig_busca).first()

    if invoice_orig:
        assert_invoice_access(db, current_user, invoice_orig)
    effective_client_id = req.client_id or (invoice_orig.client_id if invoice_orig else None)
    assert_client_access(db, current_user, effective_client_id, allow_none_for_admin=False)
    return await AdnService.substituir_nfse(db=db, req=req, current_user=current_user)


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retransmite para o ADN/Sefin Nacional as DPS pendentes na fila de contingência."""
    allowed_ids = assert_client_access(db, current_user, req.client_id, allow_none_for_admin=True)
    if allowed_ids is not None and req.invoice_ids:
        invs = db.query(Invoice).filter(Invoice.id.in_(req.invoice_ids)).all()
        for inv in invs:
            assert_invoice_access(db, current_user, inv)
    return await AdnService.reenviar_fila_contingencia(db=db, req=req, allowed_client_ids=allowed_ids)


@router.delete("/fila/{invoice_id}")
def cancelar_item_fila_contingencia(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancela e remove um item pendente da fila de contingência."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        assert_invoice_access(db, current_user, inv)
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Acesso negado a esta nota pendente.")
    return AdnService.cancelar_item_fila_contingencia(db=db, invoice_id=invoice_id)


@router.post("/nfse/{invoice_id}/enviar-email")
def enviar_nfse_email(
    invoice_id: int,
    req: EnviarEmailNfseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Envia o XML e o DANFSe (PDF) da NFS-e para o e-mail do tomador utilizando o SMTP do Prestador."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        assert_invoice_access(db, current_user, inv)
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Acesso negado a esta nota fiscal.")
    return AdnService.enviar_email_nfse(db=db, invoice_id=invoice_id, req=req)


@router.post("/cofre/sincronizar")
async def sincronizar_cofre_adn(
    req: SincronizarCofreAdnRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sincroniza o Cofre de Notas (emitidas e recebidas) diretamente do Ambiente Nacional via Certificado A1 (DistDFe/NSU)."""
    assert_client_access(db, current_user, req.client_id, allow_none_for_admin=False)
    return await AdnService.sincronizar_cofre_adn(db=db, req=req)


@router.get("/worker/status")
def get_worker_status():
    """Retorna o status, intervalo e resultado da última execução do Worker Automático da Fila de Contingência."""
    return SchedulerService.get_status()


@router.post("/worker/trigger")
async def trigger_worker_cycle(_admin: User = Depends(require_admin_user)):
    """Dispara imediatamente um ciclo do Worker de Retransmissão Automática da Fila de Contingência."""
    return await SchedulerService.run_fila_retry_cycle()

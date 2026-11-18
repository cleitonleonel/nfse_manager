"""Router de Emissão, Cancelamento e Substituição de NFS-e via ADN / Sefin Nacional (v1.01).

Delega toda a orquestração ao `AdnService`, que utiliza as classes e funções do pacote `pynfse.adn`
(`/home/cleiton/PyJobs/MeusProjetos/emissor_nfse`).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routers.auth import get_current_user, require_admin_user
from app.database import get_db
from app.models import User
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

router = APIRouter(
    prefix="/api/adn",
    tags=["adn", "emission", "events"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/dps/preview")
def preview_dps_xml(req: EmitirDpsRequest, db: Session = Depends(get_db)):
    """Gera o XML da DPS v1.01 com o cálculo tributário integrado e valida contra DPS_v1.01.xsd."""
    return AdnService.preview_dps(db=db, req=req)


@router.post("/dps/emitir")
async def emitir_dps_adn(req: EmitirDpsRequest, db: Session = Depends(get_db)):
    """Gera, valida XSD, assina com Certificado A1 e transmite a DPS v1.01 ao ADN / Sefin Nacional."""
    return await AdnService.emitir_dps(db=db, req=req)


@router.post("/dps/emitir-lote")
async def emitir_dps_lote_adn(req: EmitirDpsLoteRequest, db: Session = Depends(get_db)):
    """Emite múltiplas DPS v1.01 em lote para o mesmo prestador, consolidando o status de cada item."""
    return await AdnService.emitir_dps_lote(db=db, req=req)


@router.post("/nfse/cancelar")
async def cancelar_nfse_adn(req: CancelarNfseRequest, db: Session = Depends(get_db)):
    """Gera o evento e101101 (<pedRegEvento versao="1.01">), valida XSD, assina e transmite o cancelamento ao ADN."""
    return await AdnService.cancelar_nfse(db=db, req=req)


@router.post("/nfse/substituir")
async def substituir_nfse_adn(req: SubstituirNfseRequest, db: Session = Depends(get_db)):
    """Executa a Substituição de NFS-e via ADN / Sefin Nacional (v1.01)."""
    return await AdnService.substituir_nfse(db=db, req=req)


@router.get("/parametros-municipais/{cod_ibge}")
async def get_parametros_municipais(cod_ibge: str, ambiente: str = "homologacao"):
    """Consulta parâmetros municipais (convênio e alíquotas) no ADN."""
    return await AdnService.consultar_parametros_municipais(cod_ibge=cod_ibge, ambiente=ambiente)


@router.get("/fila", response_model=List[InvoiceResponse])
def listar_fila_contingencia(
    client_id: Optional[int] = Query(None, description="Filtrar fila por ID do Prestador"),
    db: Session = Depends(get_db),
):
    """Lista todas as notas na fila de contingência / aguardando transmissão (dps_gerada ou fila_contingencia)."""
    return AdnService.listar_fila_contingencia(db=db, client_id=client_id)


@router.post("/fila/reenviar")
async def reenviar_fila_contingencia(req: ReenviarFilaRequest, db: Session = Depends(get_db)):
    """Retransmite para o ADN/Sefin Nacional as DPS pendentes na fila de contingência."""
    return await AdnService.reenviar_fila_contingencia(db=db, req=req)


@router.delete("/fila/{invoice_id}")
def cancelar_item_fila_contingencia(invoice_id: int, db: Session = Depends(get_db)):
    """Cancela e remove um item pendente da fila de contingência."""
    return AdnService.cancelar_item_fila_contingencia(db=db, invoice_id=invoice_id)


@router.post("/nfse/{invoice_id}/enviar-email")
def enviar_nfse_email(invoice_id: int, req: EnviarEmailNfseRequest, db: Session = Depends(get_db)):
    """Envia o XML e o DANFSe (PDF) da NFS-e para o e-mail do tomador utilizando o SMTP do Prestador."""
    return AdnService.enviar_email_nfse(db=db, invoice_id=invoice_id, req=req)


@router.post("/cofre/sincronizar")
async def sincronizar_cofre_adn(req: SincronizarCofreAdnRequest, db: Session = Depends(get_db)):
    """Sincroniza o Cofre de Notas (emitidas e recebidas) diretamente do Ambiente Nacional via Certificado A1 (DistDFe/NSU)."""
    return await AdnService.sincronizar_cofre_adn(db=db, req=req)


@router.get("/worker/status")
def get_worker_status():
    """Retorna o status, intervalo e resultado da última execução do Worker Automático da Fila de Contingência."""
    return SchedulerService.get_status()


@router.post("/worker/trigger")
async def trigger_worker_cycle(_admin: User = Depends(require_admin_user)):
    """Dispara imediatamente um ciclo do Worker de Retransmissão Automática da Fila de Contingência."""
    return await SchedulerService.run_fila_retry_cycle()

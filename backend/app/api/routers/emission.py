"""Router de Emissão, Cancelamento e Substituição de NFS-e via ADN / Sefin Nacional (v1.01).

Delega toda a orquestração ao `AdnService`, que utiliza as classes e funções do pacote `pynfse.adn`
(`/home/cleiton/PyJobs/MeusProjetos/emissor_nfse`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CancelarNfseRequest, EmitirDpsRequest, SubstituirNfseRequest
from app.services.adn_service import AdnService

router = APIRouter(prefix="/api/adn", tags=["adn", "emission", "events"])


@router.post("/dps/preview")
def preview_dps_xml(req: EmitirDpsRequest, db: Session = Depends(get_db)):
    """Gera o XML da DPS v1.01 com o cálculo tributário integrado e valida contra DPS_v1.01.xsd."""
    return AdnService.preview_dps(db=db, req=req)


@router.post("/dps/emitir")
async def emitir_dps_adn(req: EmitirDpsRequest, db: Session = Depends(get_db)):
    """Gera, valida XSD, assina com Certificado A1 e transmite a DPS v1.01 ao ADN / Sefin Nacional."""
    return await AdnService.emitir_dps(db=db, req=req)


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

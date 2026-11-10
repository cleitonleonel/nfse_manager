"""Router de Catálogos Tributários e de Serviços da NFS-e Nacional (ADN / Sefin Nacional v1.01).

Delega as consultas à camada `AdnService` (que consome o pacote `pynfse.adn`).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.adn_service import AdnService

router = APIRouter(prefix="/api/catalogs", tags=["catalogs"])


@router.get("/cst")
def get_cst_table(
    apenas_nfse: bool = Query(False, description="Filtrar apenas CSTs com classificações aplicáveis à NFS-e"),
):
    """Lista os 18 Códigos de Situação Tributária (CST) do IBS/CBS e suas classificações."""
    return AdnService.listar_cst(apenas_nfse=apenas_nfse)


@router.get("/cclasstrib")
def get_cclasstrib_table(
    cst: Optional[str] = Query(None, description="Filtrar pelo código CST (3 dígitos, ex: 000, 200)"),
    apenas_nfse: bool = Query(False, description="Retornar apenas códigos com IndNfse=True ou presentes no Anexo VIII"),
    apenas_anexo_viii: bool = Query(False, description="Retornar apenas os 27 códigos do Anexo VIII da NFS-e"),
    q: Optional[str] = Query(None, description="Busca textual por código ou descrição"),
):
    """Lista e filtra a tabela completa de 138 códigos cClassTrib da Reforma Tributária."""
    return AdnService.listar_cclasstrib(
        cst=cst,
        apenas_nfse=apenas_nfse,
        apenas_anexo_viii=apenas_anexo_viii,
        q=q,
    )


@router.get("/cclasstrib/{codigo}")
def get_cclasstrib_detail(codigo: str):
    """Retorna os metadados detalhados de um código cClassTrib de 6 dígitos."""
    item = AdnService.obter_cclasstrib(codigo)
    if not item:
        raise HTTPException(status_code=404, detail=f"cClassTrib '{codigo}' não encontrado.")
    return item


@router.get("/servicos")
def get_servicos_ctribnac(
    item_lc116: Optional[str] = Query(None, description="Filtrar pelo item da LC 116 (ex: 01.01, 17.14)"),
    q: Optional[str] = Query(None, description="Termo de busca por código ou descrição do serviço"),
    limite: int = Query(400, ge=1, le=1000),
):
    """Lista ou pesquisa os 338 códigos de tributação nacional (cTribNac - 6 dígitos) da LC 116/2003."""
    return AdnService.listar_servicos(item_lc116=item_lc116, q=q, limite=limite)


@router.get("/servicos/{c_trib_nac}")
def get_servico_ctribnac_detail(c_trib_nac: str):
    """Obtém detalhes de um código cTribNac (6 dígitos), regras de incidência do ISSQN e correlações do Anexo VIII."""
    srv = AdnService.obter_servico(c_trib_nac)
    if not srv:
        raise HTTPException(status_code=404, detail=f"Serviço cTribNac '{c_trib_nac}' não encontrado.")
    return srv


@router.get("/lc116")
def get_subitens_lc116():
    """Lista todos os subitens da LC 116/2003 com seus respectivos desdobramentos cTribNac."""
    return AdnService.listar_lc116()


@router.get("/correlacoes")
def get_correlacoes_anexo_viii(
    q: Optional[str] = Query(None, description="Busca textual por NBS, descrição, LC 116 ou cClassTrib"),
    item_lc116: Optional[str] = Query(None, description="Filtrar pelo subitem da LC 116 (ex: 01.01)"),
    c_trib_nac: Optional[str] = Query(None, description="Filtrar pelo código cTribNac (6 dígitos, ex: 010101)"),
    c_nbs: Optional[str] = Query(None, description="Filtrar pelo código NBS (ex: 115022000)"),
    c_class_trib: Optional[str] = Query(None, description="Filtrar pelo código cClassTrib (ex: 000001, 200029)"),
    indop: Optional[str] = Query(None, description="Filtrar pelo código cIndOp (ex: 100301)"),
    limite: int = Query(100, ge=1, le=2000),
):
    """Busca na matriz oficial do Anexo VIII (1.739 correlações entre LC 116, NBS, INDOP e cClassTrib)."""
    return AdnService.buscar_correlacoes(
        q=q,
        item_lc116=item_lc116,
        c_trib_nac=c_trib_nac,
        c_nbs=c_nbs,
        c_class_trib=c_class_trib,
        indop=indop,
        limite=limite,
    )


@router.get("/indop")
def get_indop_table():
    """Lista a tabela de Códigos Indicadores de Operação (cIndOp) e regras de local de incidência IBS/CBS."""
    return AdnService.listar_indop()


@router.get("/favoritos")
def get_favoritos():
    """Retorna os presets favoritos de serviços para preenchimento rápido de DPS."""
    return AdnService.listar_favoritos()

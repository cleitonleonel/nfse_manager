"""Router de Catálogos Tributários e de Serviços da NFS-e Nacional (ADN / Sefin Nacional v1.01).

Delega as consultas à camada `AdnService` (que consome o pacote `pynfse.adn`).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.routers.auth import get_current_user, require_admin_user
from app.database import get_db
from app.models import User
from app.services.adn_service import AdnService
from app.services.audit_service import AuditService, get_client_ip

router = APIRouter(prefix="/api/catalogs", tags=["catalogs"], dependencies=[Depends(get_current_user)])


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
    apenas_anexo_viii: bool = Query(False, description="Retornar apenas os códigos presentes no Anexo VIII da NFS-e"),
    q: Optional[str] = Query(None, description="Busca textual por código ou descrição"),
    data_competencia: Optional[str] = Query(None, description="Filtrar por vigência na data AAAA-MM-DD"),
):
    """Lista e filtra a tabela oficial de códigos cClassTrib da Reforma Tributária."""
    return AdnService.listar_cclasstrib(
        cst=cst,
        apenas_nfse=apenas_nfse,
        apenas_anexo_viii=apenas_anexo_viii,
        q=q,
        data_competencia=data_competencia,
    )


@router.get("/cclasstrib/{codigo}")
def get_cclasstrib_detail(
    codigo: str,
    data_competencia: Optional[str] = Query(None, description="Validar vigência na data AAAA-MM-DD"),
):
    """Retorna os metadados detalhados de um código cClassTrib de 6 dígitos."""
    item = AdnService.obter_cclasstrib(codigo, data_competencia=data_competencia)
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
    """Busca na matriz oficial do Anexo VIII (correlações entre LC 116, NBS, INDOP e cClassTrib)."""
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
def get_indop_table(
    data_competencia: Optional[str] = Query(None, description="Filtrar por vigência na data AAAA-MM-DD"),
):
    """Lista a tabela de Códigos Indicadores de Operação (cIndOp) e regras de local de incidência IBS/CBS."""
    return AdnService.listar_indop(data_competencia=data_competencia)


@router.get("/atividades-simples")
def get_atividades_simples_nacional(
    apenas_nfse: bool = Query(False, description="Retornar apenas atividades habilitadas para NFS-e (tpDoc=91)"),
    data_competencia: Optional[str] = Query(None, description="Filtrar por vigência na data AAAA-MM-DD"),
):
    """Lista as atividades oficiais do Simples Nacional (cAtivSN — NT 2026.005 / base RFB V0073)."""
    return AdnService.listar_atividades_simples(
        apenas_nfse=apenas_nfse,
        data_competencia=data_competencia,
    )


@router.get("/simples-nacional")
def get_catalogo_simples_nacional():
    """Retorna o catálogo oficial completo do Simples Nacional (atividades, regimes, tpRBSN e transição)."""
    return AdnService.obter_catalogo_simples_nacional()


@router.get("/nbs")
def get_nbs_table(
    q: Optional[str] = Query(None, description="Busca textual por código NBS ou descrição"),
    item_lc116: Optional[str] = Query(None, description="Filtrar pelo subitem da LC 116 (ex: 01.01)"),
    apenas_anexo_viii: bool = Query(False, description="Retornar apenas NBS listadas no Anexo VIII"),
    limite: int = Query(1000, ge=1, le=2000),
):
    """Lista e pesquisa a tabela oficial completa de códigos NBS (920+ itens)."""
    return AdnService.listar_nbs(
        q=q,
        item_lc116=item_lc116,
        apenas_anexo_viii=apenas_anexo_viii,
        limite=limite,
    )


@router.get("/nbs/{c_nbs}/combinacoes")
def get_nbs_combinacoes(
    c_nbs: str,
    c_trib_nac: Optional[str] = Query(None, description="Filtrar adicionalmente pelo cTribNac (6 dígitos)"),
):
    """Retorna as opções compatíveis de cClassTrib e cIndOp para a NBS informada."""
    return AdnService.listar_combinacoes_por_nbs(c_nbs=c_nbs, c_trib_nac=c_trib_nac)


@router.get("/favoritos")
def get_favoritos():
    """Retorna os presets favoritos de serviços para preenchimento rápido de DPS."""
    return AdnService.listar_favoritos()


@router.get("/status")
def get_catalogs_status(
    check_remote: bool = Query(
        False,
        description="Consultar também a API da Receita Federal e gov.br/nfse para verificar atualizações",
    ),
):
    """Retorna metadados, versão oficial vigente (RFB / Anexos VII e VIII), diretório ativo e totais dos catálogos."""
    return AdnService.obter_status_catalogos(check_remote=check_remote)


@router.post("/sync")
def sync_catalogs_from_official_sources(
    request: Request,
    force: bool = Query(False, description="Forçar gravação mesmo se a versão oficial já estiver atual"),
    validar_calculadora: bool = Query(
        False,
        description="Consultar combinações aceitas na calculadora piloto RFB por NBS (mais lento)",
    ),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
):
    """Sincroniza os catálogos fiscais no cache compartilhado a partir das fontes oficiais RFB e gov.br/nfse (somente admin)."""
    res = AdnService.sincronizar_catalogos_oficiais(
        force=force,
        validar_calculadora=validar_calculadora,
    )
    AuditService.record(
        db,
        action="system.catalogs_sync",
        entity_type="catalog",
        current_user=_admin,
        summary="Sincronização dos catálogos fiscais oficiais (RFB / gov.br/nfse) executada.",
        details={
            "force": force,
            "validar_calculadora": validar_calculadora,
            "atualizado": res.get("atualizado") if isinstance(res, dict) else None,
            "versao_db": ((res.get("metadados") or {}).get("versao_db") if isinstance(res, dict) else None),
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=True,
    )
    return res

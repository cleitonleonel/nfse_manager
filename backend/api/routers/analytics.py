"""Router de Analytics - Estatísticas e gráficos de NFSe."""

import logging
import datetime
from typing import Optional, cast
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Client, Note
from backend.schemas import DashboardStats, ChartData, ChartPoint
from core.xml_parser import extrair_dados_nfse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter estatísticas gerais do dashboard."""
    base = db.query(Note)
    if client_id:
        base = base.filter(Note.client_id == client_id)

    total_notas = base.count()
    total_emitidas = base.filter(Note.tipo == "emitidas").count()
    total_recebidas = base.filter(Note.tipo == "recebidas").count()
    total_clientes = db.query(Client).count()
    downloads_pendentes = base.filter(Note.xml_path.is_(None)).count()

    v_base = db.query(func.coalesce(func.sum(Note.valor), 0.0))
    if client_id:
        v_base = v_base.filter(Note.client_id == client_id)

    valor_total = v_base.scalar() or 0.0
    valor_emitidas = (
            v_base.filter(Note.tipo == "emitidas").scalar() or 0.0
    )
    valor_recebidas = (
            v_base.filter(Note.tipo == "recebidas").scalar() or 0.0
    )

    return {
        "total_notas": total_notas,
        "total_emitidas": total_emitidas,
        "total_recebidas": total_recebidas,
        "total_clientes": total_clientes,
        "downloads_pendentes": downloads_pendentes,
        "valor_total": valor_total,
        "valor_emitidas": valor_emitidas,
        "valor_recebidas": valor_recebidas
    }


@router.get("/chart", response_model=ChartData)
def get_chart_data(period: str = "30d", client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter dados de gráfico por período."""
    days = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    base_filter = [Note.data_emissao >= date_limit]
    if client_id:
        base_filter.append(Note.client_id == client_id)

    results = db.query(
        func.date(Note.data_emissao).label('dia'),
        func.count(Note.id).filter(Note.tipo == "emitidas").label('emitidas'),
        func.count(Note.id).filter(Note.tipo == "recebidas").label('recebidas'),
        func.coalesce(func.sum(Note.valor), 0.0).label('valor')
    ).filter(*base_filter).group_by('dia').order_by('dia').all()

    points = [
        ChartPoint(
            label=str(r.dia),
            emitidas=r.emitidas or 0,
            recebidas=r.recebidas or 0,
            valor=float(r.valor or 0.0)
        )
        for r in results
    ]

    return ChartData(points=points)


@router.post("/enrich-xml")
def enrich_from_xml(db: Session = Depends(get_db)):
    """Enriquecer notas com dados do XML local."""
    notas = db.query(Note).filter(Note.xml_path.is_not(None)).all()

    updated = 0
    errors = 0
    for note in notas:
        try:
            xml_path = getattr(note, "xml_path", None)
            if not xml_path:
                continue

            dados = extrair_dados_nfse(cast(str, xml_path))
            changed = False
            valor_atual = getattr(note, "valor", None)
            numero_atual = getattr(note, "numero", None)

            if dados.get("valor", 0) > 0 and (valor_atual is None or valor_atual == 0):
                note.valor = dados["valor"]
                changed = True

            if dados.get("numero") and (not numero_atual or numero_atual == note.chave):
                note.numero = dados["numero"]
                changed = True

            if dados.get("data_emissao"):
                note.data_emissao = dados["data_emissao"]
                changed = True

            if changed:
                db.add(note)
                updated += 1
        except Exception as e:
            logger.warning(f"Erro ao enriquecer nota {note.id}: {e}")
            errors += 1

    db.commit()
    return {
        "message": f"{updated} notas enriquecidas com sucesso.",
        "updated": updated,
        "errors": errors
    }


@router.get("/ranking")
def get_ranking(period: str = "30d", db: Session = Depends(get_db)):
    """Obter ranking de clientes por período."""
    days = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    results = db.query(
        Note.client_id,
        Client.razao_social,
        func.sum(Note.valor).filter(Note.tipo == "emitidas").label('emitidas'),
        func.sum(Note.valor).filter(Note.tipo == "recebidas").label('recebidas')
    ).join(Client).filter(Note.data_emissao >= date_limit).group_by(Note.client_id, Client.razao_social).all()

    top_emitidas = sorted(
        [{"client_id": r.client_id, "razao_social": r.razao_social, "valor": float(r.emitidas or 0)}
         for r in results if (r.emitidas or 0) > 0],
        key=lambda x: x["valor"],
        reverse=True
    )[:5]

    top_recebidas = sorted(
        [{"client_id": r.client_id, "razao_social": r.razao_social, "valor": float(r.recebidas or 0)}
         for r in results if (r.recebidas or 0) > 0],
        key=lambda x: x["valor"],
        reverse=True
    )[:5]

    return {"top_emitidas": top_emitidas, "top_recebidas": top_recebidas}

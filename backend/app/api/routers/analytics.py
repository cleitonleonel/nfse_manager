"""Router de Analytics - Estatísticas e gráficos de NFSe."""

import logging
import datetime
from typing import Optional, cast
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, Invoice
from app.schemas import DashboardStats, ChartData, ChartPoint
from pynfse.xml_parser import extrair_dados_nfse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter estatísticas gerais do dashboard."""
    base = db.query(Invoice)
    if client_id:
        base = base.filter(Invoice.client_id == client_id)

    total_notas = base.count()
    total_emitidas = base.filter(Invoice.tipo == "emitidas").count()
    total_recebidas = base.filter(Invoice.tipo == "recebidas").count()
    total_clientes = db.query(Client).count()
    downloads_pendentes = base.filter(Invoice.xml_path.is_(None)).count()

    v_base = db.query(func.coalesce(func.sum(Invoice.valor), 0.0))
    if client_id:
        v_base = v_base.filter(Invoice.client_id == client_id)

    valor_total = v_base.scalar() or 0.0
    valor_emitidas = v_base.filter(Invoice.tipo == "emitidas").scalar() or 0.0
    valor_recebidas = v_base.filter(Invoice.tipo == "recebidas").scalar() or 0.0

    return {
        "total_notas": total_notas,
        "total_emitidas": total_emitidas,
        "total_recebidas": total_recebidas,
        "total_clientes": total_clientes,
        "downloads_pendentes": downloads_pendentes,
        "valor_total": valor_total,
        "valor_emitidas": valor_emitidas,
        "valor_recebidas": valor_recebidas,
    }


@router.get("/chart", response_model=ChartData)
def get_chart_data(period: str = "30d", client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter dados de gráfico por período."""
    days = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    base_filter = [Invoice.data_emissao >= date_limit]
    if client_id:
        base_filter.append(Invoice.client_id == client_id)

    results = (
        db.query(
            func.date(Invoice.data_emissao).label("dia"),
            func.count(Invoice.id).filter(Invoice.tipo == "emitidas").label("emitidas"),
            func.count(Invoice.id).filter(Invoice.tipo == "recebidas").label("recebidas"),
            func.coalesce(func.sum(Invoice.valor), 0.0).label("valor"),
        )
        .filter(*base_filter)
        .group_by("dia")
        .order_by("dia")
        .all()
    )

    points = [
        ChartPoint(label=str(r.dia), emitidas=r.emitidas or 0, recebidas=r.recebidas or 0, valor=float(r.valor or 0.0))
        for r in results
    ]

    return ChartData(points=points)


@router.post("/enrich-xml")
def enrich_from_xml(db: Session = Depends(get_db)):
    """Enriquecer notas com dados do XML local."""
    invoices = db.query(Invoice).filter(Invoice.xml_path.is_not(None)).all()

    updated = 0
    errors = 0
    for invoice in invoices:
        try:
            xml_path = getattr(invoice, "xml_path", None)
            if not xml_path:
                continue

            dados = extrair_dados_nfse(cast(str, xml_path))
            changed = False
            valor_atual = getattr(invoice, "valor", None)
            numero_atual = getattr(invoice, "numero", None)

            if dados.get("valor", 0) > 0 and (valor_atual is None or valor_atual == 0):
                invoice.valor = dados["valor"]
                changed = True

            if dados.get("numero") and (not numero_atual or numero_atual == invoice.chave):
                invoice.numero = dados["numero"]
                changed = True

            if dados.get("data_emissao"):
                invoice.data_emissao = dados["data_emissao"]
                changed = True

            if changed:
                db.add(invoice)
                updated += 1
        except Exception as e:
            logger.warning(f"Erro ao enriquecer nota {invoice.id}: {e}")
            errors += 1

    db.commit()
    return {"message": f"{updated} notas enriquecidas com sucesso.", "updated": updated, "errors": errors}


@router.get("/ranking")
def get_ranking(period: str = "30d", db: Session = Depends(get_db)):
    """Obter ranking de clientes por período."""
    days = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    results = (
        db.query(
            Invoice.client_id,
            Client.razao_social,
            func.sum(Invoice.valor).filter(Invoice.tipo == "emitidas").label("emitidas"),
            func.sum(Invoice.valor).filter(Invoice.tipo == "recebidas").label("recebidas"),
        )
        .join(Client)
        .filter(Invoice.data_emissao >= date_limit)
        .group_by(Invoice.client_id, Client.razao_social)
        .all()
    )

    top_emitidas = sorted(
        [
            {"client_id": r.client_id, "razao_social": r.razao_social, "valor": float(r.emitidas or 0)}
            for r in results
            if (r.emitidas or 0) > 0
        ],
        key=lambda x: x["valor"],
        reverse=True,
    )[:5]

    top_recebidas = sorted(
        [
            {"client_id": r.client_id, "razao_social": r.razao_social, "valor": float(r.recebidas or 0)}
            for r in results
            if (r.recebidas or 0) > 0
        ],
        key=lambda x: x["valor"],
        reverse=True,
    )[:5]

    return {"top_emitidas": top_emitidas, "top_recebidas": top_recebidas}

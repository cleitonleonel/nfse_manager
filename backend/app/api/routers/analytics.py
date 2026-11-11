"""Router de Analytics - Estatísticas e gráficos de NFSe."""

import logging
import datetime
from typing import Optional, cast
from fastapi import APIRouter, Depends
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.constants import DEFAULT_PERIOD, PERIOD_DAYS_MAP
from app.database import get_db
from app.models import Client, Invoice
from app.schemas import DashboardStats, ChartData, ChartPoint
from app.services.html_xml_service import enriquecer_nota_com_xml

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def filtro_nota_valida_para_calculo():
    """Retorna expressão SQL para filtrar notas ativas/faturáveis (exclui canceladas e substituídas/substitutas)."""
    status_lower = func.lower(func.coalesce(Invoice.status, ""))
    return and_(
        status_lower.notlike("%cancelad%"),
        status_lower.notlike("%substitu%"),
    )


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter estatísticas gerais do dashboard (exclui notas canceladas e substituídas dos totais financeiros)."""
    base = db.query(Invoice)
    if client_id:
        base = base.filter(Invoice.client_id == client_id)

    total_notas = base.count()
    status_valido = filtro_nota_valida_para_calculo()

    total_emitidas = base.filter(Invoice.tipo == "emitidas", status_valido).count()
    total_recebidas = base.filter(Invoice.tipo == "recebidas", status_valido).count()
    total_clientes = db.query(Client).count()
    downloads_pendentes = base.filter(Invoice.xml_path.is_(None)).count()

    v_base = db.query(func.coalesce(func.sum(Invoice.valor), 0.0))
    if client_id:
        v_base = v_base.filter(Invoice.client_id == client_id)

    valor_total = v_base.filter(status_valido).scalar() or 0.0
    valor_emitidas = v_base.filter(Invoice.tipo == "emitidas", status_valido).scalar() or 0.0
    valor_recebidas = v_base.filter(Invoice.tipo == "recebidas", status_valido).scalar() or 0.0

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
def get_chart_data(period: str = DEFAULT_PERIOD, client_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Obter dados de gráfico por período (desconsidera notas canceladas e substituídas no faturamento)."""
    days = PERIOD_DAYS_MAP.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    base_filter = [Invoice.data_emissao >= date_limit]
    if client_id:
        base_filter.append(Invoice.client_id == client_id)

    status_valido = filtro_nota_valida_para_calculo()

    results = (
        db.query(
            func.date(Invoice.data_emissao).label("dia"),
            func.count(Invoice.id).filter(Invoice.tipo == "emitidas", status_valido).label("emitidas"),
            func.count(Invoice.id).filter(Invoice.tipo == "recebidas", status_valido).label("recebidas"),
            func.coalesce(func.sum(Invoice.valor).filter(Invoice.tipo == "emitidas", status_valido), 0.0).label("valor"),
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

            valor_antigo = getattr(invoice, "valor", None)
            numero_antigo = getattr(invoice, "numero", None)
            data_antiga = getattr(invoice, "data_emissao", None)

            enriquecer_nota_com_xml(
                invoice,
                xml_path=cast(str, xml_path),
                atualizar_data=True,
                apenas_se_vazio=True,
            )

            changed = (
                getattr(invoice, "valor", None) != valor_antigo
                or getattr(invoice, "numero", None) != numero_antigo
                or getattr(invoice, "data_emissao", None) != data_antiga
            )
            if changed:
                db.add(invoice)
                updated += 1
        except Exception as e:
            logger.warning(f"Erro ao enriquecer nota {invoice.id}: {e}")
            errors += 1

    db.commit()
    return {"message": f"{updated} notas enriquecidas com sucesso.", "updated": updated, "errors": errors}


@router.get("/ranking")
def get_ranking(period: str = DEFAULT_PERIOD, db: Session = Depends(get_db)):
    """Obter ranking de clientes por período (desconsidera notas canceladas e substituídas)."""
    days = PERIOD_DAYS_MAP.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    status_valido = filtro_nota_valida_para_calculo()

    results = (
        db.query(
            Invoice.client_id,
            Client.razao_social,
            func.sum(Invoice.valor).filter(Invoice.tipo == "emitidas", status_valido).label("emitidas"),
            func.sum(Invoice.valor).filter(Invoice.tipo == "recebidas", status_valido).label("recebidas"),
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

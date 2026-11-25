"""Router de consulta da Trilha de Auditoria (`/api/audit-logs`, restrito a administradores)."""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.routers.auth import require_admin_user
from app.database import get_db
from app.models import AuditLog, Client
from app.schemas import AuditLogItemResponse, AuditLogListResponse

router = APIRouter(
    prefix="/api/audit-logs",
    tags=["audit"],
    dependencies=[Depends(require_admin_user)],
)


def _parse_date_bound(raw: str, *, end_of_day: bool) -> datetime.datetime:
    text_val = (raw or "").strip()
    if not text_val:
        raise ValueError("Data vazia")

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        if len(text_val) == 10:
            try:
                parsed_date = datetime.datetime.strptime(text_val, fmt).date()
                if end_of_day:
                    return datetime.datetime.combine(parsed_date, datetime.time(23, 59, 59, 999999))
                return datetime.datetime.combine(parsed_date, datetime.time(0, 0, 0))
            except ValueError:
                pass

    try:
        iso_candidate = text_val.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.UTC).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Formato de data inválido. Utilize AAAA-MM-DD ou DD/MM/AAAA.",
        ) from exc


def _parse_details(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except Exception:
        return {"raw": raw}


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    q: Optional[str] = Query(None, description="Busca textual em resumo, ator, ação, entidade ou detalhes"),
    action: Optional[str] = Query(None, description="Filtrar por ação exata"),
    entity_type: Optional[str] = Query(None, description="Filtrar por tipo de entidade"),
    actor: Optional[str] = Query(None, description="Filtrar por username do ator"),
    client_id: Optional[int] = Query(None, description="Filtrar por empresa vinculada"),
    status: Optional[str] = Query(None, description="Filtrar por status (success, error, denied)"),
    date_from: Optional[str] = Query(None, description="Data inicial (AAAA-MM-DD ou DD/MM/AAAA)"),
    date_to: Optional[str] = Query(None, description="Data final (AAAA-MM-DD ou DD/MM/AAAA)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lista os registros da trilha de auditoria com paginação e filtros (somente admin)."""
    query = db.query(AuditLog)

    if q and q.strip():
        termo = f"%{q.strip()}%"
        query = query.filter(
            or_(
                AuditLog.summary.ilike(termo),
                AuditLog.actor_username.ilike(termo),
                AuditLog.entity_id.ilike(termo),
                AuditLog.details_json.ilike(termo),
                AuditLog.action.ilike(termo),
                AuditLog.entity_type.ilike(termo),
            )
        )

    if action and action.strip():
        query = query.filter(AuditLog.action == action.strip())

    if entity_type and entity_type.strip():
        query = query.filter(AuditLog.entity_type == entity_type.strip())

    if actor and actor.strip():
        query = query.filter(AuditLog.actor_username.ilike(f"%{actor.strip()}%"))

    if client_id is not None:
        query = query.filter(AuditLog.client_id == client_id)

    if status and status.strip():
        query = query.filter(AuditLog.status == status.strip().lower())

    if date_from and date_from.strip():
        dt_from = _parse_date_bound(date_from, end_of_day=False)
        query = query.filter(AuditLog.created_at >= dt_from)

    if date_to and date_to.strip():
        dt_to = _parse_date_bound(date_to, end_of_day=True)
        query = query.filter(AuditLog.created_at <= dt_to)

    total = query.count()
    rows = (
        query.outerjoin(Client, AuditLog.client_id == Client.id)
        .add_columns(Client.razao_social, Client.cnpj)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        AuditLogItemResponse(
            id=log.id,
            created_at=log.created_at,
            actor_user_id=log.actor_user_id,
            actor_username=log.actor_username,
            actor_role=log.actor_role,
            client_id=log.client_id,
            client_name=client_name,
            client_cnpj=client_cnpj,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            summary=log.summary,
            details=_parse_details(log.details_json),
            status=log.status,
            ip_address=log.ip_address,
        )
        for log, client_name, client_cnpj in rows
    ]

    facets = {
        "actions": sorted(r[0] for r in db.query(AuditLog.action).distinct().all() if r[0]),
        "entity_types": sorted(r[0] for r in db.query(AuditLog.entity_type).distinct().all() if r[0]),
        "statuses": ["success", "error", "denied"],
    }

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        facets=facets,
    )

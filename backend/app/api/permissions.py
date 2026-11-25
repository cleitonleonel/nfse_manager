"""Helpers centralizados de autorização e isolamento multiempresa (`User` <-> `Client`)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from fastapi import HTTPException
from sqlalchemy import false as sa_false, or_
from sqlalchemy.orm import Session

from app.models import Client, Invoice, User, UserClient


def is_admin_user(user: Optional[User]) -> bool:
    """Retorna True se o usuário autenticado possui papel administrativo irrestrito."""
    return getattr(user, "role", None) == "admin"


def get_allowed_client_ids(db: Session, user: User) -> Optional[List[int]]:
    """
    Retorna `None` para administradores (acesso irrestrito a todas as empresas)
    ou a lista de IDs de `Client` vinculados ao usuário em `user_clients`.
    """
    if is_admin_user(user):
        return None
    user_id = getattr(user, "id", None)
    if not user_id:
        return []
    rows = db.query(UserClient.client_id).filter(UserClient.user_id == int(user_id)).all()
    return [int(r[0]) for r in rows if r[0] is not None]


def assert_client_access(
    db: Session,
    user: User,
    client_id: Optional[int],
    *,
    allow_none_for_admin: bool = True,
) -> Optional[List[int]]:
    """
    Valida se `user` tem acesso ao `client_id` informado.
    Retorna `allowed_ids` (`None` para admin, `list[int]` para operador).
    """
    allowed_ids = get_allowed_client_ids(db, user)
    if allowed_ids is None:
        if client_id is None and not allow_none_for_admin:
            raise HTTPException(status_code=400, detail="Informe o `client_id` da empresa prestadora.")
        return None

    if client_id is None:
        if not allow_none_for_admin:
            raise HTTPException(
                status_code=403,
                detail="Selecione uma empresa vinculada ao seu usuário para executar esta operação.",
            )
        return allowed_ids

    if int(client_id) not in allowed_ids:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado: você não tem permissão para acessar ou operar esta empresa.",
        )
    return allowed_ids


def assert_invoice_access(db: Session, user: User, invoice: Optional[Invoice]) -> Optional[List[int]]:
    """Valida se `user` tem permissão para acessar/operar a `Invoice` informada."""
    if invoice is None or is_admin_user(user):
        return None
    return assert_client_access(db, user, invoice.client_id, allow_none_for_admin=False)


def filter_query_by_allowed_clients(
    query,
    client_id_col,
    db: Session,
    user: User,
    client_id: Optional[int] = None,
    *,
    include_global_none_for_admin: bool = False,
):
    """
    Aplica filtro de `client_id` e restrição por usuário em queries SQLAlchemy.
    Quando `client_id` é omitido por um não-admin, restringe aos vínculos em `user_clients`.
    """
    if client_id is not None:
        allowed_ids = assert_client_access(db, user, client_id, allow_none_for_admin=True)
        if include_global_none_for_admin and allowed_ids is None:
            return query.filter(or_(client_id_col == int(client_id), client_id_col.is_(None)))
        return query.filter(client_id_col == int(client_id))

    allowed_ids = get_allowed_client_ids(db, user)
    if allowed_ids is None:
        return query
    if not allowed_ids:
        return query.filter(sa_false())
    return query.filter(client_id_col.in_(allowed_ids))


def grant_client_access(
    db: Session,
    user_id: int,
    client_id: int,
    access_level: str = "manager",
) -> UserClient:
    """Garante o vínculo `UserClient` entre um usuário e uma empresa sem duplicar registros."""
    existing = (
        db.query(UserClient)
        .filter(UserClient.user_id == int(user_id), UserClient.client_id == int(client_id))
        .first()
    )
    if existing:
        if access_level == "manager" and existing.access_level != "manager":
            existing.access_level = "manager"
            db.add(existing)
        return existing

    link = UserClient(
        user_id=int(user_id),
        client_id=int(client_id),
        access_level=access_level,
    )
    db.add(link)
    return link


def get_client_access_level(db: Session, user: User, client_id: Optional[int]) -> Optional[str]:
    """Retorna `'admin'`, `'manager'`, `'operator'` ou `None` se o usuário não tiver vínculo."""
    if is_admin_user(user):
        return "admin"
    user_id = getattr(user, "id", None)
    if not user_id or client_id is None:
        return None
    link = (
        db.query(UserClient)
        .filter(UserClient.user_id == int(user_id), UserClient.client_id == int(client_id))
        .first()
    )
    return link.access_level if link else None


def assert_client_manager_or_admin(
    db: Session,
    user: User,
    client_id: Optional[int],
    *,
    detail: str = "Apenas administradores ou o gestor da empresa podem executar esta operação.",
) -> None:
    """Exige papel global `admin` ou vínculo `UserClient.access_level == 'manager'` na empresa."""
    assert_client_access(db, user, client_id, allow_none_for_admin=False)
    if is_admin_user(user):
        return
    if get_client_access_level(db, user, client_id) != "manager":
        raise HTTPException(status_code=403, detail=detail)


def sync_user_clients(
    db: Session,
    user_id: int,
    client_ids: Optional[Iterable[int]] = None,
    access_level: str = "operator",
    client_links: Optional[Iterable[object]] = None,
) -> List[int]:
    """Substitui os vínculos `UserClient` de um usuário por `client_links` ou `client_ids`."""
    explicit_levels: Optional[dict[int, str]] = None
    if client_links is not None:
        explicit_levels = {}
        for item in client_links:
            raw_cid = item["client_id"] if isinstance(item, dict) else getattr(item, "client_id", None)
            raw_lvl = (
                item.get("access_level", "operator")
                if isinstance(item, dict)
                else getattr(item, "access_level", "operator")
            )
            if raw_cid is None:
                continue
            cid = int(raw_cid)
            lvl = str(raw_lvl or "operator").strip().lower()
            if lvl not in {"manager", "operator"}:
                raise HTTPException(status_code=400, detail=f"Nível de acesso inválido: '{lvl}'.")
            if cid in explicit_levels and explicit_levels[cid] != lvl:
                raise HTTPException(status_code=400, detail=f"Empresa {cid} informada com níveis conflitantes.")
            explicit_levels[cid] = lvl
        unique_ids = sorted(explicit_levels.keys())
    else:
        unique_ids = sorted({int(cid) for cid in (client_ids or []) if cid is not None})

    if unique_ids:
        existing_rows = db.query(Client.id).filter(Client.id.in_(unique_ids)).all()
        found_ids = {int(r[0]) for r in existing_rows}
        missing = [cid for cid in unique_ids if cid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Empresa(s) informada(s) não encontrada(s): {missing}",
            )

    existing_links = db.query(UserClient).filter(UserClient.user_id == int(user_id)).all()
    existing_by_cid = {int(link.client_id): link for link in existing_links}
    target_set = set(unique_ids)

    for cid, link in existing_by_cid.items():
        if cid not in target_set:
            db.delete(link)

    for cid in unique_ids:
        if cid in existing_by_cid:
            if explicit_levels is not None:
                existing_by_cid[cid].access_level = explicit_levels[cid]
        else:
            lvl = explicit_levels[cid] if explicit_levels is not None else access_level
            db.add(UserClient(user_id=int(user_id), client_id=cid, access_level=lvl))

    db.flush()
    return unique_ids

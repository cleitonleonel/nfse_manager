"""Router de Autenticação JWT e Gestão de Operadores (`/api/auth`).

O primeiro administrador é criado via CLI estilo Django:
    python manage.py create_admin
"""

from __future__ import annotations

import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.permissions import sync_user_clients
from app.core.config import allow_public_register
from app.core.security import create_access_token, hash_password, verify_access_token, verify_password
from app.database import get_db
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserRegister,
    UserResponse,
    UserUpdate,
)
from app.services.audit_service import AuditService, get_client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Valida o cabeçalho `Authorization: Bearer <token>` e retorna o usuário autenticado."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token de autenticação não informado.")

    token = authorization.split(" ", 1)[1].strip()
    payload = verify_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado.")

    user = (
        db.query(User)
        .options(selectinload(User.client_links))
        .filter(User.username == str(payload["sub"]))
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário inativo ou não encontrado.")
    return user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return current_user


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Indica se já existem operadores cadastrados no banco de dados e se o auto-cadastro está aberto."""
    total_users = db.query(User).count()
    return {
        "has_users": total_users > 0,
        "total_users": total_users,
        "allow_self_register": allow_public_register(),
    }


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Autentica um operador por username ou e-mail e retorna um token JWT (Bearer)."""
    ident = (payload.username or "").strip()
    if not ident or not payload.password:
        raise HTTPException(status_code=400, detail="Informe usuário e senha.")

    ip_addr = get_client_ip(request)
    user = (
        db.query(User)
        .options(selectinload(User.client_links))
        .filter(or_(User.username == ident, User.email == ident.lower()))
        .first()
    )
    if not user or not verify_password(payload.password, user.password_hash):
        AuditService.record(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            actor_username=user.username if user else ident,
            actor_role=user.role if user else None,
            summary=f"Falha de login para '{ident}'.",
            details={"ident": ident, "reason": "invalid_credentials"},
            status="denied",
            ip_address=ip_addr,
            commit=True,
        )
        raise HTTPException(status_code=401, detail="Credenciais inválidas.")

    if not user.is_active:
        AuditService.record(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            current_user=user,
            summary=f"Tentativa de login com usuário desativado '{user.username}'.",
            details={"ident": ident, "reason": "inactive_user"},
            status="denied",
            ip_address=ip_addr,
            commit=True,
        )
        raise HTTPException(status_code=403, detail="Usuário desativado.")

    user.last_login_at = datetime.datetime.now(datetime.UTC)
    db.add(user)
    AuditService.record(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        current_user=user,
        summary=f"Login realizado por '{user.username}'.",
        details={"role": user.role},
        status="success",
        ip_address=ip_addr,
        commit=False,
    )
    db.commit()
    user = db.query(User).options(selectinload(User.client_links)).filter(User.id == user.id).first()

    token = create_access_token({"sub": user.username, "uid": user.id, "role": user.role}, expires_minutes=1440)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=86400,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse)
def register_user(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    """Cadastra um novo operador e já retorna um token JWT autenticado.

    O primeiro operador cadastrado no sistema recebe automaticamente o papel `admin`;
    os demais são criados como `operador` (respeitando `NFSE_ALLOW_PUBLIC_REGISTER`).
    """
    total_users = db.query(User).count()
    if total_users > 0 and not allow_public_register():
        raise HTTPException(status_code=403, detail="Auto-cadastro público desabilitado pelo administrador.")

    uname = (payload.username or "").strip()
    if len(uname) < 3:
        raise HTTPException(status_code=400, detail="O usuário deve ter pelo menos 3 caracteres.")
    if " " in uname:
        raise HTTPException(status_code=400, detail="O nome de usuário não pode conter espaços.")
    if not payload.password or len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 4 caracteres.")

    if db.query(User).filter(User.username == uname).first():
        raise HTTPException(status_code=400, detail=f"Usuário '{uname}' já está cadastrado.")

    email_clean = (payload.email or "").strip().lower() or None
    if email_clean and db.query(User).filter(User.email == email_clean).first():
        raise HTTPException(status_code=400, detail=f"E-mail '{email_clean}' já está em uso.")

    is_first_user = total_users == 0
    role = "admin" if is_first_user else "operador"

    new_user = User(
        username=uname,
        email=email_clean,
        full_name=(payload.full_name or "").strip() or None,
        password_hash=hash_password(payload.password),
        role=role,
        is_active=1,
        last_login_at=datetime.datetime.now(datetime.UTC),
    )
    db.add(new_user)
    db.flush()
    AuditService.record(
        db,
        action="auth.register",
        entity_type="user",
        entity_id=new_user.id,
        current_user=new_user,
        summary=f"Auto-cadastro realizado para '{new_user.username}' ({role}).",
        details={"role": role, "is_first_user": is_first_user},
        status="success",
        ip_address=get_client_ip(request),
        commit=False,
    )
    db.commit()
    new_user = db.query(User).options(selectinload(User.client_links)).filter(User.id == new_user.id).first()

    token = create_access_token({"sub": new_user.username, "uid": new_user.id, "role": new_user.role}, expires_minutes=1440)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=86400,
        user=UserResponse.model_validate(new_user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retorna os dados do operador autenticado."""
    return current_user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Altera a senha do próprio operador autenticado."""
    ip_addr = get_client_ip(request)
    if not verify_password(payload.current_password, current_user.password_hash):
        AuditService.record(
            db,
            action="auth.change_password",
            entity_type="user",
            entity_id=current_user.id,
            current_user=current_user,
            summary=f"Tentativa recusada de alteração de senha para '{current_user.username}'.",
            details={"reason": "invalid_current_password"},
            status="denied",
            ip_address=ip_addr,
            commit=True,
        )
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    if not payload.new_password or len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="A nova senha deve ter pelo menos 4 caracteres.")

    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    AuditService.record(
        db,
        action="auth.change_password",
        entity_type="user",
        entity_id=current_user.id,
        current_user=current_user,
        summary=f"Senha alterada pelo usuário '{current_user.username}'.",
        details={"self_service": True},
        status="success",
        ip_address=ip_addr,
        commit=False,
    )
    db.commit()
    return {"message": "Senha alterada com sucesso."}


@router.get("/users", response_model=List[UserResponse])
def list_users(
    _admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Lista todos os operadores cadastrados (restrito a administradores)."""
    return db.query(User).options(selectinload(User.client_links)).order_by(User.id.asc()).all()


@router.post("/users", response_model=UserResponse)
def create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Cria um novo operador (restrito a administradores)."""
    uname = (payload.username or "").strip()
    if len(uname) < 3:
        raise HTTPException(status_code=400, detail="O usuário deve ter pelo menos 3 caracteres.")
    if " " in uname:
        raise HTTPException(status_code=400, detail="O nome de usuário não pode conter espaços.")
    if db.query(User).filter(User.username == uname).first():
        raise HTTPException(status_code=400, detail=f"Username '{uname}' já está em uso.")

    email_clean = (payload.email or "").strip().lower() or None
    if email_clean and db.query(User).filter(User.email == email_clean).first():
        raise HTTPException(status_code=400, detail=f"E-mail '{email_clean}' já está em uso.")

    new_user = User(
        username=uname,
        email=email_clean,
        full_name=(payload.full_name or "").strip() or None,
        password_hash=hash_password(payload.password),
        role=payload.role or "operador",
        is_active=1,
    )
    db.add(new_user)
    db.flush()
    synced_ids: List[int] = []
    if new_user.role != "admin":
        if payload.client_links is not None:
            synced_ids = sync_user_clients(db, new_user.id, client_links=payload.client_links)
        elif payload.client_ids is not None:
            synced_ids = sync_user_clients(db, new_user.id, client_ids=payload.client_ids, access_level="operator")

    AuditService.record(
        db,
        action="auth.user_create",
        entity_type="user",
        entity_id=new_user.id,
        current_user=admin,
        summary=f"Usuário '{new_user.username}' ({new_user.role}) criado por '{admin.username}'.",
        details={
            "target_username": new_user.username,
            "role": new_user.role,
            "client_ids": synced_ids,
            "client_links": [
                {"client_id": link.client_id, "access_level": link.access_level}
                for link in (payload.client_links or [])
            ]
            if payload.client_links is not None
            else None,
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=False,
    )
    db.commit()
    return (
        db.query(User)
        .options(selectinload(User.client_links))
        .filter(User.id == new_user.id)
        .first()
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Atualiza dados, papel, status ativo ou senha de um operador (restrito a administradores)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if target.id == admin.id:
        if payload.is_active is not None and payload.is_active == 0:
            raise HTTPException(status_code=400, detail="Não é permitido desativar o próprio usuário autenticado.")
        if payload.role is not None and payload.role != "admin":
            raise HTTPException(status_code=400, detail="Não é permitido rebaixar o próprio perfil para operador.")

    will_deactivate = payload.is_active is not None and payload.is_active == 0
    will_demote = payload.role is not None and payload.role != "admin"
    if target.role == "admin" and target.is_active == 1 and (will_deactivate or will_demote):
        other_active_admins = (
            db.query(User)
            .filter(User.id != target.id, User.role == "admin", User.is_active == 1)
            .count()
        )
        if other_active_admins == 0:
            raise HTTPException(
                status_code=400,
                detail="Não é permitido desativar ou rebaixar o último administrador ativo do sistema.",
            )

    fields_set = payload.model_fields_set
    if "email" in fields_set:
        email_clean = (payload.email or "").strip().lower() or None
        if email_clean:
            conflict = db.query(User).filter(User.email == email_clean, User.id != target.id).first()
            if conflict:
                raise HTTPException(status_code=400, detail=f"E-mail '{email_clean}' já está em uso.")
        target.email = email_clean

    if "full_name" in fields_set:
        target.full_name = (payload.full_name or "").strip() or None

    if payload.role is not None:
        target.role = payload.role

    if payload.is_active is not None:
        target.is_active = int(payload.is_active)

    if payload.password is not None:
        target.password_hash = hash_password(payload.password)

    if target.role != "admin":
        if payload.client_links is not None:
            sync_user_clients(db, target.id, client_links=payload.client_links)
        elif payload.client_ids is not None:
            sync_user_clients(db, target.id, client_ids=payload.client_ids, access_level="operator")
    elif payload.role == "admin":
        sync_user_clients(db, target.id, [], access_level="operator")

    db.add(target)
    AuditService.record(
        db,
        action="auth.user_update",
        entity_type="user",
        entity_id=target.id,
        current_user=admin,
        summary=f"Usuário '{target.username}' atualizado por '{admin.username}'.",
        details={
            "target_username": target.username,
            "changed_fields": sorted(fields_set),
            "role": target.role,
            "is_active": target.is_active,
            "password_reset": payload.password is not None,
        },
        status="success",
        ip_address=get_client_ip(request),
        commit=False,
    )
    db.commit()
    return (
        db.query(User)
        .options(selectinload(User.client_links))
        .filter(User.id == target.id)
        .first()
    )


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Remove um operador (restrito a administradores)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Não é permitido excluir o próprio usuário autenticado.")

    target_id = target.id
    target_username = target.username
    target_role = target.role

    db.delete(target)
    AuditService.record(
        db,
        action="auth.user_delete",
        entity_type="user",
        entity_id=target_id,
        current_user=admin,
        summary=f"Usuário '{target_username}' removido por '{admin.username}'.",
        details={"target_username": target_username, "target_role": target_role},
        status="success",
        ip_address=get_client_ip(request),
        commit=False,
    )
    db.commit()
    return {"message": "Usuário removido com sucesso."}

"""Router de Autenticação JWT e Gestão de Operadores (`/api/auth`).

O primeiro administrador é criado via CLI estilo Django:
    python manage.py create_admin
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_access_token, verify_password
from app.database import get_db
from app.models import User
from app.schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserCreate, UserRegister, UserResponse

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

    user = db.query(User).filter(User.username == str(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário inativo ou não encontrado.")
    return user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return current_user


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Indica se já existem operadores cadastrados no banco de dados."""
    total_users = db.query(User).count()
    return {"has_users": total_users > 0, "total_users": total_users}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Autentica um operador por username ou e-mail e retorna um token JWT (Bearer)."""
    ident = (payload.username or "").strip()
    if not ident or not payload.password:
        raise HTTPException(status_code=400, detail="Informe usuário e senha.")

    user = db.query(User).filter(or_(User.username == ident, User.email == ident.lower())).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuário desativado.")

    token = create_access_token({"sub": user.username, "uid": user.id, "role": user.role}, expires_minutes=1440)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=86400,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse)
def register_user(payload: UserRegister, db: Session = Depends(get_db)):
    """Cadastra um novo operador e já retorna um token JWT autenticado.

    O primeiro operador cadastrado no sistema recebe automaticamente o papel `admin`;
    os demais são criados como `operador`.
    """
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

    is_first_user = db.query(User).count() == 0
    role = "admin" if is_first_user else "operador"

    new_user = User(
        username=uname,
        email=email_clean,
        full_name=(payload.full_name or "").strip() or None,
        password_hash=hash_password(payload.password),
        role=role,
        is_active=1,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Altera a senha do próprio operador autenticado."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    if not payload.new_password or len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="A nova senha deve ter pelo menos 4 caracteres.")

    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()
    return {"message": "Senha alterada com sucesso."}


@router.get("/users", response_model=List[UserResponse])
def list_users(
    _admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Lista todos os operadores cadastrados (restrito a administradores)."""
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/users", response_model=UserResponse)
def create_user(
    payload: UserCreate,
    _admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Cria um novo operador (restrito a administradores)."""
    uname = payload.username.strip()
    if not uname:
        raise HTTPException(status_code=400, detail="Username inválido.")
    if db.query(User).filter(User.username == uname).first():
        raise HTTPException(status_code=400, detail=f"Username '{uname}' já está em uso.")

    email_clean = (payload.email or "").strip().lower() or None
    if email_clean and db.query(User).filter(User.email == email_clean).first():
        raise HTTPException(status_code=400, detail=f"E-mail '{email_clean}' já está em uso.")

    new_user = User(
        username=uname,
        email=email_clean,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role or "operador",
        is_active=1,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Remove um operador (restrito a administradores)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Não é permitido excluir o próprio usuário autenticado.")

    db.delete(target)
    db.commit()
    return {"message": "Usuário removido com sucesso."}

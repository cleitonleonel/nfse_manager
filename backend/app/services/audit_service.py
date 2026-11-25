"""Serviço centralizado de Trilha de Auditoria (`AuditLog`) com sanitização de segredos."""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, Client, User

logger = logging.getLogger(__name__)

# Chaves sensíveis que devem ser sempre redigidas (comparação case-insensitive por substring/nome)
_SENSITIVE_SUBSTRINGS = (
    "password",
    "senha",
    "token",
    "secret",
    "pfx",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "chave_privada",
    "credential",
)
_SENSITIVE_EXACT_KEYS = {
    "cert",
    "certificate",
    "certificado",
    "auth",
    "jwt",
    "bearer",
    "pwd",
    "pass",
}
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n_-]+$")
_VALID_STATUSES = {"success", "error", "denied"}
_MAX_DETAILS_JSON_CHARS = 16384


def get_client_ip(request: Optional[Request]) -> Optional[str]:
    """Extrai o IP do cliente HTTP considerando proxies reversos (`X-Forwarded-For`, `X-Real-IP`)."""
    if request is None:
        return None
    try:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            first_ip = forwarded_for.split(",")[0].strip()
            if first_ip:
                return first_ip[:64]
        real_ip = request.headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()[:64]
        client = getattr(request, "client", None)
        host = getattr(client, "host", None)
        if host:
            return str(host).strip()[:64]
    except Exception:
        return None
    return None


def _is_sensitive_key(key: Any) -> bool:
    norm = str(key or "").strip().lower().replace("-", "_")
    if not norm:
        return False
    if norm in _SENSITIVE_EXACT_KEYS:
        return True
    return any(sub in norm for sub in _SENSITIVE_SUBSTRINGS)


def _sanitize_string(val: str) -> str:
    stripped = val.strip()
    if stripped.startswith("enc:") or stripped.startswith("pbkdf2_sha256$"):
        return "[REDACTED]"
    if ";base64," in stripped[:80].lower():
        return f"<base64_omitted:{len(val)}chars>"
    if stripped.startswith("<") and (
        len(stripped) > 300
        or "<SignatureValue" in stripped
        or "<X509Certificate" in stripped
        or "</NFSe>" in stripped
        or "</DPS>" in stripped
    ):
        return f"<xml_omitted:{len(val)}chars>"
    if len(stripped) > 256 and " " not in stripped and _BASE64_RE.match(stripped):
        return f"<base64_omitted:{len(val)}chars>"
    if len(val) > 1000:
        return val[:1000] + "...[truncated]"
    return val


def sanitize_details(value: Any, *, _depth: int = 0) -> Any:
    """Sanitiza recursivamente dicionários/listas removendo senhas, tokens, PFX, XML bruto e base64."""
    if _depth > 6:
        return "<max_depth_reached>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes:{len(value)}>"
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if _is_sensitive_key(key_str):
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = sanitize_details(v, _depth=_depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        clipped = [sanitize_details(item, _depth=_depth + 1) for item in items[:50]]
        if len(items) > 50:
            clipped.append(f"...(+{len(items) - 50} items)")
        return clipped
    return _sanitize_string(str(value))


def _serialize_details(details: Optional[Dict[str, Any]]) -> Optional[str]:
    if not details:
        return None
    cleaned = sanitize_details(details)
    serialized = json.dumps(cleaned, ensure_ascii=False, default=str)
    if len(serialized) > _MAX_DETAILS_JSON_CHARS:
        fallback = {"_truncated": True, "preview": serialized[:2000]}
        return json.dumps(fallback, ensure_ascii=False)
    return serialized


class AuditService:
    """Facade estática para gravação segura e isolada de eventos de auditoria."""

    @staticmethod
    def get_client_ip(request: Optional[Request]) -> Optional[str]:
        return get_client_ip(request)

    @classmethod
    def record(
        cls,
        db: Optional[Session],
        *,
        action: str,
        entity_type: str,
        summary: str,
        current_user: Any = None,
        actor_username: Optional[str] = None,
        actor_role: Optional[str] = None,
        client_id: Optional[int] = None,
        entity_id: Optional[str | int] = None,
        details: Optional[Dict[str, Any]] = None,
        status: str = "success",
        ip_address: Optional[str] = None,
        commit: bool = False,
    ) -> Optional[AuditLog]:
        """
        Registra um evento em `audit_logs` com sanitização de segredos e isolamento de falhas.
        Nunca propaga exceções para não interromper nem corromper a transação principal.
        """
        if db is None:
            return None

        resolved_status = status if status in _VALID_STATUSES else "success"
        resolved_username = actor_username or getattr(current_user, "username", None)
        resolved_role = actor_role or getattr(current_user, "role", None)
        raw_actor_id = getattr(current_user, "id", None) if current_user is not None else None
        resolved_entity_id = str(entity_id) if entity_id is not None else None
        details_json = _serialize_details(details)

        try:
            with db.begin_nested():
                # Garante integridade de FK inclusive em fixtures de teste (ex.: dummy_admin id=999999)
                # ou logs registrados após exclusão do registro alvo.
                valid_actor_id: Optional[int] = None
                if raw_actor_id is not None:
                    uid = int(raw_actor_id)
                    if db.query(User.id).filter(User.id == uid).scalar() is not None:
                        valid_actor_id = uid

                valid_client_id: Optional[int] = None
                if client_id is not None:
                    cid = int(client_id)
                    if db.query(Client.id).filter(Client.id == cid).scalar() is not None:
                        valid_client_id = cid
                    elif resolved_entity_id is None:
                        resolved_entity_id = str(cid)

                entry = AuditLog(
                    created_at=datetime.datetime.now(datetime.UTC),
                    actor_user_id=valid_actor_id,
                    actor_username=(str(resolved_username).strip()[:120] if resolved_username else None),
                    actor_role=(str(resolved_role).strip()[:40] if resolved_role else None),
                    client_id=valid_client_id,
                    action=str(action).strip()[:100],
                    entity_type=str(entity_type).strip()[:60],
                    entity_id=(resolved_entity_id[:120] if resolved_entity_id else None),
                    summary=str(summary or "").strip()[:500] or str(action).strip()[:500],
                    details_json=details_json,
                    status=resolved_status,
                    ip_address=(str(ip_address).strip()[:64] if ip_address else None),
                )
                db.add(entry)
                db.flush()

            if commit:
                db.commit()
            return entry
        except Exception as exc:
            logger.warning("Falha isolada ao registrar auditoria (action=%s): %s", action, exc)
            if commit:
                try:
                    db.rollback()
                except Exception:
                    pass
            return None

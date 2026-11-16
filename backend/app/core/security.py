"""Módulo de criptografia simétrica em repouso para credenciais sensíveis, hash PBKDF2 de senhas de usuários e tokens JWT."""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import load_dotenv_if_present

load_dotenv_if_present()

logger = logging.getLogger(__name__)

PREFIXO_ENCRIPTADO = "enc:"
PBKDF2_ITERATIONS = 260000


def _get_fernet_key() -> bytes:
    """Obtém ou deriva uma chave válida de 32 bytes em base64 URL-safe para o Fernet."""
    raw_key = (
        os.getenv("NFSE_ENCRYPTION_KEY")
        or os.getenv("SECRET_KEY")
        or "nfse_manager_secret_encryption_key_change_in_production"
    )
    derived_32bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived_32bytes)


def _get_fernet() -> Fernet:
    """Retorna a instância configurada do Fernet."""
    return Fernet(_get_fernet_key())


def is_encrypted(val: Optional[str]) -> bool:
    """Verifica se um valor textual já se encontra no formato criptografado."""
    if not val or not isinstance(val, str):
        return False
    return val.startswith(PREFIXO_ENCRIPTADO)


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """
    Criptografa um segredo (senha) para persistência segura em repouso no banco de dados.
    Se já estiver criptografado ou for nulo/vazio, retorna sem alterações.
    """
    if plaintext is None or plaintext == "":
        return plaintext

    if is_encrypted(plaintext):
        return plaintext

    try:
        fernet = _get_fernet()
        encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
        return f"{PREFIXO_ENCRIPTADO}{encrypted_bytes.decode('utf-8')}"
    except Exception as exc:
        logger.error(f"Erro ao criptografar credencial: {exc}")
        # Em caso de falha crítica na criptografia, propaga a exceção para não salvar inseguro
        raise RuntimeError(f"Falha de segurança ao criptografar credencial: {exc}") from exc


def decrypt_secret(ciphertext: Optional[str]) -> Optional[str]:
    """
    Decifra uma credencial armazenada no banco de dados para uso em memória.
    Se o valor for legado (não criptografado) ou nulo/vazio, retorna o valor original com segurança.
    """
    if ciphertext is None or ciphertext == "":
        return ciphertext

    if not is_encrypted(ciphertext):
        # Tenta decifrar caso seja um token Fernet puro sem o prefixo
        try:
            return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            # Dado legado em texto plano
            return ciphertext

    raw_token = ciphertext[len(PREFIXO_ENCRIPTADO) :]
    try:
        decrypted_bytes = _get_fernet().decrypt(raw_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken:
        logger.error("Token de credencial inválido ou chave de criptografia incorreta.")
        return ""
    except Exception as exc:
        logger.error(f"Erro ao decifrar credencial: {exc}")
        return ""


# ==============================================================================
# Hash de Senhas de Operadores (PBKDF2-HMAC-SHA256) e Autenticação JWT
# ==============================================================================


def hash_password(plain_password: str) -> str:
    """Gera hash seguro PBKDF2-HMAC-SHA256 com salt aleatório de 16 bytes."""
    if not plain_password:
        raise ValueError("A senha não pode ser vazia.")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    hash_b64 = base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def _pad_b64(val: str) -> str:
    return val + "=" * (-len(val) % 4)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verifica uma senha em texto plano contra um hash PBKDF2-HMAC-SHA256."""
    if not plain_password or not password_hash:
        return False
    try:
        parts = password_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = base64.urlsafe_b64decode(_pad_b64(parts[2]))
        expected_dk = base64.urlsafe_b64decode(_pad_b64(parts[3]))
        actual_dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(actual_dk, expected_dk)
    except Exception:
        return False


def _get_jwt_secret() -> bytes:
    raw = (
        os.getenv("JWT_SECRET_KEY")
        or os.getenv("NFSE_ENCRYPTION_KEY")
        or os.getenv("SECRET_KEY")
        or "nfse_manager_jwt_secret_key_change_in_production"
    )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def create_access_token(data: Dict[str, Any], expires_minutes: int = 1440) -> str:
    """Gera um token JWT (HS256) assinado."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = dict(data)
    payload["iat"] = now
    payload["exp"] = now + int(expires_minutes * 60)

    h_b64 = (
        base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    )
    p_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    )
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(_get_jwt_secret(), signing_input, hashlib.sha256).digest()
    s_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{h_b64}.{p_b64}.{s_b64}"


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida a assinatura e expiração de um token JWT (HS256), retornando o payload ou None."""
    if not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    h_b64, p_b64, s_b64 = parts
    try:
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(_get_jwt_secret(), signing_input, hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(_pad_b64(s_b64))
        if not secrets.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(_pad_b64(p_b64)).decode("utf-8"))
        exp = payload.get("exp")
        if exp is not None and int(time.time()) > int(exp):
            return None
        return payload
    except Exception:
        return None

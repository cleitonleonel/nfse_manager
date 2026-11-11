"""Módulo de criptografia simétrica em repouso para credenciais sensíveis (senhas do portal e de certificados)."""

import base64
import hashlib
import logging
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

PREFIXO_ENCRIPTADO = "enc:"


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

    raw_token = ciphertext[len(PREFIXO_ENCRIPTADO):]
    try:
        decrypted_bytes = _get_fernet().decrypt(raw_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken:
        logger.error("Token de credencial inválido ou chave de criptografia incorreta.")
        return ""
    except Exception as exc:
        logger.error(f"Erro ao decifrar credencial: {exc}")
        return ""

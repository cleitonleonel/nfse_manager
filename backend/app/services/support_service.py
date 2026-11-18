"""Serviço de encaminhamento de mensagens de Suporte/Feedback por E-mail (SMTP) e Telegram."""

from __future__ import annotations

import html
import logging
import os
from typing import Any, Dict, Optional

from fastapi import HTTPException
import httpx2 as httpx

from app.core.config import load_dotenv_if_present
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

DEFAULT_SUPPORT_EMAIL_TO = "cleiton.leonel@gmail.com"
DEFAULT_SUPPORT_TELEGRAM_TARGET = "@cleitonLC"


class SupportService:
    """Encaminha mensagens de suporte para E-mail e Telegram configurados no ambiente."""

    @staticmethod
    def _get_email_target() -> str:
        load_dotenv_if_present()
        return (
            os.getenv("SUPPORT_EMAIL_TO")
            or os.getenv("DEFAULT_SMTP_USER")
            or DEFAULT_SUPPORT_EMAIL_TO
        ).strip()

    @staticmethod
    def _get_telegram_config() -> tuple[str, str]:
        load_dotenv_if_present()
        token = (
            os.getenv("SUPPORT_TELEGRAM_BOT_TOKEN")
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or ""
        ).strip()
        chat_id = (
            os.getenv("SUPPORT_TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_CHAT_ID")
            or DEFAULT_SUPPORT_TELEGRAM_TARGET
        ).strip()
        return token, chat_id

    @staticmethod
    def _format_telegram_html(
        remetente_email: str,
        whatsapp: Optional[str],
        mensagem: str,
        operador: Optional[str] = None,
    ) -> str:
        op_line = f"\n<b>Operador:</b> {html.escape(operador)}" if operador else ""
        wpp_txt = html.escape(whatsapp or "-")
        return (
            "<b>📩 Suporte &amp; Feedback — NFSe Manager Pro</b>"
            f"{op_line}"
            f"\n<b>E-mail:</b> {html.escape(remetente_email)}"
            f"\n<b>WhatsApp:</b> {wpp_txt}"
            f"\n\n<b>Mensagem:</b>\n<pre>{html.escape(mensagem)}</pre>"
        )

    @classmethod
    async def enviar_telegram(
        cls,
        remetente_email: str,
        whatsapp: Optional[str],
        mensagem: str,
        operador: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Envia a mensagem diretamente via Telegram Bot API."""
        token, chat_id = cls._get_telegram_config()
        if not token:
            raise RuntimeError("Token do bot Telegram não configurado (SUPPORT_TELEGRAM_BOT_TOKEN).")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": cls._format_telegram_html(remetente_email, whatsapp, mensagem, operador=operador),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code >= 400:
            detail = resp.text
            try:
                data = resp.json()
                detail = data.get("description") or detail
            except Exception:
                pass
            raise RuntimeError(f"Telegram API HTTP {resp.status_code}: {detail}")

        return {"chat_id": chat_id}

    @classmethod
    async def enviar_mensagem(
        cls,
        remetente_email: str,
        whatsapp: Optional[str],
        mensagem: str,
        operador: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Despacha a mensagem pelos canais configurados (E-mail SMTP e Telegram)."""
        logger.info(
            "Support Message Received: operador=%r email=%r whatsapp=%r message=%r",
            operador,
            remetente_email,
            whatsapp,
            mensagem,
        )

        channels: Dict[str, Any] = {"email": "not_configured", "telegram": "not_configured"}
        errors: list[str] = []
        configured_count = 0
        sent_count = 0

        # 1. Canal E-mail (SMTP)
        smtp_cfg = EmailService.obter_config_smtp(None)
        if smtp_cfg:
            configured_count += 1
            email_to = cls._get_email_target()
            try:
                EmailService.enviar_mensagem_suporte(
                    destinatario=email_to,
                    remetente_email=remetente_email,
                    whatsapp=whatsapp,
                    mensagem=mensagem,
                    operador=operador,
                )
                channels["email"] = "sent"
                sent_count += 1
            except Exception as exc:
                err_msg = getattr(exc, "detail", None) or str(exc)
                logger.warning("Falha ao enviar mensagem de suporte por e-mail: %s", err_msg)
                channels["email"] = "failed"
                errors.append(f"E-mail: {err_msg}")

        # 2. Canal Telegram
        tg_token, _tg_chat = cls._get_telegram_config()
        if tg_token:
            configured_count += 1
            try:
                await cls.enviar_telegram(
                    remetente_email=remetente_email,
                    whatsapp=whatsapp,
                    mensagem=mensagem,
                    operador=operador,
                )
                channels["telegram"] = "sent"
                sent_count += 1
            except Exception as exc:
                logger.warning("Falha ao enviar mensagem de suporte via Telegram: %s", exc)
                channels["telegram"] = "failed"
                errors.append(f"Telegram: {exc}")

        if configured_count > 0 and sent_count == 0:
            raise HTTPException(
                status_code=502,
                detail=f"Não foi possível enviar a mensagem de suporte ({'; '.join(errors)}).",
            )

        return {
            "message": "Mensagem enviada com sucesso! Nossa equipe entrará em contato em breve.",
            "channels": channels,
        }

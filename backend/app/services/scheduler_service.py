"""Serviço de Worker Agendado em Background para Retransmissão Automática da Fila de Contingência.

Roda assincronamente no `lifespan` do FastAPI (configurável via `AUTO_RETRY_FILA_ENABLED`,
`AUTO_RETRY_FILA_INTERVAL_SECONDS` e `AUTO_RETRY_MAX_TENTATIVAS`), buscando notas com
`status == 'fila_contingencia'` e retransmitindo-as automaticamente quando a conexão/Sefin estabilizar.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import or_

from app.core.config import load_dotenv_if_present
from app.database import SessionLocal
from app.models import Client, Invoice
from app.schemas import ReenviarFilaRequest
from app.services.adn_service import AdnService
from app.services.email_service import EmailService

load_dotenv_if_present()

logger = logging.getLogger(__name__)


class SchedulerService:
    """Gerencia o worker periódico de reenvio da fila de contingência em background."""

    _task: Optional[asyncio.Task] = None
    _running: bool = False
    _last_run_at: Optional[str] = None
    _last_result: Dict[str, Any] = {
        "total_processadas": 0,
        "autorizadas": 0,
        "falhas": 0,
        "emails_enviados": 0,
    }

    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        enabled_raw = (os.getenv("AUTO_RETRY_FILA_ENABLED") or "1").strip().lower()
        enabled = enabled_raw not in ("0", "false", "no")
        interval = max(10, int(os.getenv("AUTO_RETRY_FILA_INTERVAL_SECONDS") or "300"))
        max_tentativas = max(1, int(os.getenv("AUTO_RETRY_MAX_TENTATIVAS") or "10"))
        return {
            "enabled": enabled,
            "interval_seconds": interval,
            "max_tentativas": max_tentativas,
        }

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        cfg = cls.get_config()
        return {
            "enabled": cfg["enabled"],
            "worker_running": cls._running,
            "interval_seconds": cfg["interval_seconds"],
            "max_tentativas": cfg["max_tentativas"],
            "ultima_execucao": cls._last_run_at,
            "ultimo_resultado": cls._last_result,
        }

    @classmethod
    async def run_fila_retry_cycle(cls) -> Dict[str, Any]:
        """Executa um ciclo completo de verificação e reenvio de notas na fila de contingência."""
        cfg = cls.get_config()
        max_tent = cfg["max_tentativas"]
        db = SessionLocal()
        try:
            pendentes = (
                db.query(Invoice)
                .filter(
                    Invoice.status == "fila_contingencia",
                    or_(Invoice.tentativas_envio.is_(None), Invoice.tentativas_envio < max_tent),
                )
                .order_by(Invoice.id.asc())
                .all()
            )
            if not pendentes:
                cls._last_run_at = datetime.datetime.now(datetime.UTC).isoformat()
                res_empty = {
                    "total_processadas": 0,
                    "autorizadas": 0,
                    "falhas": 0,
                    "emails_enviados": 0,
                }
                cls._last_result = res_empty
                return res_empty

            ids_elegiveis = [inv.id for inv in pendentes]
            res_reenvio = await AdnService.reenviar_fila_contingencia(
                db=db,
                req=ReenviarFilaRequest(invoice_ids=ids_elegiveis),
            )

            # Se alguma nota foi autorizada e o cliente possui enviar_email_automatico == 1, dispara o e-mail
            emails_enviados = 0
            for item in res_reenvio.get("resultados", []):
                if item.get("sucesso"):
                    inv_obj = db.query(Invoice).filter(Invoice.id == item["invoice_id"]).first()
                    if inv_obj and inv_obj.client_id and inv_obj.tomador_email:
                        cli_obj = db.query(Client).filter(Client.id == inv_obj.client_id).first()
                        if cli_obj and cli_obj.enviar_email_automatico and EmailService.obter_config_smtp(cli_obj):
                            try:
                                EmailService.enviar_nfse_por_email(
                                    client_db=cli_obj,
                                    invoice=inv_obj,
                                    destinatario=inv_obj.tomador_email,
                                )
                                emails_enviados += 1
                            except Exception as exc:
                                logger.warning(
                                    f"Aviso ao enviar e-mail automático pós-fila para nota {inv_obj.id}: {exc}"
                                )

            res_final = {
                "total_processadas": res_reenvio.get("total_processadas", 0),
                "autorizadas": res_reenvio.get("autorizadas", 0),
                "falhas": res_reenvio.get("falhas", 0),
                "emails_enviados": emails_enviados,
                "resultados": res_reenvio.get("resultados", []),
            }
            cls._last_run_at = datetime.datetime.now(datetime.UTC).isoformat()
            cls._last_result = res_final
            return res_final
        finally:
            db.close()

    @classmethod
    async def _worker_loop(cls) -> None:
        cls._running = True
        try:
            while cls._running:
                cfg = cls.get_config()
                if cfg["enabled"]:
                    try:
                        await cls.run_fila_retry_cycle()
                    except Exception as exc:
                        logger.warning(f"Erro no ciclo do worker de contingência: {exc}")
                await asyncio.sleep(cfg["interval_seconds"])
        except asyncio.CancelledError:
            pass
        finally:
            cls._running = False

    @classmethod
    def start(cls) -> None:
        cfg = cls.get_config()
        if not cfg["enabled"]:
            return
        if cls._task is None or cls._task.done():
            cls._task = asyncio.create_task(cls._worker_loop())

    @classmethod
    async def stop(cls) -> None:
        cls._running = False
        if cls._task and not cls._task.done():
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        cls._task = None

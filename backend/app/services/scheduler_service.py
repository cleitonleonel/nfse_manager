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
import socket
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import delete, or_, text, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_scheduler_mode, load_dotenv_if_present
from app.database import SessionLocal, engine
from app.models import Client, Invoice, SchedulerLock
from app.schemas import ReenviarFilaRequest
from app.services.adn_service import AdnService
from app.services.email_service import EmailService

load_dotenv_if_present()

logger = logging.getLogger(__name__)


class SchedulerService:
    """Gerencia o worker periódico de reenvio da fila de contingência em background."""

    _LOCK_NAME = "nfse_fila_retry_worker"
    _PG_LOCK_KEY = 785412369

    _task: Optional[asyncio.Task] = None
    _running: bool = False
    _is_leader: bool = False
    _owner_id: Optional[str] = None
    _last_run_at: Optional[str] = None
    _last_result: Dict[str, Any] = {
        "total_processadas": 0,
        "autorizadas": 0,
        "falhas": 0,
        "emails_enviados": 0,
    }

    @classmethod
    def _get_owner_id(cls) -> str:
        if not cls._owner_id:
            cls._owner_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        return cls._owner_id

    @classmethod
    def get_lock_backend(cls) -> str:
        dialect = engine.dialect.name
        return "pg_advisory_lock" if dialect == "postgresql" else "sqlite_lease"

    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        scheduler_mode = get_scheduler_mode()
        enabled_raw = (os.getenv("AUTO_RETRY_FILA_ENABLED") or "1").strip().lower()
        enabled = (scheduler_mode != "disabled") and (enabled_raw not in ("0", "false", "no"))
        interval = max(10, int(os.getenv("AUTO_RETRY_FILA_INTERVAL_SECONDS") or "300"))
        max_tentativas = max(1, int(os.getenv("AUTO_RETRY_MAX_TENTATIVAS") or "10"))
        return {
            "enabled": enabled,
            "scheduler_mode": scheduler_mode,
            "interval_seconds": interval,
            "max_tentativas": max_tentativas,
        }

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        cfg = cls.get_config()
        scheduler_mode = cfg.get("scheduler_mode", get_scheduler_mode())
        is_leader = bool(cls._is_leader) if cfg["enabled"] else False
        return {
            "enabled": cfg["enabled"],
            "scheduler_mode": scheduler_mode,
            "worker_running": cls._running,
            "is_leader": is_leader,
            "lock_backend": cls.get_lock_backend(),
            "interval_seconds": cfg["interval_seconds"],
            "max_tentativas": cfg["max_tentativas"],
            "ultima_execucao": cls._last_run_at,
            "ultimo_resultado": cls._last_result,
        }

    @classmethod
    def _acquire_distributed_lock(cls, db, interval_seconds: int) -> tuple[bool, Any]:
        dialect = db.bind.dialect.name if db.bind is not None else engine.dialect.name
        if dialect == "postgresql":
            lock_conn = db.get_bind().connect()
            try:
                acquired = bool(
                    lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": cls._PG_LOCK_KEY}).scalar()
                )
                if not acquired:
                    lock_conn.close()
                    return False, None
                return True, lock_conn
            except Exception:
                lock_conn.close()
                raise

        now_naive = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        lease_seconds = max(60, min(int(interval_seconds or 300), 600))
        locked_until = now_naive + datetime.timedelta(seconds=lease_seconds)
        owner = cls._get_owner_id()

        try:
            db.add(
                SchedulerLock(
                    lock_name=cls._LOCK_NAME,
                    owner_id=owner,
                    locked_until=locked_until,
                    updated_at=now_naive,
                )
            )
            db.commit()
            return True, None
        except IntegrityError:
            db.rollback()

        res = db.execute(
            update(SchedulerLock)
            .where(
                SchedulerLock.lock_name == cls._LOCK_NAME,
                or_(
                    SchedulerLock.locked_until < now_naive,
                    SchedulerLock.owner_id == owner,
                ),
            )
            .values(
                owner_id=owner,
                locked_until=locked_until,
                updated_at=now_naive,
            )
        )
        db.commit()
        return (res.rowcount or 0) > 0, None

    @classmethod
    def _release_distributed_lock(cls, db, lock_conn: Any) -> None:
        dialect = db.bind.dialect.name if db.bind is not None else engine.dialect.name
        if dialect == "postgresql":
            if lock_conn is not None:
                try:
                    lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": cls._PG_LOCK_KEY})
                except Exception as exc:
                    logger.debug("Erro ao liberar pg_advisory_unlock: %s", exc)
                finally:
                    try:
                        lock_conn.close()
                    except Exception:
                        pass
            return

        try:
            db.execute(
                delete(SchedulerLock).where(
                    SchedulerLock.lock_name == cls._LOCK_NAME,
                    SchedulerLock.owner_id == cls._get_owner_id(),
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug("Erro ao liberar SchedulerLock: %s", exc)

    @classmethod
    async def run_fila_retry_cycle(cls) -> Dict[str, Any]:
        """Executa um ciclo completo de verificação e reenvio de notas na fila de contingência."""
        cfg = cls.get_config()
        max_tent = cfg["max_tentativas"]
        db = SessionLocal()
        lock_acquired = False
        lock_conn = None
        try:
            lock_acquired, lock_conn = cls._acquire_distributed_lock(db, cfg.get("interval_seconds", 300))
            if not lock_acquired:
                cls._is_leader = False
                return {
                    "total_processadas": 0,
                    "autorizadas": 0,
                    "falhas": 0,
                    "emails_enviados": 0,
                    "skipped_lock": True,
                }

            cls._is_leader = True
            dialect = db.bind.dialect.name if db.bind is not None else engine.dialect.name
            query = (
                db.query(Invoice)
                .filter(
                    Invoice.status == "fila_contingencia",
                    or_(Invoice.tentativas_envio.is_(None), Invoice.tentativas_envio < max_tent),
                )
                .order_by(Invoice.id.asc())
            )
            if dialect == "postgresql":
                query = query.with_for_update(skip_locked=True)

            pendentes = query.all()
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
            if lock_acquired:
                cls._release_distributed_lock(db, lock_conn)
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
            cls._is_leader = False
            return
        if cfg.get("scheduler_mode") == "leader":
            cls._is_leader = True
        if cls._task is None or cls._task.done():
            cls._task = asyncio.create_task(cls._worker_loop())

    @classmethod
    async def stop(cls) -> None:
        cls._running = False
        cls._is_leader = False
        if cls._task and not cls._task.done():
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass
        cls._task = None

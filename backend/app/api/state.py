"""
Módulo de estado global de tarefas em background.
Mantém `tasks_status` em memória para compatibilidade com testes e espelha/consulta
o estado persistido na tabela `background_tasks` via `TaskStore`.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from typing import Any, Dict, Optional

from app.database import SessionLocal
from app.models import BackgroundTask

logger = logging.getLogger(__name__)

# Dicionário em memória para rastrear o progresso e status das tarefas
# Formato: {"task_id_123": {"status": "running", "message": "...", "progress": 50}}
tasks_status: Dict[str, Dict[str, Any]] = {}
_STATE_LOCK = threading.Lock()


class TaskStore:
    """Armazenamento híbrido (memória + banco) de status de tarefas em background."""

    @staticmethod
    def _persist_task(
        task_id: str,
        payload: Dict[str, Any],
        kind: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> None:
        db = SessionLocal()
        try:
            now = datetime.datetime.now(datetime.UTC)
            status = str(payload.get("status") or "running")
            message = payload.get("message")
            message_str = str(message) if message is not None else None
            try:
                progress = int(payload.get("progress") or 0)
            except (TypeError, ValueError):
                progress = 0

            result_json = json.dumps(payload, ensure_ascii=False, default=str)

            row = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if row is None:
                row = BackgroundTask(
                    id=task_id,
                    kind=kind,
                    status=status,
                    message=message_str,
                    progress=progress,
                    result_json=result_json,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                if kind is not None and not row.kind:
                    row.kind = kind
                if created_by is not None and not row.created_by:
                    row.created_by = created_by
                row.status = status
                row.message = message_str
                row.progress = progress
                row.result_json = result_json
                row.updated_at = now
                db.add(row)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug("Falha ao persistir tarefa %s no banco: %s", task_id, exc)
        finally:
            db.close()

    @staticmethod
    def _load_from_db(task_id: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            row = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not row:
                return None
            data: Dict[str, Any] = {}
            if row.result_json:
                try:
                    parsed = json.loads(row.result_json)
                    if isinstance(parsed, dict):
                        data.update(parsed)
                except Exception:
                    pass
            data.setdefault("status", row.status)
            if row.message is not None:
                data.setdefault("message", row.message)
            data.setdefault("progress", row.progress)
            return data
        except Exception as exc:
            logger.debug("Falha ao consultar tarefa %s no banco: %s", task_id, exc)
            return None
        finally:
            db.close()

    @classmethod
    def set_task(
        cls,
        task_id: str,
        data: Dict[str, Any],
        kind: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = dict(data)
        with _STATE_LOCK:
            tasks_status[task_id] = payload
        cls._persist_task(task_id, payload, kind=kind, created_by=created_by)
        return payload

    @classmethod
    def update_task(cls, task_id: str, **fields: Any) -> Dict[str, Any]:
        with _STATE_LOCK:
            current = dict(tasks_status.get(task_id) or {})
        if not current:
            loaded = cls._load_from_db(task_id)
            if loaded:
                current = loaded
        current.update(fields)
        with _STATE_LOCK:
            tasks_status[task_id] = current
        cls._persist_task(task_id, current)
        return current

    @classmethod
    def get_task(cls, task_id: str) -> Optional[Dict[str, Any]]:
        loaded = cls._load_from_db(task_id)
        if loaded is not None:
            return loaded
        with _STATE_LOCK:
            mem = tasks_status.get(task_id)
            return dict(mem) if isinstance(mem, dict) else mem

"""Testes de operação multiusuário, WTS/desktop, storage configurável, concorrência de DPS, TaskStore e locks."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.state import TaskStore, tasks_status
from app.core.config import (
    get_certs_dir,
    get_data_dir,
    get_downloads_dir,
    get_sqlite_db_path,
    resolve_storage_path,
    to_storage_relative_path,
)
from app.database import SessionLocal
from app.main import app
from app.models import BackgroundTask, Client, SchedulerLock, init_db
from app.services.adn_service import AdnService
from app.services.scheduler_service import SchedulerService

client = TestClient(app)


def test_configurable_storage_dirs_and_portable_paths(tmp_path: Path, monkeypatch):
    """Valida NFSE_DATA_DIR, NFSE_CERTS_DIR, NFSE_DOWNLOADS_DIR, NFSE_DB_PATH e helpers de caminho portável."""
    data_dir = tmp_path / "custom_data"
    monkeypatch.setenv("NFSE_DATA_DIR", str(data_dir))
    monkeypatch.delenv("NFSE_CERTS_DIR", raising=False)
    monkeypatch.delenv("CERTIFICADOS_DIR", raising=False)
    monkeypatch.delenv("NFSE_DOWNLOADS_DIR", raising=False)
    monkeypatch.delenv("DOWNLOADS_DIR", raising=False)
    monkeypatch.delenv("NFSE_DB_PATH", raising=False)

    assert get_data_dir() == data_dir
    assert get_certs_dir() == data_dir / "certificados"
    assert get_downloads_dir() == data_dir / "downloads"
    assert get_sqlite_db_path() == data_dir / "nfse.db"

    # Overrides explícitos têm precedência sobre NFSE_DATA_DIR
    certs_override = tmp_path / "shared_certs"
    downloads_override = tmp_path / "shared_downloads"
    db_override = tmp_path / "db" / "custom.sqlite"
    monkeypatch.setenv("NFSE_CERTS_DIR", str(certs_override))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(downloads_override))
    monkeypatch.setenv("NFSE_DB_PATH", str(db_override))

    assert get_certs_dir() == certs_override
    assert get_downloads_dir() == downloads_override
    assert get_sqlite_db_path() == db_override

    # Conversão para caminho relativo POSIX portável e resolução de volta
    cert_file = certs_override / "12345678000199" / "empresa.pfx"
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    cert_file.write_bytes(b"pfx-bytes")

    rel_cert = to_storage_relative_path(cert_file, kind="certs")
    assert rel_cert == "12345678000199/empresa.pfx"
    resolved_cert = resolve_storage_path(rel_cert, kind="certs")
    assert resolved_cert == cert_file

    dl_file = downloads_override / "adn" / "dps" / "DPS_1.xml"
    dl_file.parent.mkdir(parents=True, exist_ok=True)
    dl_file.write_text("<DPS/>", encoding="utf-8")

    rel_dl = to_storage_relative_path(dl_file, kind="downloads")
    assert rel_dl == "adn/dps/DPS_1.xml"
    resolved_dl = resolve_storage_path(rel_dl, kind="downloads")
    assert resolved_dl == dl_file

    # Rebase de caminhos absolutos legados (ex: container Linux ou Windows/WTS)
    legacy_docker_cert = "/app/backend/certificados/12345678000199/empresa.pfx"
    assert resolve_storage_path(legacy_docker_cert, kind="certs") == cert_file

    legacy_windows_dl = r"C:\NFSeManager\downloads\adn\dps\DPS_1.xml"
    assert resolve_storage_path(legacy_windows_dl, kind="downloads") == dl_file

    # Caminho legado de container/SO que aponta exatamente para a raiz /downloads inexistente no host
    assert resolve_storage_path("/workspace_inexistente/backend/downloads", kind="downloads") == downloads_override
    assert (
        resolve_storage_path("/workspace_inexistente/backend/downloads/empresa_a", kind="downloads")
        == downloads_override / "empresa_a"
    )
    assert resolve_storage_path(r"C:\ProgramData\NFSeManager\downloads", kind="downloads") == downloads_override


def test_reservar_proximo_numero_dps_multithread_concurrency():
    """Garante que reservas concorrentes em múltiplas threads geram sequência única de DPS sem colisão."""
    init_db()
    cnpj = "66777888000144"
    db = SessionLocal()
    try:
        existing = db.query(Client).filter(Client.cnpj == cnpj).first()
        if existing:
            db.delete(existing)
            db.commit()

        cli = Client(
            cnpj=cnpj,
            razao_social="Prestador Concorrencia DPS LTDA",
            username=cnpj,
            codigo_municipio="3201308",
            serie_dps_padrao="900",
            ultimo_numero_dps=0,
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)
        client_id = cli.id
    finally:
        db.close()

    total_workers = 12

    def _reserve_one(_idx: int):
        local_db = SessionLocal()
        try:
            return AdnService.reservar_proximo_numero_dps(
                db=local_db,
                client_id=client_id,
            )
        finally:
            local_db.close()

    with ThreadPoolExecutor(max_workers=total_workers) as pool:
        results = list(pool.map(_reserve_one, range(total_workers)))

    series = {item[0] for item in results}
    numeros = sorted(item[1] for item in results)
    ids_dps = {item[2] for item in results}

    assert series == {"900"}
    assert numeros == list(range(1, total_workers + 1))
    assert len(ids_dps) == total_workers

    # `numero_informado` maior atualiza o ponteiro; menor não regride
    db_check = SessionLocal()
    try:
        _, num_high, _ = AdnService.reservar_proximo_numero_dps(
            db=db_check,
            client_id=client_id,
            numero_informado=50,
        )
        assert num_high == 50

        _, num_low, _ = AdnService.reservar_proximo_numero_dps(
            db=db_check,
            client_id=client_id,
            numero_informado=10,
        )
        assert num_low == 10

        refreshed = db_check.query(Client).filter(Client.id == client_id).first()
        assert refreshed.ultimo_numero_dps == 50
    finally:
        db_check.close()


def test_task_store_persists_to_background_tasks_table_across_workers():
    """Valida persistência do TaskStore em background_tasks e leitura via /api/tasks/{id} sem cache em memória."""
    init_db()
    task_id = "task_multiworker_test_001"

    db = SessionLocal()
    try:
        db.query(BackgroundTask).filter(BackgroundTask.id == task_id).delete()
        db.commit()
    finally:
        db.close()

    TaskStore.set_task(
        task_id,
        {"status": "running", "message": "Iniciando...", "progress": 10},
        kind="sync",
        created_by="operador_a",
    )
    TaskStore.update_task(
        task_id,
        status="completed",
        message="Concluído no worker B",
        progress=100,
        extra_count=7,
    )

    # Simula consulta em outro processo/worker sem o cache local `tasks_status`
    tasks_status.pop(task_id, None)

    loaded = TaskStore.get_task(task_id)
    assert loaded is not None
    assert loaded["status"] == "completed"
    assert loaded["message"] == "Concluído no worker B"
    assert loaded["progress"] == 100
    assert loaded["extra_count"] == 7

    res_api = client.get(f"/api/tasks/{task_id}")
    assert res_api.status_code == 200
    api_data = res_api.json()
    assert api_data["status"] == "completed"
    assert api_data["progress"] == 100
    assert api_data["extra_count"] == 7


def test_scheduler_disabled_mode_and_distributed_lock_contention(monkeypatch):
    """Valida NFSE_SCHEDULER_MODE=disabled e exclusão mútua via tabela scheduler_locks."""
    init_db()

    # 1. Modo disabled impede start() e marca enabled=False
    monkeypatch.setenv("NFSE_SCHEDULER_MODE", "disabled")
    cfg = SchedulerService.get_config()
    assert cfg["scheduler_mode"] == "disabled"
    assert cfg["enabled"] is False

    SchedulerService._task = None
    SchedulerService.start()
    assert SchedulerService._task is None
    st = SchedulerService.get_status()
    assert st["enabled"] is False
    assert st["is_leader"] is False

    # 2. Modo auto com lock na tabela scheduler_locks
    monkeypatch.setenv("NFSE_SCHEDULER_MODE", "auto")
    monkeypatch.setenv("AUTO_RETRY_FILA_ENABLED", "1")

    db_setup = SessionLocal()
    try:
        db_setup.query(SchedulerLock).delete()
        db_setup.commit()
    finally:
        db_setup.close()

    orig_owner = SchedulerService._owner_id
    db_a = SessionLocal()
    db_b = SessionLocal()
    db_c = SessionLocal()
    conn_a = None
    conn_b_after = None
    conn_c = None
    try:
        # Worker A adquire o lock
        SchedulerService._owner_id = "hostA:1001:aaaa"
        acquired_a, conn_a = SchedulerService._acquire_distributed_lock(db_a, 120)
        assert acquired_a is True

        # Worker B tenta adquirir enquanto o lease de A ainda é válido -> False
        SchedulerService._owner_id = "hostB:2002:bbbb"
        acquired_b, _ = SchedulerService._acquire_distributed_lock(db_b, 120)
        assert acquired_b is False

        # Ciclo do worker B respeita o lock e pula execução sem chamar ADN
        with patch(
            "app.services.scheduler_service.AdnService.reenviar_fila_contingencia",
            new=AsyncMock(),
        ) as mock_reenviar:
            cycle_res = asyncio.run(SchedulerService.run_fila_retry_cycle())
            assert cycle_res.get("skipped_lock") is True
            mock_reenviar.assert_not_called()

        # Worker A libera o lock -> Worker B consegue adquirir
        SchedulerService._owner_id = "hostA:1001:aaaa"
        SchedulerService._release_distributed_lock(db_a, conn_a)
        conn_a = None

        SchedulerService._owner_id = "hostB:2002:bbbb"
        acquired_b_after, conn_b_after = SchedulerService._acquire_distributed_lock(db_b, 120)
        assert acquired_b_after is True

        # Worker B assume e depois simula queda / expiração -> Worker C assume automaticamente
        if SchedulerService.get_lock_backend() == "pg_advisory_lock":
            assert conn_b_after is not None
            # invalidate() encerra o socket físico no pool (Close apenas devolveria ao pool com o advisory lock preso)
            conn_b_after.invalidate()
            conn_b_after = None
        else:
            lock_row = db_b.query(SchedulerLock).filter(SchedulerLock.lock_name == SchedulerService._LOCK_NAME).first()
            assert lock_row is not None
            lock_row.locked_until = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(seconds=30)
            db_b.commit()

        SchedulerService._owner_id = "hostC:3003:cccc"
        acquired_c, conn_c = SchedulerService._acquire_distributed_lock(db_c, 120)
        assert acquired_c is True
        SchedulerService._release_distributed_lock(db_c, conn_c)
        conn_c = None
        if conn_b_after is not None:
            SchedulerService._release_distributed_lock(db_b, conn_b_after)
            conn_b_after = None
    finally:
        SchedulerService._owner_id = orig_owner
        for session, conn in ((db_a, conn_a), (db_b, conn_b_after), (db_c, conn_c)):
            if conn is not None:
                SchedulerService._release_distributed_lock(session, conn)
            session.close()
        db_clean = SessionLocal()
        try:
            db_clean.query(SchedulerLock).delete()
            db_clean.commit()
        finally:
            db_clean.close()

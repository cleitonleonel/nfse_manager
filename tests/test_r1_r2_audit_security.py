"""Testes abrangentes para Milestone M1 (F01–F07):
- F01: TaskStore persistência de ownership (`created_by`, `kind`) e guarda anti-IDOR em `/api/tasks/{task_id}`
- F02: Paridade de FKs (`ON DELETE CASCADE`/`SET NULL`), `Client.batch_imports` cascade e `init_db()` (rollback + `smtp_password`)
- F03: Hardening de `clients.py` (CNPJ duplicado antes do disco, bloqueio `save_path="."`, RBAC `manager`/`admin` no `PUT`, reset de metadados do certificado) e `system/list-folders`
- F04: Validação de username em `POST /api/auth/users` e documento em `PUT /api/customers/{id}`
- F05/F06: `AuditLog`, `AuditService` (sanitização de segredos, `dummy_admin`, isolamento transacional), hooks nos routers e `GET /api/audit-logs`
- F07: Gestão de equipe via `client_links` (`manager`/`operator`), compatibilidade retroativa com `client_ids` e `last_login_at`
"""

from __future__ import annotations

import datetime
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.api.state import TaskStore, tasks_status
from app.core.migrations import create_admin_user
from app.core.security import is_encrypted
from app.database import SessionLocal, engine
from app.main import app
from app.models import (
    AuditLog,
    BackgroundTask,
    BatchImport,
    BatchImportItem,
    Client,
    Customer,
    Invoice,
    ServiceItem,
    User,
    UserClient,
    init_db,
)
from app.services.audit_service import AuditService

client = TestClient(app)


def _reset_db() -> None:
    init_db()
    tasks_status.clear()
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.query(UserClient).delete()
        db.query(BatchImportItem).delete()
        db.query(BatchImport).delete()
        db.query(Invoice).delete()
        db.query(Customer).delete()
        db.query(ServiceItem).delete()
        db.query(Client).delete()
        db.query(User).delete()
        db.query(BackgroundTask).delete()
        db.commit()
    finally:
        db.close()


def _login_headers(username: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_operator(
    admin_headers: dict[str, str],
    username: str,
    password: str = "OpPass123",
    client_ids: list[int] | None = None,
    client_links: list[dict] | None = None,
) -> dict:
    payload: dict = {
        "username": username,
        "email": f"{username}@empresa.com.br",
        "full_name": username.upper(),
        "password": password,
        "role": "operador",
    }
    if client_links is not None:
        payload["client_links"] = client_links
    elif client_ids is not None:
        payload["client_ids"] = client_ids

    res = client.post("/api/auth/users", headers=admin_headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


# ==============================================================================
# F01 — TaskStore & /api/tasks/{task_id} Anti-IDOR
# ==============================================================================


@pytest.mark.real_auth
def test_f01_task_store_persistence_and_anti_idor():
    _reset_db()
    create_admin_user("adm_f01", "adm_f01@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f01", "AdminPass123")
    _create_operator(adm_headers, "op1_f01")
    _create_operator(adm_headers, "op2_f01")
    op1_headers = _login_headers("op1_f01", "OpPass123")
    op2_headers = _login_headers("op2_f01", "OpPass123")

    task_id = "sync_f01_task"
    TaskStore.set_task(
        task_id,
        {"status": "running", "message": "Sincronizando...", "progress": 10},
        kind="sync",
        created_by="op1_f01",
    )

    # Simula perda de memória em worker separado e atualização parcial
    tasks_status.clear()
    updated = TaskStore.update_task(task_id, progress=80, message="Quase pronto")
    assert updated["created_by"] == "op1_f01"
    assert updated["kind"] == "sync"

    # Re-set sem passar created_by/kind preserva os valores existentes
    TaskStore.set_task(task_id, {"status": "completed", "progress": 100})
    tasks_status.clear()
    loaded = TaskStore.get_task(task_id)
    assert loaded is not None
    assert loaded["created_by"] == "op1_f01"
    assert loaded["kind"] == "sync"
    assert loaded["progress"] == 100

    # Endpoints HTTP (com memória limpa para garantir leitura do banco)
    assert client.get(f"/api/tasks/{task_id}").status_code == 401
    assert client.get(f"/api/tasks/{task_id}", headers=op2_headers).status_code == 403
    r_op1 = client.get(f"/api/tasks/{task_id}", headers=op1_headers)
    assert r_op1.status_code == 200
    assert r_op1.json()["created_by"] == "op1_f01"

    r_adm = client.get(f"/api/tasks/{task_id}", headers=adm_headers)
    assert r_adm.status_code == 200
    assert client.get("/api/tasks/inexistente_999", headers=adm_headers).status_code == 404


# ==============================================================================
# F02 — DB Parity, FK Cascades & init_db()
# ==============================================================================


@pytest.mark.real_auth
def test_f02_db_fk_cascade_and_init_db_smtp_encryption():
    _reset_db()
    db = SessionLocal()
    try:
        user = User(username="u_f02", password_hash="hash", role="operador", is_active=1)
        cli = Client(
            cnpj="99111222000133",
            razao_social="Empresa F02 Cascade LTDA",
            smtp_password="SmtpPlainPassword!",
        )
        db.add_all([user, cli])
        db.flush()

        db.add(UserClient(user_id=user.id, client_id=cli.id, access_level="manager"))
        db.add(Customer(client_id=cli.id, documento="11222333000181", razao_social="Tomador F02"))
        db.add(ServiceItem(client_id=cli.id, titulo="Servico F02", descricao="Desc F02"))
        inv1 = Invoice(client_id=cli.id, numero="1", chave="CHAVE-F02-1", status="gerada", tipo="emitidas")
        inv2 = Invoice(client_id=cli.id, numero="2", chave="CHAVE-F02-2", status="gerada", tipo="emitidas")
        db.add_all([inv1, inv2])
        db.flush()

        batch = BatchImport(client_id=cli.id, filename="lote.csv", file_hash="abc123")
        db.add(batch)
        db.flush()
        bi1 = BatchImportItem(batch_id=batch.id, row_number=1, payload_json="{}", invoice_id=inv1.id)
        bi2 = BatchImportItem(batch_id=batch.id, row_number=2, payload_json="{}", invoice_id=inv2.id)
        db.add_all([bi1, bi2])
        db.commit()

        AuditService.record(
            db,
            action="client.create",
            entity_type="client",
            entity_id=cli.id,
            client_id=cli.id,
            current_user=user,
            summary="Log F02",
            commit=True,
        )

        # Excluir inv1 deve desvincular bi1.invoice_id -> None (ON DELETE SET NULL / ORM)
        inv1_id = inv1.id
        bi1_id = bi1.id
        db.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": inv1_id})
        db.commit()
        db.expire_all()
        bi1_after = db.query(BatchImportItem).filter(BatchImportItem.id == bi1_id).first()
        assert bi1_after is not None
        assert bi1_after.invoice_id is None

        # Excluir client via ORM cascateia BatchImport/Customer/ServiceItem/Invoice/UserClient e preserva AuditLog
        cli_id = cli.id
        db.delete(cli)
        db.commit()

        assert db.query(Client).filter(Client.id == cli_id).count() == 0
        assert db.query(BatchImport).filter(BatchImport.client_id == cli_id).count() == 0
        assert db.query(Customer).filter(Customer.client_id == cli_id).count() == 0
        assert db.query(ServiceItem).filter(ServiceItem.client_id == cli_id).count() == 0
        assert db.query(Invoice).filter(Invoice.client_id == cli_id).count() == 0
        audit_row = db.query(AuditLog).filter(AuditLog.entity_id == str(cli_id)).first()
        assert audit_row is not None
        assert audit_row.client_id is None

        # Testa migração transparente de smtp_password em texto puro via init_db()
        cli2 = Client(cnpj="88111222000144", razao_social="Empresa SMTP Legada")
        db.add(cli2)
        db.commit()
        db.execute(
            text("UPDATE clients SET smtp_password = :raw WHERE id = :id"),
            {"raw": "senha_smtp_legada", "id": cli2.id},
        )
        db.commit()
        cli2_id = cli2.id
    finally:
        db.close()

    # Chama init_db() novamente (idempotência + criptografia + zero InFailedSqlTransaction)
    init_db()
    db = SessionLocal()
    try:
        raw_smtp = db.execute(
            text("SELECT smtp_password FROM clients WHERE id = :id"), {"id": cli2_id}
        ).scalar()
        assert raw_smtp is not None
        assert is_encrypted(raw_smtp)
        loaded_cli2 = db.query(Client).filter(Client.id == cli2_id).first()
        assert loaded_cli2 is not None
        assert loaded_cli2.smtp_password == "senha_smtp_legada"

        if engine.dialect.name == "postgresql":
            insp = inspect(engine)
            fk_map = {
                (t, tuple(fk["constrained_columns"])): (fk.get("options") or {}).get("ondelete", "").upper()
                for t in ("customers", "service_items", "invoices", "batch_imports", "batch_import_items")
                for fk in insp.get_foreign_keys(t)
            }
            assert fk_map[("customers", ("client_id",))] == "CASCADE"
            assert fk_map[("service_items", ("client_id",))] == "CASCADE"
            assert fk_map[("invoices", ("client_id",))] == "CASCADE"
            assert fk_map[("invoices", ("created_by_user_id",))] == "SET NULL"
            assert fk_map[("batch_imports", ("client_id",))] == "CASCADE"
            assert fk_map[("batch_import_items", ("batch_id",))] == "CASCADE"
            assert fk_map[("batch_import_items", ("invoice_id",))] == "SET NULL"
    finally:
        db.close()


# ==============================================================================
# F03 — Clients & System Hardening
# ==============================================================================


@pytest.mark.real_auth
def test_f03_client_duplicate_cnpj_preserves_cert_and_rejects_save_path_root(monkeypatch, tmp_path: Path):
    _reset_db()
    certs_dir = tmp_path / "certs"
    dl_dir = tmp_path / "downloads"
    certs_dir.mkdir(parents=True, exist_ok=True)
    dl_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NFSE_CERTS_DIR", str(certs_dir))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(dl_dir))

    create_admin_user("adm_f03a", "adm_f03a@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f03a", "AdminPass123")
    _create_operator(adm_headers, "op_f03a")
    op_headers = _login_headers("op_f03a", "OpPass123")

    # 1. Cria empresa com máscara no CNPJ e .pfx original
    r1 = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "12.345.678/0001-90", "razao_social": "Empresa Original LTDA"},
        files={"cert_file": ("original.pfx", io.BytesIO(b"ORIGINAL-PFX-BYTES"), "application/x-pkcs12")},
    )
    assert r1.status_code == 200, r1.text
    cid = r1.json()["id"]
    cert_disk_path = certs_dir / "12345678000190" / "original.pfx"
    assert cert_disk_path.read_bytes() == b"ORIGINAL-PFX-BYTES"

    # 2. Tentativa duplicada sem máscara e com máscara deve retornar 409 e NÃO apagar/sobrescrever .pfx
    for dup_cnpj in ("12345678000190", "12.345.678/0001-90"):
        r_dup = client.post(
            "/api/clients",
            headers=adm_headers,
            data={"cnpj": dup_cnpj, "razao_social": "Duplicada LTDA"},
            files={"cert_file": ("atacante.pfx", io.BytesIO(b"ATTACKER-PFX-BYTES"), "application/x-pkcs12")},
        )
        assert r_dup.status_code == 409
        assert cert_disk_path.exists()
        assert cert_disk_path.read_bytes() == b"ORIGINAL-PFX-BYTES"
        assert not (certs_dir / "12345678000190" / "atacante.pfx").exists()

    # 3. save_path="." / "./" / str(dl_dir) / "downloads" rejeitado com 400 (mesmo com allow_custom=1)
    for allow_custom in ("0", "1"):
        monkeypatch.setenv("NFSE_ALLOW_CUSTOM_CLIENT_SAVE_PATH", allow_custom)
        for bad_path in (".", "./", str(dl_dir), "downloads", "../fora"):
            r_bad = client.put(
                f"/api/clients/{cid}",
                headers=adm_headers,
                data={"save_path": bad_path},
            )
            assert r_bad.status_code == 400, f"Esperado 400 para {bad_path} (allow_custom={allow_custom})"

    # 4. Operador tentando definir save_path -> 403
    monkeypatch.setenv("NFSE_ALLOW_CUSTOM_CLIENT_SAVE_PATH", "0")
    assert client.post(
        "/api/clients",
        headers=op_headers,
        data={"cnpj": "98765432000110", "razao_social": "Op Emp", "save_path": "sub"},
    ).status_code == 403

    # 5. Admin define subpasta válida -> 200 e limpa com "" -> 200
    sub_dir = dl_dir / "emp_f03"
    r_ok = client.put(f"/api/clients/{cid}", headers=adm_headers, data={"save_path": str(sub_dir)})
    assert r_ok.status_code == 200
    assert r_ok.json()["save_path"] == "emp_f03"

    r_clr = client.put(f"/api/clients/{cid}", headers=adm_headers, data={"save_path": "   "})
    assert r_clr.status_code == 200
    assert r_clr.json()["save_path"] == ""


@pytest.mark.real_auth
def test_f03_client_put_manager_vs_operator_and_cert_metadata_reset(monkeypatch, tmp_path: Path):
    _reset_db()
    monkeypatch.setenv("NFSE_CERTS_DIR", str(tmp_path / "certs"))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(tmp_path / "downloads"))

    create_admin_user("adm_f03b", "adm_f03b@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f03b", "AdminPass123")

    r_cli = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "22333444000155", "razao_social": "Empresa RBAC LTDA"},
    )
    assert r_cli.status_code == 200
    cid = r_cli.json()["id"]

    _create_operator(adm_headers, "mgr_f03b", client_links=[{"client_id": cid, "access_level": "manager"}])
    _create_operator(adm_headers, "op_f03b", client_links=[{"client_id": cid, "access_level": "operator"}])
    _create_operator(adm_headers, "other_f03b", client_links=[])

    mgr_headers = _login_headers("mgr_f03b", "OpPass123")
    op_headers = _login_headers("op_f03b", "OpPass123")
    other_headers = _login_headers("other_f03b", "OpPass123")

    # Operador vinculado com access_level='operator' -> 403 em PUT /api/clients/{id}
    assert client.put(f"/api/clients/{cid}", headers=op_headers, data={"razao_social": "Hack"}).status_code == 403
    assert client.put(f"/api/clients/{cid}", headers=op_headers, data={"smtp_host": "evil.smtp"}).status_code == 403
    # Usuário sem vínculo -> 403
    assert client.put(f"/api/clients/{cid}", headers=other_headers, data={"razao_social": "Sem Vinculo"}).status_code == 403
    # Empresa inexistente -> 404 (admin)
    assert client.put("/api/clients/999999", headers=adm_headers, data={"razao_social": "X"}).status_code == 404

    # Gestor ('manager') altera razao_social -> 200, mas ainda recebe 403 se tentar alterar save_path
    r_mgr_ok = client.put(f"/api/clients/{cid}", headers=mgr_headers, data={"razao_social": "Empresa Gestor LTDA"})
    assert r_mgr_ok.status_code == 200
    assert r_mgr_ok.json()["razao_social"] == "Empresa Gestor LTDA"
    assert client.put(f"/api/clients/{cid}", headers=mgr_headers, data={"save_path": "pasta_mgr"}).status_code == 403

    # Upload de .pfx válido preenche cert_valid_until e cert_subject
    now = datetime.datetime.now(datetime.UTC)
    mock_cert = MagicMock()
    mock_cert.not_valid_after_utc = now + datetime.timedelta(days=120)
    mock_cert.subject.rfc4514_string.return_value = "CN=Cert Valido F03"
    mock_signer = MagicMock()
    mock_signer.certificate = mock_cert

    with patch("app.api.routers.clients.DpsSigner", return_value=mock_signer):
        r_cert_ok = client.put(
            f"/api/clients/{cid}",
            headers=mgr_headers,
            data={"cert_password": "1234"},
            files={"cert_file": ("valido.pfx", io.BytesIO(b"VALID-PFX"), "application/x-pkcs12")},
        )
    assert r_cert_ok.status_code == 200
    assert r_cert_ok.json()["cert_subject"] == "CN=Cert Valido F03"
    assert r_cert_ok.json()["cert_valid_until"] is not None

    # Atualizar razao_social enviando cert_password="" preserva metadados existentes
    r_keep = client.put(
        f"/api/clients/{cid}",
        headers=mgr_headers,
        data={"razao_social": "Empresa Preserva Cert", "cert_password": ""},
    )
    assert r_keep.status_code == 200
    assert r_keep.json()["cert_subject"] == "CN=Cert Valido F03"
    assert r_keep.json()["cert_valid_until"] is not None

    # Trocar por .pfx ilegível limpa cert_valid_until e cert_subject para None
    with patch("app.api.routers.clients.DpsSigner", side_effect=ValueError("PFX corrompido")):
        r_cert_bad = client.put(
            f"/api/clients/{cid}",
            headers=mgr_headers,
            data={"cert_password": "errada"},
            files={"cert_file": ("invalido.pfx", io.BytesIO(b"BAD-PFX"), "application/x-pkcs12")},
        )
    assert r_cert_bad.status_code == 200
    assert r_cert_bad.json()["cert_subject"] is None
    assert r_cert_bad.json()["cert_valid_until"] is None


@pytest.mark.real_auth
def test_f03_system_list_folders_defaults_to_downloads_dir(monkeypatch, tmp_path: Path):
    _reset_db()
    dl_root = tmp_path / "downloads_root"
    (dl_root / "sub_empresa").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(dl_root))

    create_admin_user("adm_f03c", "adm_f03c@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f03c", "AdminPass123")
    _create_operator(adm_headers, "op_f03c")
    op_headers = _login_headers("op_f03c", "OpPass123")

    assert client.get("/api/system/list-folders").status_code == 401
    assert client.get("/api/system/list-folders", headers=op_headers).status_code == 403

    r_default = client.get("/api/system/list-folders", headers=adm_headers)
    assert r_default.status_code == 200
    data = r_default.json()
    assert data["current"] == str(dl_root.resolve())
    assert any(f["name"] == "sub_empresa" for f in data["folders"])

    r_explicit = client.get("/api/system/list-folders", headers=adm_headers, params={"path": str(tmp_path)})
    assert r_explicit.status_code == 200
    assert r_explicit.json()["current"] == str(tmp_path.resolve())


# ==============================================================================
# F04 — Auth Username & Registry Customer Validation
# ==============================================================================


@pytest.mark.real_auth
def test_f04_auth_username_and_customer_update_validation():
    _reset_db()
    create_admin_user("adm_f04", "adm_f04@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f04", "AdminPass123")

    for bad_uname in ("ab", "a b", "   ", "um dois"):
        r_bad_u = client.post(
            "/api/auth/users",
            headers=adm_headers,
            json={"username": bad_uname, "password": "Password123", "role": "operador"},
        )
        assert r_bad_u.status_code == 400

    r_cli = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "33444555000166", "razao_social": "Empresa F04 LTDA"},
    )
    cid = r_cli.json()["id"]
    _create_operator(adm_headers, "op_valid", client_ids=[cid])
    _create_operator(adm_headers, "op_unlinked", client_ids=[])
    op_unlinked_headers = _login_headers("op_unlinked", "OpPass123")

    r_cust = client.post(
        "/api/customers",
        headers=adm_headers,
        json={"client_id": cid, "documento": "11.222.333/0001-81", "razao_social": "Tomador F04"},
    )
    assert r_cust.status_code == 200
    cust_id = r_cust.json()["id"]

    # Documentos inválidos (curto, vazio, None) -> 400
    for bad_doc in ("123", "", None):
        r_bad_c = client.put(
            f"/api/customers/{cust_id}",
            headers=adm_headers,
            json={"documento": bad_doc},
        )
        assert r_bad_c.status_code == 400

    # CPF válido -> 200 normalizado
    r_ok_c = client.put(
        f"/api/customers/{cust_id}",
        headers=adm_headers,
        json={"documento": "123.456.789-01"},
    )
    assert r_ok_c.status_code == 200
    assert r_ok_c.json()["documento"] == "12345678901"

    # Anti-IDOR e 404
    assert client.put(f"/api/customers/{cust_id}", headers=op_unlinked_headers, json={"razao_social": "X"}).status_code == 403
    assert client.put("/api/customers/999999", headers=adm_headers, json={"razao_social": "X"}).status_code == 404

    # Combinação tributária inválida no ServiceItem -> 422
    r_srv = client.post(
        "/api/service-items",
        headers=adm_headers,
        json={"client_id": cid, "titulo": "Srv F04", "descricao": "Desc"},
    )
    assert r_srv.status_code == 200
    srv_id = r_srv.json()["id"]
    r_srv_bad = client.put(
        f"/api/service-items/{srv_id}",
        headers=adm_headers,
        json={"c_class_trib": "999999", "cst_ibscbs": "999"},
    )
    assert r_srv_bad.status_code == 422


# ==============================================================================
# F05 & F06 — AuditService Sanitization, Router Hooks & /api/audit-logs API
# ==============================================================================


@pytest.mark.real_auth
def test_f06_audit_service_sanitization_and_router_hooks(monkeypatch, tmp_path: Path):
    _reset_db()
    monkeypatch.setenv("NFSE_CERTS_DIR", str(tmp_path / "certs"))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("NFSE_DISABLE_SELF_UPDATE", "0")

    # 1. Testa sanitização recursiva, dummy_admin(id=999999) e isolamento de erro
    db = SessionLocal()
    try:
        dummy_admin = User(id=999999, username="pytest_admin", role="admin", is_active=1)
        entry = AuditService.record(
            db,
            action="test.sanitize",
            entity_type="system",
            current_user=dummy_admin,
            summary="Teste sanitização",
            details={
                "password": "secret_password",
                "senha_cert": "minha_senha",
                "smtp_password": "smtp_secret",
                "token": "jwt_token",
                "api_key": "key_123",
                "authorization": "Bearer abc",
                "pfx": b"PFX-BINARY",
                "nested": {"secret": "hidden", "cert_subject": "CN=Empresa Segura"},
                "enc_val": "enc:gAAAAAB...",
                "hash_val": "pbkdf2_sha256$100$salt$hash",
                "raw_xml": "<NFSe><SignatureValue>abc</SignatureValue>" + ("x" * 350) + "</NFSe>",
                "cert_valid_until": "2027-01-01T00:00:00",
                "smtp_host": "smtp.empresa.com.br",
            },
            commit=True,
        )
        assert entry is not None
        assert entry.actor_user_id is None
        assert entry.actor_username == "pytest_admin"
        parsed = json.loads(entry.details_json)
        assert parsed["password"] == "[REDACTED]"
        assert parsed["senha_cert"] == "[REDACTED]"
        assert parsed["smtp_password"] == "[REDACTED]"
        assert parsed["token"] == "[REDACTED]"
        assert parsed["api_key"] == "[REDACTED]"
        assert parsed["authorization"] == "[REDACTED]"
        assert parsed["pfx"] == "[REDACTED]"
        assert parsed["nested"]["secret"] == "[REDACTED]"
        assert parsed["nested"]["cert_subject"] == "CN=Empresa Segura"
        assert parsed["enc_val"] == "[REDACTED]"
        assert parsed["hash_val"] == "[REDACTED]"
        assert parsed["raw_xml"].startswith("<xml_omitted:")
        assert parsed["smtp_host"] == "smtp.empresa.com.br"

        # Simula falha interna no AuditService sem corromper transação externa
        with patch.object(db, "flush", side_effect=RuntimeError("Falha simulada")):
            res_err = AuditService.record(db, action="test.fail", entity_type="system", summary="Falha", commit=False)
            assert res_err is None
        assert db.query(AuditLog).count() >= 1
    finally:
        db.close()

    # 2. Testa hooks de auditoria ponta a ponta nos routers (auth, clients, registry, catalogs, system)
    r_reg = client.post(
        "/api/auth/register",
        json={"username": "adm_f06", "email": "adm_f06@empresa.com.br", "password": "AdminPass123"},
    )
    assert r_reg.status_code == 200
    adm_headers = {"Authorization": f"Bearer {r_reg.json()['access_token']}"}

    # Login inválido -> auth.login_failed (sem vazar senha tentada!)
    assert client.post("/api/auth/login", json={"username": "adm_f06", "password": "WrongPassword999"}).status_code == 401
    adm_headers = _login_headers("adm_f06", "AdminPass123")
    assert client.post(
        "/api/auth/change-password",
        headers=adm_headers,
        json={"current_password": "errada", "new_password": "AdminPass456"},
    ).status_code == 400
    assert client.post(
        "/api/auth/change-password",
        headers=adm_headers,
        json={"current_password": "AdminPass123", "new_password": "AdminPass456"},
    ).status_code == 200
    adm_headers = _login_headers("adm_f06", "AdminPass456")

    op = _create_operator(adm_headers, "op_f06")
    client.patch(f"/api/auth/users/{op['id']}", headers=adm_headers, json={"full_name": "Op Atualizado"})
    client.delete(f"/api/auth/users/{op['id']}", headers=adm_headers)

    # Clients CRUD + cert + delete
    r_c = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "44555666000177", "razao_social": "Empresa Audit LTDA"},
    )
    assert r_c.status_code == 200
    cid = r_c.json()["id"]
    client.put(
        f"/api/clients/{cid}",
        headers=adm_headers,
        data={"razao_social": "Empresa Audit Editada"},
        files={"cert_file": ("a1.pfx", io.BytesIO(b"PFX"), "application/x-pkcs12")},
    )

    # Registry CRUD + batch-delete + import
    r_cust = client.post(
        "/api/customers",
        headers=adm_headers,
        json={"client_id": cid, "documento": "55666777000188", "razao_social": "Tom Audit"},
    )
    cust_id = r_cust.json()["id"]
    client.put(f"/api/customers/{cust_id}", headers=adm_headers, json={"razao_social": "Tom Audit 2"})
    client.delete(f"/api/customers/{cust_id}", headers=adm_headers)
    client.post(
        "/api/customers/import",
        headers=adm_headers,
        data={"client_id": str(cid)},
        files={"file": ("toms.csv", io.BytesIO(b"documento;razao_social\n11222333000181;Tom CSV\n"), "text/csv")},
    )
    client.post(
        "/api/customers/delete-batch",
        headers=adm_headers,
        json={"client_id": cid, "delete_all": True},
    )

    r_srv = client.post(
        "/api/service-items",
        headers=adm_headers,
        json={"client_id": cid, "titulo": "Srv Audit", "descricao": "Desc"},
    )
    srv_id = r_srv.json()["id"]
    client.put(f"/api/service-items/{srv_id}", headers=adm_headers, json={"titulo": "Srv Audit 2"})
    client.delete(f"/api/service-items/{srv_id}", headers=adm_headers)
    client.post(
        "/api/service-items/import",
        headers=adm_headers,
        data={"client_id": str(cid)},
        files={"file": ("srvs.csv", io.BytesIO(b"titulo;descricao\nSrv CSV;Desc CSV\n"), "text/csv")},
    )
    client.post(
        "/api/service-items/delete-batch",
        headers=adm_headers,
        json={"client_id": cid, "delete_all": True},
    )

    # Exclui cliente após registry ops
    assert client.delete(f"/api/clients/{cid}", headers=adm_headers).status_code == 200

    # Catalogs sync + System update download/apply
    with patch(
        "app.api.routers.catalogs.AdnService.sincronizar_catalogos_oficiais",
        return_value={"atualizado": True, "metadados": {"versao_db": "2026.1"}},
    ):
        assert client.post("/api/catalogs/sync", headers=adm_headers).status_code == 200

    with patch("app.api.routers.system._download_release_package"):
        r_upd = client.post("/api/system/update/download", headers=adm_headers, json={"version": "0.3.1"})
        assert r_upd.status_code == 200
        upd_task_id = r_upd.json()["task_id"]

    staged = tmp_path / "staged_release"
    staged.mkdir(parents=True, exist_ok=True)
    TaskStore.set_task(
        upd_task_id,
        {"status": "completed", "version": "0.3.1", "staged_path": str(staged)},
        kind="update_download",
        created_by="adm_f06",
    )
    with (
        patch("app.api.routers.system._copy_tree_transactional"),
        patch("app.api.routers.system.threading.Thread", return_value=SimpleNamespace(start=lambda: None)),
    ):
        assert client.post("/api/system/update/apply", headers=adm_headers, json={"task_id": upd_task_id}).status_code == 200

    db = SessionLocal()
    try:
        actions = {row.action for row in db.query(AuditLog).all()}
        expected_actions = {
            "auth.register",
            "auth.login_failed",
            "auth.login",
            "auth.change_password",
            "auth.user_create",
            "auth.user_update",
            "auth.user_delete",
            "client.create",
            "client.update",
            "client.cert_update",
            "client.delete",
            "registry.customer_create",
            "registry.customer_update",
            "registry.customer_delete",
            "registry.customer_import",
            "registry.customer_batch_delete",
            "registry.service_create",
            "registry.service_update",
            "registry.service_delete",
            "registry.service_import",
            "registry.service_batch_delete",
            "system.catalogs_sync",
            "system.update_download",
            "system.update_apply",
        }
        assert expected_actions.issubset(actions)
        failed_login = db.query(AuditLog).filter(AuditLog.action == "auth.login_failed").first()
        assert failed_login is not None
        assert failed_login.status == "denied"
        assert "WrongPassword999" not in (failed_login.details_json or "")
    finally:
        db.close()


@pytest.mark.real_auth
def test_f06_audit_logs_api_rbac_filters_and_pagination():
    _reset_db()
    create_admin_user("adm_audit", "adm_audit@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_audit", "AdminPass123")

    r_cli = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "55666777000199", "razao_social": "Empresa Filtro Audit LTDA"},
    )
    cid = r_cli.json()["id"]
    _create_operator(
        adm_headers,
        "mgr_audit",
        client_links=[{"client_id": cid, "access_level": "manager"}],
    )
    mgr_headers = _login_headers("mgr_audit", "OpPass123")

    # Sem JWT -> 401; operador (mesmo gestor de empresa) -> 403
    assert client.get("/api/audit-logs").status_code == 401
    assert client.get("/api/audit-logs", headers=mgr_headers).status_code == 403

    # Validações de data e paginação
    assert client.get("/api/audit-logs?date_from=data-invalida", headers=adm_headers).status_code == 400
    assert client.get("/api/audit-logs?page_size=500", headers=adm_headers).status_code == 422

    # Listagem paginada e filtros
    r_all = client.get("/api/audit-logs?page=1&page_size=2", headers=adm_headers)
    assert r_all.status_code == 200
    body = r_all.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) <= 2
    assert body["total"] >= 3
    assert "actions" in body["facets"]

    r_cli_logs = client.get(
        f"/api/audit-logs?action=client.create&entity_type=client&client_id={cid}&actor=adm_audit&status=success&q=Filtro",
        headers=adm_headers,
    )
    assert r_cli_logs.status_code == 200
    cli_items = r_cli_logs.json()["items"]
    assert len(cli_items) == 1
    assert cli_items[0]["client_name"] == "Empresa Filtro Audit LTDA"
    assert cli_items[0]["client_cnpj"] == "55666777000199"

    today_iso = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    r_dates = client.get(f"/api/audit-logs?date_from={today_iso}&date_to={today_iso}", headers=adm_headers)
    assert r_dates.status_code == 200
    assert r_dates.json()["total"] >= 1


# ==============================================================================
# F07 — Team Management (client_links, access_level, last_login_at)
# ==============================================================================


@pytest.mark.real_auth
def test_f07_team_access_levels_client_links_and_last_login():
    _reset_db()
    create_admin_user("adm_f07", "adm_f07@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f07", "AdminPass123")

    c1 = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "66111222000111", "razao_social": "Empresa C1 Manager"},
    ).json()["id"]
    c2 = client.post(
        "/api/clients",
        headers=adm_headers,
        data={"cnpj": "66111222000222", "razao_social": "Empresa C2 Operator"},
    ).json()["id"]

    # Validação de payload inválido em client_links
    assert client.post(
        "/api/auth/users",
        headers=adm_headers,
        json={
            "username": "op_bad_lvl",
            "password": "OpPass123",
            "client_links": [{"client_id": c1, "access_level": "super"}],
        },
    ).status_code == 422

    assert client.post(
        "/api/auth/users",
        headers=adm_headers,
        json={
            "username": "op_missing_cli",
            "password": "OpPass123",
            "client_links": [{"client_id": 999999, "access_level": "manager"}],
        },
    ).status_code == 400

    # Criação com client_links distintos (manager em C1, operator em C2)
    u_links = _create_operator(
        adm_headers,
        "op_team_links",
        client_links=[
            {"client_id": c1, "access_level": "manager"},
            {"client_id": c2, "access_level": "operator"},
        ],
    )
    assert sorted(u_links["client_ids"]) == sorted([c1, c2])
    links_map = {item["client_id"]: item["access_level"] for item in u_links["client_links"]}
    assert links_map == {c1: "manager", c2: "operator"}
    assert u_links["last_login_at"] is None

    # Compatibilidade retroativa: criação com client_ids define access_level="operator"
    u_legacy = _create_operator(adm_headers, "op_team_legacy", client_ids=[c1])
    assert u_legacy["client_ids"] == [c1]
    assert u_legacy["client_links"] == [{"client_id": c1, "access_level": "operator"}]

    # Login preenche last_login_at em login, /me e /users
    login_res = client.post("/api/auth/login", json={"username": "op_team_links", "password": "OpPass123"})
    assert login_res.status_code == 200
    login_json = login_res.json()
    assert login_json["user"]["last_login_at"] is not None
    op_headers = {"Authorization": f"Bearer {login_json['access_token']}"}

    me_res = client.get("/api/auth/me", headers=op_headers)
    assert me_res.status_code == 200
    assert me_res.json()["last_login_at"] is not None

    users_list = client.get("/api/auth/users", headers=adm_headers).json()
    found_u = next(u for u in users_list if u["username"] == "op_team_links")
    assert found_u["last_login_at"] is not None

    # Operador não pode chamar PATCH /api/auth/users/{id}
    assert client.patch(
        f"/api/auth/users/{u_legacy['id']}",
        headers=op_headers,
        json={"full_name": "Proibido"},
    ).status_code == 403

    # Manager pode editar/excluir C1 (200), mas é bloqueado em C2 (403)
    assert client.put(f"/api/clients/{c2}", headers=op_headers, data={"razao_social": "Bloqueado"}).status_code == 403
    assert client.delete(f"/api/clients/{c2}", headers=op_headers).status_code == 403
    assert client.put(f"/api/clients/{c1}", headers=op_headers, data={"razao_social": "C1 Editada"}).status_code == 200

    # Admin promove C2 para manager via PATCH e rebaixa C1 para operator
    r_patch = client.patch(
        f"/api/auth/users/{u_links['id']}",
        headers=adm_headers,
        json={
            "client_links": [
                {"client_id": c1, "access_level": "operator"},
                {"client_id": c2, "access_level": "manager"},
            ]
        },
    )
    assert r_patch.status_code == 200
    patched_map = {item["client_id"]: item["access_level"] for item in r_patch.json()["client_links"]}
    assert patched_map == {c1: "operator", c2: "manager"}

    assert client.put(f"/api/clients/{c1}", headers=op_headers, data={"razao_social": "Agora Bloqueado"}).status_code == 403
    assert client.delete(f"/api/clients/{c2}", headers=op_headers).status_code == 200

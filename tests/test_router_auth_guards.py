"""Testes de guarda de autenticação JWT, RBAC, gestão de usuários, ambiente e segurança de download."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.migrations import create_admin_user
from app.core.security import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Client, Invoice, User, init_db

client = TestClient(app)


def _reset_users() -> None:
    init_db()
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


def _login_headers(username: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.real_auth
def test_all_business_routers_require_authentication_401():
    """Garante que todos os routers protegidos rejeitam requisições sem JWT (401) e rotas públicas continuam abertas."""
    # Rotas públicas permanecem acessíveis sem token
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").status_code == 200

    protected_requests = [
        ("GET", "/api/auth/me", {}),
        ("GET", "/api/auth/users", {}),
        ("GET", "/api/clients", {}),
        ("GET", "/api/invoices", {}),
        ("GET", "/api/tasks/nonexistent_task_id", {}),
        ("GET", "/api/download/file?path=qualquer.pdf", {}),
        ("POST", "/api/download/batch", {"json": {"arquivos": ["a.xml"]}}),
        ("GET", "/api/analytics/stats", {}),
        ("GET", "/api/reports/export", {}),
        ("GET", "/api/reports/competencia", {}),
        ("GET", "/api/catalogs/cst", {}),
        ("POST", "/api/tax/calculate", {"json": {"valor_servico": 100.0}}),
        ("GET", "/api/adn/fila", {}),
        ("GET", "/api/adn/worker/status", {}),
        ("POST", "/api/adn/worker/trigger", {}),
        ("GET", "/api/customers", {}),
        ("GET", "/api/service-items", {}),
        ("GET", "/api/lookup/cnpj/12345678000190", {}),
        ("GET", "/api/batch-emission", {}),
        ("GET", "/api/batch-emission/template", {}),
        ("GET", "/api/system/version", {}),
        ("GET", "/api/system/environment", {}),
        ("GET", "/api/system/list-folders", {}),
        ("POST", "/api/system/update/download", {"json": {"version": "9.9.9"}}),
        ("POST", "/api/system/update/apply", {"json": {"task_id": "fake_task"}}),
        ("POST", "/api/support/message", {"json": {"email": "a@b.com", "message": "oi"}}),
    ]

    for method, url, kwargs in protected_requests:
        resp = client.request(method, url, **kwargs)
        assert resp.status_code == 401, f"Esperado 401 em {method} {url}, obtido {resp.status_code}: {resp.text}"

    # Token inválido também deve retornar 401
    bad_headers = {"Authorization": "Bearer token.invalido.aqui"}
    assert client.get("/api/clients", headers=bad_headers).status_code == 401


@pytest.mark.real_auth
def test_operator_forbidden_on_admin_routes_and_allowed_on_standard_routes():
    """Garante RBAC: operador recebe 403 em rotas administrativas e acesso normal nas operacionais."""
    _reset_users()
    admin = create_admin_user("rbac_admin", "rbac_admin@empresa.com.br", "AdminPass123", "Admin RBAC")
    admin_headers = _login_headers("rbac_admin", "AdminPass123")

    res_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "rbac_operador",
            "email": "rbac_op@empresa.com.br",
            "full_name": "Operador RBAC",
            "password": "OpPass123",
            "role": "operador",
        },
    )
    assert res_op.status_code == 200, res_op.text
    op_id = res_op.json()["id"]
    op_headers = _login_headers("rbac_operador", "OpPass123")

    # Rotas administrativas proibidas para operador (403)
    admin_only_requests = [
        ("GET", "/api/auth/users", {}),
        (
            "POST",
            "/api/auth/users",
            {"json": {"username": "xpto_user", "password": "Password123", "role": "operador"}},
        ),
        ("PATCH", f"/api/auth/users/{admin.id}", {"json": {"full_name": "Hack"}}),
        ("DELETE", f"/api/auth/users/{op_id}", {}),
        ("GET", "/api/system/list-folders", {}),
        ("POST", "/api/system/update/download", {"json": {"version": "9.9.9"}}),
        ("POST", "/api/system/update/apply", {"json": {"task_id": "task_123"}}),
        ("POST", "/api/adn/worker/trigger", {}),
    ]

    for method, url, kwargs in admin_only_requests:
        resp = client.request(method, url, headers=op_headers, **kwargs)
        assert resp.status_code == 403, f"Esperado 403 para operador em {method} {url}, obtido {resp.status_code}"

    # Rotas operacionais permitidas para operador
    assert client.get("/api/clients/certificados/alertas", headers=op_headers).status_code == 200
    assert client.get("/api/analytics/stats", headers=op_headers).status_code == 200
    assert client.get("/api/catalogs/cst", headers=op_headers).status_code == 200
    assert client.get("/api/system/environment", headers=op_headers).status_code == 200
    assert client.get("/api/adn/worker/status", headers=op_headers).status_code == 200


@pytest.mark.real_auth
def test_patch_user_management_and_last_admin_protections():
    """Valida PATCH /api/auth/users/{id}, bloqueios de auto-rebaixamento/desativação, último admin e login inativo."""
    _reset_users()
    admin1 = create_admin_user("adm_principal", "adm1@empresa.com.br", "AdmPass123", "Admin Um")
    adm1_headers = _login_headers("adm_principal", "AdmPass123")

    # Cria um operador para editar
    res_op = client.post(
        "/api/auth/users",
        headers=adm1_headers,
        json={
            "username": "op_editavel",
            "email": "op_orig@empresa.com.br",
            "full_name": "Nome Original",
            "password": "OrigPass123",
            "role": "operador",
        },
    )
    assert res_op.status_code == 200
    op_id = res_op.json()["id"]

    # 1. Edição de nome, e-mail, papel, status e redefinição de senha
    res_patch = client.patch(
        f"/api/auth/users/{op_id}",
        headers=adm1_headers,
        json={
            "full_name": "Nome Atualizado",
            "email": "OP_NOVO@empresa.com.br",
            "role": "admin",
            "is_active": 1,
            "password": "ResetPass456",
        },
    )
    assert res_patch.status_code == 200, res_patch.text
    patched = res_patch.json()
    assert patched["full_name"] == "Nome Atualizado"
    assert patched["email"] == "op_novo@empresa.com.br"
    assert patched["role"] == "admin"

    # Senha antiga não funciona mais; senha redefinida funciona
    assert client.post("/api/auth/login", json={"username": "op_editavel", "password": "OrigPass123"}).status_code == 401
    adm2_headers = _login_headers("op_editavel", "ResetPass456")

    # Conflito de e-mail já em uso -> 400
    res_email_dup = client.patch(
        f"/api/auth/users/{op_id}",
        headers=adm1_headers,
        json={"email": "adm1@empresa.com.br"},
    )
    assert res_email_dup.status_code == 400

    # Usuário inexistente -> 404
    assert client.patch("/api/auth/users/9999999", headers=adm1_headers, json={"full_name": "X"}).status_code == 404

    # 2. Como há dois admins ativos, admin1 pode rebaixar e desativar admin2 (op_editavel)
    res_demote = client.patch(
        f"/api/auth/users/{op_id}",
        headers=adm1_headers,
        json={"role": "operador", "is_active": 0},
    )
    assert res_demote.status_code == 200
    assert res_demote.json()["role"] == "operador"
    assert res_demote.json()["is_active"] == 0

    # Usuário desativado recebe 403 no login e 401 com token emitido anteriormente
    res_login_disabled = client.post(
        "/api/auth/login",
        json={"username": "op_editavel", "password": "ResetPass456"},
    )
    assert res_login_disabled.status_code == 403
    assert client.get("/api/auth/me", headers=adm2_headers).status_code == 401

    # Reativar usuário restaura login
    assert client.patch(f"/api/auth/users/{op_id}", headers=adm1_headers, json={"is_active": 1}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "op_editavel", "password": "ResetPass456"}).status_code == 200

    # 3. Bloqueio de auto-rebaixamento e auto-desativação para o próprio admin autenticado
    res_self_demote = client.patch(
        f"/api/auth/users/{admin1.id}",
        headers=adm1_headers,
        json={"role": "operador"},
    )
    assert res_self_demote.status_code == 400

    res_self_deact = client.patch(
        f"/api/auth/users/{admin1.id}",
        headers=adm1_headers,
        json={"is_active": 0},
    )
    assert res_self_deact.status_code == 400

    # 4. Proteção contra desativar/rebaixar o último admin ativo quando executado por outro contexto admin
    db = SessionLocal()
    try:
        phantom_admin = User(
            username="phantom_admin",
            email="phantom@empresa.com.br",
            full_name="Phantom Admin",
            password_hash=hash_password("Phantom123"),
            role="admin",
            is_active=0,  # inativo: não conta como outro admin ativo
        )
        db.add(phantom_admin)
        db.commit()
        db.refresh(phantom_admin)
    finally:
        db.close()

    from app.api.routers.auth import require_admin_user

    app.dependency_overrides[require_admin_user] = lambda: phantom_admin
    try:
        assert client.patch(f"/api/auth/users/{admin1.id}", json={"is_active": 0}).status_code == 400
        assert client.patch(f"/api/auth/users/{admin1.id}", json={"role": "operador"}).status_code == 400
    finally:
        app.dependency_overrides.pop(require_admin_user, None)


@pytest.mark.real_auth
def test_allow_public_register_flag_blocks_second_user_when_disabled(monkeypatch):
    """NFSE_ALLOW_PUBLIC_REGISTER=0 permite bootstrap do 1º admin e bloqueia o 2º auto-cadastro com 403."""
    _reset_users()
    monkeypatch.setenv("NFSE_ALLOW_PUBLIC_REGISTER", "0")

    st_before = client.get("/api/auth/status")
    assert st_before.status_code == 200
    assert st_before.json()["has_users"] is False
    assert st_before.json()["allow_self_register"] is False

    # Primeiro usuário (bootstrap admin) deve funcionar mesmo com NFSE_ALLOW_PUBLIC_REGISTER=0
    r1 = client.post(
        "/api/auth/register",
        json={
            "username": "bootstrap_adm",
            "email": "boot@empresa.com.br",
            "password": "BootPassword123",
        },
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["user"]["role"] == "admin"

    # Segundo auto-cadastro deve retornar 403
    r2 = client.post(
        "/api/auth/register",
        json={
            "username": "intruso_op",
            "email": "intruso@empresa.com.br",
            "password": "IntrusoPassword123",
        },
    )
    assert r2.status_code == 403

    # Reabilitando NFSE_ALLOW_PUBLIC_REGISTER=1, o status reflete True e permite operador
    monkeypatch.setenv("NFSE_ALLOW_PUBLIC_REGISTER", "1")
    st_open = client.get("/api/auth/status").json()
    assert st_open["allow_self_register"] is True
    r3 = client.post(
        "/api/auth/register",
        json={
            "username": "segundo_aberto",
            "email": "segundo_aberto@empresa.com.br",
            "password": "OpenPassword123",
        },
    )
    assert r3.status_code == 200
    assert r3.json()["user"]["role"] == "operador"


def test_system_environment_and_disable_self_update(tmp_path: Path, monkeypatch):
    """Valida GET /api/system/environment e bloqueio de update quando NFSE_DISABLE_SELF_UPDATE=1."""
    data_dir = tmp_path / "data"
    certs_dir = tmp_path / "certs"
    downloads_dir = tmp_path / "downloads"
    monkeypatch.setenv("NFSE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("NFSE_CERTS_DIR", str(certs_dir))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(downloads_dir))
    monkeypatch.setenv("NFSE_SCHEDULER_MODE", "disabled")
    monkeypatch.setenv("NFSE_DISABLE_SELF_UPDATE", "1")

    res = client.get("/api/system/environment")
    assert res.status_code == 200, res.text
    env_data = res.json()

    assert env_data["database_connected"] is True
    assert env_data["database_dialect"] in {"sqlite", "postgresql"}
    assert env_data["paths"]["data_dir"] == str(data_dir)
    assert env_data["paths"]["certs_dir"] == str(certs_dir)
    assert env_data["paths"]["downloads_dir"] == str(downloads_dir)
    assert env_data["paths"]["certs_writable"] is True
    assert env_data["paths"]["downloads_writable"] is True
    assert env_data["scheduler"]["enabled"] is False
    assert env_data["self_update_allowed"] is False

    # Rotas de self-update retornam 403 quando desabilitado
    r_dl = client.post("/api/system/update/download", json={"version": "9.9.9"})
    assert r_dl.status_code == 403

    r_ap = client.post("/api/system/update/apply", json={"task_id": "qualquer"})
    assert r_ap.status_code == 403


def test_download_file_path_traversal_protection(tmp_path: Path, monkeypatch):
    """Garante bloqueio (403) contra Path Traversal e permissão apenas em diretórios autorizados ou notas."""
    allowed_dir = tmp_path / "allowed_downloads"
    allowed_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(allowed_dir))

    outside_dir = tmp_path / "secret_outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "segredo.txt"
    outside_file.write_text("conteudo sensivel", encoding="utf-8")

    # 1. Tentativas fora das raízes permitidas -> 403
    for bad_path in (
        "/etc/passwd",
        "../../etc/passwd",
        str(outside_file),
        str(allowed_dir / ".." / "secret_outside" / "segredo.txt"),
        "nota\x00.pdf",
    ):
        resp = client.get("/api/download/file", params={"path": bad_path})
        assert resp.status_code == 403, f"Deveria bloquear '{bad_path}' com 403, obteve {resp.status_code}"

    # 2. Arquivo dentro de NFSE_DOWNLOADS_DIR -> 200
    valid_pdf = allowed_dir / "danfse_ok.pdf"
    valid_pdf.write_bytes(b"%PDF-1.4 ok")
    res_ok = client.get("/api/download/file", params={"path": str(valid_pdf)})
    assert res_ok.status_code == 200
    assert res_ok.content == b"%PDF-1.4 ok"

    # 3. Arquivo dentro de save_path de um Client ou registrado em Invoice -> 200
    client_save_dir = tmp_path / "client_custom_save"
    client_save_dir.mkdir(parents=True, exist_ok=True)
    custom_xml = client_save_dir / "nota_custom.xml"
    custom_xml.write_text("<NFSe/>", encoding="utf-8")

    db = SessionLocal()
    try:
        cli = Client(
            cnpj="77888999000155",
            razao_social="Cliente Save Path Teste",
            username="77888999000155",
            save_path=str(client_save_dir),
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)

        inv = Invoice(
            client_id=cli.id,
            numero="777",
            chave="32013087788899900015500000000000077726110000000777",
            status="gerada",
            tipo="emitidas",
            xml_path=str(custom_xml),
        )
        db.add(inv)
        db.commit()
    finally:
        db.close()

    res_cli = client.get("/api/download/file", params={"path": str(custom_xml)})
    assert res_cli.status_code == 200
    assert res_cli.content == b"<NFSe/>"


def test_support_message_dispatches_email_and_telegram(monkeypatch):
    """Valida envio de suporte por E-mail (SMTP) + Telegram, fallback sem config e erro 502 quando todos falham."""
    from unittest.mock import AsyncMock, MagicMock, patch

    # 1. Sem configuração de SMTP/Telegram -> fallback seguro (200 OK)
    for var in (
        "DEFAULT_SMTP_HOST",
        "DEFAULT_SMTP_USER",
        "DEFAULT_SMTP_PASSWORD",
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SUPPORT_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    res_none = client.post(
        "/api/support/message",
        json={"email": "user@test.com", "whatsapp": "(27) 99999-0000", "message": "Olá!"},
    )
    assert res_none.status_code == 200
    assert res_none.json()["channels"] == {"email": "not_configured", "telegram": "not_configured"}

    # 2. Com SMTP e Telegram configurados -> envia para ambos
    monkeypatch.setenv("DEFAULT_SMTP_HOST", "smtp.teste.com")
    monkeypatch.setenv("DEFAULT_SMTP_PORT", "587")
    monkeypatch.setenv("DEFAULT_SMTP_USER", "noreply@teste.com")
    monkeypatch.setenv("DEFAULT_SMTP_PASSWORD", "segredo")
    monkeypatch.setenv("SUPPORT_EMAIL_TO", "cleiton.leonel@gmail.com")
    monkeypatch.setenv("SUPPORT_TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setenv("SUPPORT_TELEGRAM_CHAT_ID", "987654321")

    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = smtp_instance

    tg_resp = MagicMock()
    tg_resp.status_code = 200
    tg_resp.json.return_value = {"ok": True}

    http_cm = AsyncMock()
    http_cm.__aenter__.return_value.post = AsyncMock(return_value=tg_resp)

    with (
        patch("app.services.email_service.smtplib.SMTP", return_value=smtp_cm),
        patch("app.services.support_service.httpx.AsyncClient", return_value=http_cm),
    ):
        res_both = client.post(
            "/api/support/message",
            json={
                "email": "cleiton.leonel@gmail.com",
                "whatsapp": "(27) 99577-2291",
                "message": "Muito bom, gostei do sistema.",
            },
        )

    assert res_both.status_code == 200, res_both.text
    assert res_both.json()["channels"] == {"email": "sent", "telegram": "sent"}
    smtp_instance.login.assert_called_once_with("noreply@teste.com", "segredo")
    smtp_instance.send_message.assert_called_once()
    sent_email = smtp_instance.send_message.call_args[0][0]
    assert sent_email["To"] == "cleiton.leonel@gmail.com"
    assert sent_email["Reply-To"] == "cleiton.leonel@gmail.com"

    tg_call = http_cm.__aenter__.return_value.post.call_args
    assert "123456:TEST_TOKEN/sendMessage" in tg_call[0][0]
    assert tg_call[1]["json"]["chat_id"] == "987654321"
    assert "Muito bom, gostei do sistema." in tg_call[1]["json"]["text"]

    # 3. Se ambos configurados falharem -> 502 Bad Gateway
    tg_err_resp = MagicMock()
    tg_err_resp.status_code = 400
    tg_err_resp.text = "Bad Request: chat not found"
    tg_err_resp.json.return_value = {"description": "Bad Request: chat not found"}
    http_err_cm = AsyncMock()
    http_err_cm.__aenter__.return_value.post = AsyncMock(return_value=tg_err_resp)

    with (
        patch("app.services.email_service.smtplib.SMTP", side_effect=OSError("SMTP down")),
        patch("app.services.support_service.httpx.AsyncClient", return_value=http_err_cm),
    ):
        res_fail = client.post(
            "/api/support/message",
            json={"email": "user@test.com", "whatsapp": "", "message": "Falhou tudo"},
        )
    assert res_fail.status_code == 502


@pytest.mark.real_auth
def test_catalogs_sync_requires_admin_role(monkeypatch, tmp_path):
    """Garante que apenas administradores podem disparar a sincronização oficial de catálogos."""
    from unittest.mock import patch

    _reset_users()
    create_admin_user("admin_cat", "admin_cat@teste.com", "AdminPassword1!", "Admin Catalogo")
    admin_headers = _login_headers("admin_cat", "AdminPassword1!")
    res_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "operador_cat",
            "email": "op_cat@teste.com",
            "full_name": "Operador Catalogo",
            "password": "OperPassword1!",
            "role": "operador",
        },
    )
    assert res_op.status_code == 200, res_op.text
    op_headers = _login_headers("operador_cat", "OperPassword1!")

    # Operador pode consultar status, mas não pode disparar /sync (403)
    assert client.get("/api/catalogs/status", headers=op_headers).status_code == 200
    assert client.post("/api/catalogs/sync", headers=op_headers).status_code == 403

    monkeypatch.setenv("NFSE_CATALOGS_DIR", str(tmp_path / "rbac_catalogs"))
    with patch(
        "app.services.adn_service.atualizar_catalogos_oficiais",
        return_value={"atualizado": False, "metadados": {"versao_db": "V0073"}},
    ):
        r_admin = client.post("/api/catalogs/sync", headers=admin_headers)
    assert r_admin.status_code == 200
    assert r_admin.json()["metadados"]["versao_db"] == "V0073"


@pytest.mark.real_auth
def test_client_save_path_restricted_to_admin_and_downloads_root(monkeypatch, tmp_path):
    """Garante que apenas administradores alteram `save_path` e apenas dentro de `NFSE_DOWNLOADS_DIR`."""
    _reset_users()
    create_admin_user("admin_sp", "admin_sp@teste.com", "AdminPassword1!", "Admin SavePath")
    admin_headers = _login_headers("admin_sp", "AdminPassword1!")
    res_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "operador_sp",
            "email": "op_sp@teste.com",
            "full_name": "Operador SavePath",
            "password": "OperPassword1!",
            "role": "operador",
        },
    )
    assert res_op.status_code == 200, res_op.text
    op_headers = _login_headers("operador_sp", "OperPassword1!")

    dl_root = tmp_path / "dl_root"
    dl_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(dl_root))

    # 1. Operador tentando definir save_path na criação -> 403
    r_op_create = client.post(
        "/api/clients",
        headers=op_headers,
        data={"cnpj": "11222333000144", "razao_social": "EMP OP LTDA", "save_path": "subpasta"},
    )
    assert r_op_create.status_code == 403

    # 2. Operador cria cliente SEM save_path -> 200
    r_op_ok = client.post(
        "/api/clients",
        headers=op_headers,
        data={"cnpj": "11222333000145", "razao_social": "EMP OP OK LTDA"},
    )
    assert r_op_ok.status_code == 200, r_op_ok.text
    cid = r_op_ok.json()["id"]

    # 3. Operador tentando alterar save_path no PUT -> 403
    r_op_put = client.put(
        f"/api/clients/{cid}",
        headers=op_headers,
        data={"razao_social": "EMP OP OK LTDA", "save_path": "subpasta"},
    )
    assert r_op_put.status_code == 403

    # 4. Admin tentando path traversal / fora de downloads -> 400
    r_adm_bad = client.put(
        f"/api/clients/{cid}",
        headers=admin_headers,
        data={"razao_social": "EMP OP OK LTDA", "save_path": "/etc"},
    )
    assert r_adm_bad.status_code == 400

    # 5. Admin definindo subpasta válida dentro de downloads_dir -> 200 e caminho portável relativo
    sub_dir = dl_root / "empresa_a"
    sub_dir.mkdir(parents=True, exist_ok=True)
    r_adm_ok = client.put(
        f"/api/clients/{cid}",
        headers=admin_headers,
        data={"razao_social": "EMP OP OK LTDA", "save_path": str(sub_dir)},
    )
    assert r_adm_ok.status_code == 200, r_adm_ok.text
    assert r_adm_ok.json()["save_path"] == "empresa_a"

    # 6. Operador editando outro campo (sem mudar save_path) -> 200
    r_op_keep = client.put(
        f"/api/clients/{cid}",
        headers=op_headers,
        data={"razao_social": "EMP OP ATUALIZADA LTDA"},
    )
    assert r_op_keep.status_code == 200, r_op_keep.text
    assert r_op_keep.json()["save_path"] == "empresa_a"


@pytest.mark.real_auth
def test_clear_local_invoices_admin_only_and_unlinks_batch_items():
    """Garante que apenas admin limpa notas da base local e que FKs de batch_import_items são desvinculadas."""
    from app.models import BatchImport, BatchImportItem, Client, Invoice

    _reset_users()
    create_admin_user("admin_clr", "admin_clr@teste.com", "AdminPassword1!", "Admin Limpeza")
    admin_headers = _login_headers("admin_clr", "AdminPassword1!")
    res_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "operador_clr",
            "email": "op_clr@teste.com",
            "full_name": "Operador Limpeza",
            "password": "OperPassword1!",
            "role": "operador",
        },
    )
    assert res_op.status_code == 200, res_op.text
    op_headers = _login_headers("operador_clr", "OperPassword1!")

    db = SessionLocal()
    try:
        cli = Client(cnpj="99888777000166", razao_social="Empresa Limpar Notas LTDA")
        db.add(cli)
        db.commit()
        db.refresh(cli)

        inv1 = Invoice(client_id=cli.id, numero="101", chave="1" * 49 + "1", tipo="emitidas", status="gerada")
        inv2 = Invoice(client_id=cli.id, numero="102", chave="1" * 49 + "2", tipo="emitidas", status="gerada")
        inv3 = Invoice(client_id=cli.id, numero="103", chave="1" * 49 + "3", tipo="recebidas", status="gerada")
        db.add_all([inv1, inv2, inv3])
        db.commit()
        db.refresh(inv1)
        db.refresh(inv2)
        db.refresh(inv3)

        batch = BatchImport(client_id=cli.id, filename="lote.csv", file_hash="abc123", total_items=1)
        db.add(batch)
        db.commit()
        db.refresh(batch)

        b_item = BatchImportItem(batch_id=batch.id, row_number=1, payload_json="{}", invoice_id=inv1.id)
        db.add(b_item)
        db.commit()
        db.refresh(b_item)

        cli_id, inv1_id, inv3_id, b_item_id = cli.id, inv1.id, inv3.id, b_item.id
    finally:
        db.close()

    # Operador não pode limpar nem deletar nota local
    r_op_clear = client.post("/api/invoices/limpar-local", headers=op_headers, json={"invoice_ids": [inv1_id]})
    assert r_op_clear.status_code == 403
    r_op_del = client.delete(f"/api/invoices/{inv1_id}", headers=op_headers)
    assert r_op_del.status_code == 403

    # Admin sem filtros nem IDs -> 400
    r_bad = client.post("/api/invoices/limpar-local", headers=admin_headers, json={})
    assert r_bad.status_code == 400

    # Admin remove inv1 (com BatchImportItem apontando para ela) via endpoint em lote
    r_ok = client.post("/api/invoices/limpar-local", headers=admin_headers, json={"invoice_ids": [inv1_id]})
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["removidas"] == 1

    # Admin remove inv2 por filtro (client_id + tipo="emitidas") e inv3 via DELETE unitário
    r_filter = client.post(
        "/api/invoices/limpar-local",
        headers=admin_headers,
        json={"client_id": cli_id, "tipo": "emitidas"},
    )
    assert r_filter.status_code == 200, r_filter.text
    assert r_filter.json()["removidas"] == 1

    r_single = client.delete(f"/api/invoices/{inv3_id}", headers=admin_headers)
    assert r_single.status_code == 200, r_single.text
    assert r_single.json()["removidas"] == 1

    db_check = SessionLocal()
    try:
        remaining = db_check.query(Invoice).filter(Invoice.client_id == cli_id).count()
        assert remaining == 0
        refreshed_item = db_check.query(BatchImportItem).filter(BatchImportItem.id == b_item_id).first()
        assert refreshed_item is not None
        assert refreshed_item.invoice_id is None
    finally:
        db_check.close()

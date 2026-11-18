"""Testes de cobertura para:
- CLI estilo Django (`manage.py`: makemigrations, migrate, showmigrations, create_admin)
- Carregamento de variáveis `.env` (`app.core.config`)
- Hash de senhas e tokens JWT (`app.core.security`)
- Endpoints de Autenticação e Gestão de Operadores (`/api/auth/*`)
- Monitoramento e Alertas de Vencimento de Certificados A1 (`/api/clients/certificados/alertas` e `/api/analytics/stats`)
- Worker Agendado de Retransmissão da Fila de Contingência (`SchedulerService` e `/api/adn/worker/*`)
"""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.routers.clients import extrair_metadados_certificado_pfx
from app.core.config import load_dotenv_if_present
from app.core.migrations import (
    create_admin_user,
    get_applied_versions,
    get_cumulative_migrations_snapshot,
    makemigrations,
    migrate,
    showmigrations,
)
from app.core.security import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from app.database import SessionLocal, resolve_database_url
from app.main import app
from app.models import BatchImport, BatchImportItem, Client, Customer, Invoice, ServiceItem, User
from app.services.lookup_service import _clean_cnpj
from app.services.scheduler_service import SchedulerService
import manage

client = TestClient(app)


# ==============================================================================
# 1. Config (.env) & Security (PBKDF2 + JWT)
# ==============================================================================


def test_load_dotenv_if_present(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env.custom"
    env_file.write_text(
        "# Comentário de teste\n"
        "TEST_VAR_ALPHA=valor_alpha\n"
        "export TEST_VAR_QUOTED='valor com espaco'\n"
        'TEST_VAR_DOUBLE="duplo"\n'
        "LINHA_SEM_IGUAL\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEST_VAR_ALPHA", raising=False)
    monkeypatch.delenv("TEST_VAR_QUOTED", raising=False)
    monkeypatch.delenv("TEST_VAR_DOUBLE", raising=False)

    loaded = load_dotenv_if_present(env_path=env_file, override=True)
    assert loaded["TEST_VAR_ALPHA"] == "valor_alpha"
    assert loaded["TEST_VAR_QUOTED"] == "valor com espaco"
    assert loaded["TEST_VAR_DOUBLE"] == "duplo"


def test_resolve_database_url_docker_vs_local_vs_sqlite_fallback(monkeypatch):
    # 1. Quando DATABASE_URL aponta para @database:5432 mas estamos fora do Docker e Postgres está ativo em localhost:5434
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@database:5432/nfse_db")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5434")
    with (
        patch("app.database._can_resolve_host", return_value=False),
        patch("app.database._is_tcp_port_open", side_effect=lambda h, p, timeout=0.5: int(p) == 5434),
    ):
        url_pg_local = resolve_database_url()
        assert "@localhost:5434/nfse_db" in url_pg_local

    # 2. Quando estamos fora do Docker e nenhum PostgreSQL está rodando -> fallback para SQLite local
    with (
        patch("app.database._can_resolve_host", return_value=False),
        patch("app.database._is_tcp_port_open", return_value=False),
    ):
        url_sqlite = resolve_database_url()
        assert url_sqlite.startswith("sqlite:///")
        assert url_sqlite.endswith("backend/nfse.db")


def test_password_hashing_and_jwt_tokens():
    pwd = " MinhaSenhaForte!2026 "
    hashed = hash_password(pwd)
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("senha_errada", hashed) is False
    assert verify_password(pwd, "formato_invalido") is False
    assert verify_password("", hashed) is False

    token = create_access_token({"sub": "admin", "role": "admin"}, expires_minutes=15)
    payload = verify_access_token(token)
    assert payload is not None
    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"

    # Token adulterado ou malformado
    assert verify_access_token(token + "x") is None
    assert verify_access_token("invalido.sem.partes.corretas") is None
    assert verify_access_token("") is None

    # Token expirado
    expired_token = create_access_token({"sub": "admin"}, expires_minutes=-5)
    assert verify_access_token(expired_token) is None


# ==============================================================================
# 2. Motor de Migrações e CLI `manage.py`
# ==============================================================================


def test_migrations_engine_and_manage_cli(tmp_path: Path, monkeypatch):
    mig_dir = tmp_path / "migrations"
    db_file = tmp_path / "test_mig.sqlite"
    temp_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})

    # 1. Gera a migração inicial 0001_initial.py num diretório limpo
    mig_path = makemigrations(migrations_dir=mig_dir)
    assert mig_path is not None
    assert mig_path.name == "0001_initial.py"

    # 2. Rodar novamente sem mudanças nos models deve retornar None
    assert makemigrations(migrations_dir=mig_dir) is None

    # 3. Simula que a migração 0001 não tinha a coluna `cert_subject` em `clients`
    # para testar geração incremental 0002_add_cert_subject.py
    snap = get_cumulative_migrations_snapshot(mig_dir)
    assert "clients" in snap
    content_0001 = (
        mig_path.read_text(encoding="utf-8")
        .replace(", 'cert_subject': 'VARCHAR'", "")
        .replace("'cert_subject': 'VARCHAR', ", "")
    )
    mig_path.write_text(content_0001, encoding="utf-8")

    mig_path_2 = makemigrations(name="add cert subject", migrations_dir=mig_dir)
    assert mig_path_2 is not None
    assert mig_path_2.name == "0002_add_cert_subject.py"

    # 4. Verifica showmigrations antes de aplicar
    status_before = showmigrations(migrations_dir=mig_dir, db_engine=temp_engine)
    assert len(status_before) == 2
    assert all(is_applied is False for _, _, is_applied in status_before)

    # 5. Aplica migrate no banco temporário
    applied = migrate(migrations_dir=mig_dir, db_engine=temp_engine)
    assert applied == ["0001_initial", "0002_add_cert_subject"]
    assert "0001" in get_applied_versions(temp_engine)
    assert "0002" in get_applied_versions(temp_engine)

    # 6. Rodar migrate novamente não deve reaplicar nada
    assert migrate(migrations_dir=mig_dir, db_engine=temp_engine) == []

    # 7. Testa os subcomandos da CLI `manage.py`
    assert manage.main(["showmigrations"]) == 0
    assert manage.main(["makemigrations"]) == 0
    assert manage.main(["migrate"]) == 0

    # 8. Testa `manage.py create_admin` via argumentos de linha de comando
    rc = manage.main(
        [
            "create_admin",
            "--username",
            "cli_admin",
            "--email",
            "cli_admin@empresa.com.br",
            "--password",
            "SenhaAdmin123",
        ]
    )
    assert rc == 0

    # 9. Testa `manage.py create_admin` interativo (com input + getpass)
    inputs = iter(["inter_admin", "inter@empresa.com.br"])
    passwords = iter(["SenhaInter123", "SenhaInter123"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(passwords))
    assert manage.main(["createsuperuser"]) == 0

    # 10. Testa erro quando senhas interativas não conferem
    inputs_err = iter(["err_admin", "err@empresa.com.br"])
    passwords_err = iter(["SenhaA", "SenhaB"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs_err))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(passwords_err))
    assert manage.main(["create_admin"]) == 1


# ==============================================================================
# 3. Autenticação JWT e Gestão de Operadores (`/api/auth/*`)
# ==============================================================================


@pytest.mark.real_auth
def test_auth_router_lifecycle():
    # Garante a existência do admin via `create_admin_user`
    admin = create_admin_user("admin_master", "master@empresa.com.br", "MasterPass123", "Master Admin")
    assert admin.role == "admin"

    # 1. Status inicial
    res_status = client.get("/api/auth/status")
    assert res_status.status_code == 200
    assert res_status.json()["has_users"] is True

    # 2. Login inválido
    res_bad = client.post("/api/auth/login", json={"username": "admin_master", "password": "wrong"})
    assert res_bad.status_code == 401

    # 3. Login válido por username e por e-mail
    res_login = client.post(
        "/api/auth/login",
        json={"username": "admin_master", "password": "MasterPass123"},
    )
    assert res_login.status_code == 200
    token_data = res_login.json()
    token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res_login_email = client.post(
        "/api/auth/login",
        json={"username": "MASTER@empresa.com.br", "password": "MasterPass123"},
    )
    assert res_login_email.status_code == 200

    # 4. Consulta `/api/auth/me`
    assert client.get("/api/auth/me").status_code == 401
    res_me = client.get("/api/auth/me", headers=headers)
    assert res_me.status_code == 200
    assert res_me.json()["username"] == "admin_master"

    # 5. Criação de operador secundário via `/api/auth/users`
    res_create_op = client.post(
        "/api/auth/users",
        headers=headers,
        json={
            "username": "operador_01",
            "email": "op01@empresa.com.br",
            "full_name": "Operador Um",
            "password": "OpPassword123",
            "role": "operador",
        },
    )
    assert res_create_op.status_code == 200
    op_id = res_create_op.json()["id"]

    # Duplicidade de username ou e-mail deve retornar 400
    res_dup = client.post(
        "/api/auth/users",
        headers=headers,
        json={
            "username": "operador_01",
            "email": "outro@empresa.com.br",
            "password": "OpPassword123",
        },
    )
    assert res_dup.status_code == 400

    # 6. Operador comum não pode listar nem criar usuários (403 Forbidden)
    op_login = client.post(
        "/api/auth/login",
        json={"username": "operador_01", "password": "OpPassword123"},
    )
    op_headers = {"Authorization": f"Bearer {op_login.json()['access_token']}"}
    assert client.get("/api/auth/users", headers=op_headers).status_code == 403

    # 7. Alteração da própria senha pelo operador
    res_chg_bad = client.post(
        "/api/auth/change-password",
        headers=op_headers,
        json={"current_password": "errada", "new_password": "NovaOpPassword123"},
    )
    assert res_chg_bad.status_code == 400

    res_chg_ok = client.post(
        "/api/auth/change-password",
        headers=op_headers,
        json={"current_password": "OpPassword123", "new_password": "NovaOpPassword123"},
    )
    assert res_chg_ok.status_code == 200

    # 8. Listagem e exclusão de usuário pelo admin
    res_list = client.get("/api/auth/users", headers=headers)
    assert res_list.status_code == 200
    assert any(u["username"] == "operador_01" for u in res_list.json())

    # Admin não pode excluir a si mesmo
    res_self_del = client.delete(f"/api/auth/users/{admin.id}", headers=headers)
    assert res_self_del.status_code == 400

    # Admin exclui o operador secundário
    res_del = client.delete(f"/api/auth/users/{op_id}", headers=headers)
    assert res_del.status_code == 200


@pytest.mark.real_auth
def test_auth_public_registration_bootstrap_and_role():
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
    finally:
        db.close()

    # Sem usuários -> status informa has_users=False
    st = client.get("/api/auth/status").json()
    assert st["has_users"] is False

    # Primeiro cadastro público recebe role='admin' e já retorna token válido
    r1 = client.post(
        "/api/auth/register",
        json={
            "username": "primeiro_admin",
            "email": "primeiro@empresa.com.br",
            "full_name": "Primeiro Admin",
            "password": "SenhaForte123",
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["user"]["role"] == "admin"
    assert d1["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {d1['access_token']}"}).status_code == 200

    # Segundo cadastro público recebe role='operador'
    r2 = client.post(
        "/api/auth/register",
        json={
            "username": "segundo_operador",
            "email": "segundo@empresa.com.br",
            "password": "SenhaOp123",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["user"]["role"] == "operador"

    # Validações de duplicidade e senha curta
    assert client.post("/api/auth/register", json={"username": "segundo_operador", "password": "1234"}).status_code == 400
    assert client.post("/api/auth/register", json={"username": "terceiro_op", "password": "12"}).status_code == 400


# ==============================================================================
# 4. Monitoramento e Alertas de Vencimento de Certificados A1
# ==============================================================================


def test_certificate_expiration_alerts_and_dashboard_stats(tmp_path: Path):
    now = datetime.datetime.now(datetime.UTC)
    db = SessionLocal()
    try:
        # Limpa clientes anteriores (respeitando FKs com PRAGMA foreign_keys=ON)
        db.query(BatchImportItem).delete()
        db.query(BatchImport).delete()
        db.query(Invoice).delete()
        db.query(Customer).delete()
        db.query(ServiceItem).delete()
        db.query(Client).delete()
        db.commit()

        c_vencido = Client(
            cnpj="11111111000101",
            razao_social="Empresa Certificado Vencido LTDA",
            cert_valid_until=now - datetime.timedelta(days=5),
            cert_subject="CN=Empresa Vencida:11111111000101",
        )
        c_expirando = Client(
            cnpj="22222222000102",
            razao_social="Empresa Certificado Expirando LTDA",
            cert_valid_until=now + datetime.timedelta(days=12),
            cert_subject="CN=Empresa Expirando:22222222000102",
        )
        c_valido = Client(
            cnpj="33333333000103",
            razao_social="Empresa Certificado Valido LTDA",
            cert_valid_until=now + datetime.timedelta(days=180),
            cert_subject="CN=Empresa Valida:33333333000103",
        )
        db.add_all([c_vencido, c_expirando, c_valido])
        db.commit()
    finally:
        db.close()

    # 1. Endpoint `/api/clients/certificados/alertas`
    res_alerts = client.get("/api/clients/certificados/alertas?dias_aviso=30")
    assert res_alerts.status_code == 200
    data = res_alerts.json()
    assert data["total_monitorados"] == 3
    assert data["total_vencidos"] == 1
    assert data["total_expirando"] == 1
    assert data["vencidos"][0]["cnpj"] == "11111111000101"
    assert data["vencidos"][0]["status_certificado"] == "vencido"
    assert data["expirando"][0]["cnpj"] == "22222222000102"
    assert data["expirando"][0]["status_certificado"] == "expirando"
    assert data["validos"][0]["cnpj"] == "33333333000103"
    assert data["validos"][0]["status_certificado"] == "valido"

    # 2. Endpoint `/api/analytics/stats` deve refletir os contadores
    res_stats = client.get("/api/analytics/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["certificados_vencidos"] == 1
    assert stats["certificados_expirando"] == 1

    # 3. Testa `extrair_metadados_certificado_pfx` com mock de DpsSigner e arquivo temporário
    fake_pfx = tmp_path / "teste.pfx"
    fake_pfx.write_bytes(b"fake-pfx-bytes")

    mock_cert = MagicMock()
    mock_cert.not_valid_after_utc = now + datetime.timedelta(days=90)
    mock_cert.subject.rfc4514_string.return_value = "CN=Mock Cert:99999999000199"
    mock_signer = MagicMock()
    mock_signer.certificate = mock_cert

    with patch("app.api.routers.clients.DpsSigner", return_value=mock_signer):
        valid_dt, subj = extrair_metadados_certificado_pfx(str(fake_pfx), "1234")
        assert valid_dt is not None
        assert subj == "CN=Mock Cert:99999999000199"

    # Caminho inexistente retorna (None, None)
    assert extrair_metadados_certificado_pfx("/caminho/inexistente.pfx", "1234") == (None, None)


# ==============================================================================
# 5. Worker Agendado de Retransmissão da Fila de Contingência (`SchedulerService`)
# ==============================================================================


def test_scheduler_worker_status_and_trigger():
    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.status == "fila_contingencia").delete()
        db.commit()

        # Cria cliente com envio automático de e-mail habilitado e nota na fila_contingencia
        cli = Client(
            cnpj="44444444000104",
            razao_social="Prestador Worker Auto Email LTDA",
            email="contato@prestadorworker.com.br",
            smtp_host="smtp.prestadorworker.com.br",
            smtp_port=587,
            smtp_user="contato@prestadorworker.com.br",
            smtp_password="SmtpPass123",
            enviar_email_automatico=1,
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)

        inv = Invoice(
            client_id=cli.id,
            numero="DPS-999",
            chave="FILA-WORKER-999",
            id_dps="DPS" + "9" * 42,
            data_emissao=datetime.datetime.now(datetime.UTC),
            valor=1500.0,
            tomador_documento="55555555000105",
            tomador_nome="Tomador Worker Teste SA",
            tomador_email="financeiro@tomadorworker.com.br",
            status="fila_contingencia",
            tentativas_envio=1,
            ultimo_erro_envio="Timeout anterior na Sefin Nacional",
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)
        inv_id = inv.id
    finally:
        db.close()

    # 1. Consulta status do worker via GET `/api/adn/worker/status`
    res_status = client.get("/api/adn/worker/status")
    assert res_status.status_code == 200
    st = res_status.json()
    assert "enabled" in st
    assert "interval_seconds" in st

    # 2. Dispara ciclo manual via POST `/api/adn/worker/trigger` simulando autorização + envio de e-mail
    async def fake_reenviar(db, req):
        nota = db.query(Invoice).filter(Invoice.id == inv_id).first()
        nota.status = "gerada"
        nota.chave = "33045572244444444000104000000000099926110000000999"
        db.commit()
        return {
            "total_processadas": 1,
            "autorizadas": 1,
            "falhas": 0,
            "resultados": [{"invoice_id": inv_id, "sucesso": True, "status": "gerada"}],
        }

    with (
        patch.object(
            SchedulerService,
            "get_config",
            return_value={"enabled": True, "interval_seconds": 60, "max_tentativas": 10},
        ),
        patch(
            "app.services.scheduler_service.AdnService.reenviar_fila_contingencia",
            new=AsyncMock(side_effect=fake_reenviar),
        ),
        patch(
            "app.services.scheduler_service.EmailService.enviar_nfse_por_email", return_value={"sucesso": True}
        ) as mock_email,
    ):
        res_trig = client.post("/api/adn/worker/trigger")
        assert res_trig.status_code == 200
        trig_data = res_trig.json()
        assert trig_data["total_processadas"] == 1
        assert trig_data["autorizadas"] == 1
        assert trig_data["emails_enviados"] == 1
        mock_email.assert_called_once()

        # Novo disparo com fila vazia deve retornar 0 processadas
        res_empty = client.post("/api/adn/worker/trigger")
        assert res_empty.status_code == 200
        assert res_empty.json()["total_processadas"] == 0

    # 3. Testa ciclo de vida start/stop assíncrono do SchedulerService
    async def _run_start_stop():
        SchedulerService.start()
        assert SchedulerService._task is not None
        await asyncio.sleep(0.05)
        await SchedulerService.stop()
        assert SchedulerService._task is None

    asyncio.run(_run_start_stop())


def test_alphanumeric_cnpj_lookup_and_emission_catalogs():
    # 1. Normalização e consulta de CNPJ alfanumérico (14 caracteres)
    assert _clean_cnpj("12.abc.456/0001-99") == "12ABC456000199"
    assert client.get("/api/lookup/cnpj/12345").status_code == 400

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "razao_social": "EMPRESA ALFANUMERICA DEMO LTDA",
        "email": "fiscal@demo.com.br",
        "cep": "29140000",
        "logradouro": "AV CENTRAL",
        "numero": "100",
        "bairro": "CENTRO",
        "municipio": "CARIACICA",
        "uf": "ES",
        "codigo_municipio_ibge": "3201308",
        "opcao_pelo_simples": True,
    }
    mock_http_client = MagicMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.get = AsyncMock(return_value=fake_resp)

    with patch("app.services.lookup_service.httpx.AsyncClient", return_value=mock_http_client):
        res_lk = client.get("/api/lookup/cnpj/12.abc.456/0001-99")
    assert res_lk.status_code == 200
    assert res_lk.json()["cnpj"] == "12ABC456000199"
    assert res_lk.json()["razao_social"] == "EMPRESA ALFANUMERICA DEMO LTDA"

    # 2. Completude dos catálogos usados na tela de emissão
    srvs = client.get("/api/catalogs/servicos?limite=500").json()
    assert len(srvs) == 338
    assert any(s["cTribNac"] == "040101" for s in srvs)  # Medicina presente além de TI

    cclass_nfse = client.get("/api/catalogs/cclasstrib?apenas_nfse=true").json()
    assert len(cclass_nfse) == 66

    indops = client.get("/api/catalogs/indop").json()
    assert len(indops) == 28

    corrs = client.get("/api/catalogs/correlacoes?limite=2000").json()
    assert len(corrs) == 1739
    assert len({c["cNBS"] for c in corrs if c.get("cNBS")}) == 676

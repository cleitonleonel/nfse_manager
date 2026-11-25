"""Testes de isolamento multiempresa (`User` <-> `Client`), auditoria de emissão e filtros de contingência."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.migrations import create_admin_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import BatchImport, Customer, Invoice, ServiceItem, User, UserClient


client = TestClient(app)


def _reset_all() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(UserClient).delete()
        db.query(Invoice).update({Invoice.created_by_user_id: None}, synchronize_session=False)
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


def _login_headers(username: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.real_auth
def test_user_client_isolation_and_anti_idor(tmp_path: Path, monkeypatch):
    """Garante que operadores só acessam/emitem/baixam dados das empresas vinculadas a eles."""
    _reset_all()
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(tmp_path / "dl"))

    create_admin_user("iso_admin", "iso_admin@empresa.com", "AdminPass1!", "Admin Isolamento")
    admin_headers = _login_headers("iso_admin", "AdminPass1!")

    # Cria duas empresas como Admin
    r_a = client.post(
        "/api/clients",
        headers=admin_headers,
        data={"cnpj": "11111111000191", "razao_social": "Empresa A LTDA", "ambiente_padrao": "homologacao"},
    )
    assert r_a.status_code == 200, r_a.text
    cli_a_id = r_a.json()["id"]

    r_b = client.post(
        "/api/clients",
        headers=admin_headers,
        data={"cnpj": "22222222000191", "razao_social": "Empresa B LTDA", "ambiente_padrao": "homologacao"},
    )
    assert r_b.status_code == 200, r_b.text
    cli_b_id = r_b.json()["id"]

    # Admin cria Operador 1 vinculado apenas à Empresa A e Operador 2 sem vínculos
    r_op1 = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "op_isolado_1",
            "email": "op1@empresa.com",
            "password": "OpPass123!",
            "role": "operador",
            "client_ids": [cli_a_id],
        },
    )
    assert r_op1.status_code == 200, r_op1.text
    assert r_op1.json()["client_ids"] == [cli_a_id]
    op1_id = r_op1.json()["id"]

    r_op2 = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "op_isolado_2",
            "email": "op2@empresa.com",
            "password": "OpPass123!",
            "role": "operador",
        },
    )
    assert r_op2.status_code == 200, r_op2.text
    assert r_op2.json()["client_ids"] == []

    op1_headers = _login_headers("op_isolado_1", "OpPass123!")
    op2_headers = _login_headers("op_isolado_2", "OpPass123!")

    # Cria notas, tomadores, serviços e lote para A e B diretamente no banco
    xml_b_rel = "adn/nfse/B_PRIVADO.xml"
    xml_b_full = Path(str(tmp_path / "dl")) / xml_b_rel
    xml_b_full.parent.mkdir(parents=True, exist_ok=True)
    xml_b_full.write_text("<NFSe/>", encoding="utf-8")

    db = SessionLocal()
    try:
        inv_a = Invoice(
            client_id=cli_a_id,
            numero="10",
            chave="32013082111111110001910090000000000000000000000010",
            status="gerada",
            tipo="emitidas",
            valor=1500.0,
            data_emissao=datetime.datetime.now(datetime.UTC),
        )
        inv_b = Invoice(
            client_id=cli_b_id,
            numero="20",
            chave="32013082222222220001910090000000000000000000000020",
            status="fila_contingencia",
            tipo="emitidas",
            valor=2500.0,
            xml_path=xml_b_rel,
            data_emissao=datetime.datetime.now(datetime.UTC),
        )
        inv_b_ok = Invoice(
            client_id=cli_b_id,
            numero="21",
            chave="32013082222222220001910090000000000000000000000021",
            status="gerada",
            tipo="emitidas",
            valor=3000.0,
            data_emissao=datetime.datetime.now(datetime.UTC),
        )
        cust_b = Customer(client_id=cli_b_id, documento="15459431000198", razao_social="Tomador B")
        srv_b = ServiceItem(client_id=cli_b_id, titulo="Servico B", descricao="Desc B", valor_unitario=500.0)
        batch_b = BatchImport(client_id=cli_b_id, filename="b.csv", file_hash="hash_b", total_items=1)
        db.add_all([inv_a, inv_b, inv_b_ok, cust_b, srv_b, batch_b])
        db.commit()
        db.refresh(inv_b)
        db.refresh(cust_b)
        db.refresh(srv_b)
        db.refresh(batch_b)
        inv_b_id, cust_b_id, srv_b_id, batch_b_id = inv_b.id, cust_b.id, srv_b.id, batch_b.id
    finally:
        db.close()

    # 1. Operador 2 (sem empresas) não vê nada
    assert client.get("/api/clients", headers=op2_headers).json() == []
    assert client.get("/api/invoices", headers=op2_headers).json() == []
    assert client.get("/api/adn/fila", headers=op2_headers).json() == []
    assert client.get("/api/batch-emission", headers=op2_headers).json() == []
    stats_op2 = client.get("/api/analytics/stats", headers=op2_headers).json()
    assert stats_op2["total_clientes"] == 0
    assert stats_op2["valor_emitidas"] == 0.0

    # 2. Operador 1 vê apenas Empresa A em listagens, stats, ranking, relatórios
    op1_clients = client.get("/api/clients", headers=op1_headers).json()
    assert [c["id"] for c in op1_clients] == [cli_a_id]
    op1_invs = client.get("/api/invoices", headers=op1_headers).json()
    assert all(i["client_id"] == cli_a_id for i in op1_invs)
    stats_op1 = client.get("/api/analytics/stats", headers=op1_headers).json()
    assert stats_op1["total_clientes"] == 1
    assert stats_op1["valor_emitidas"] == 1500.0

    # 3. Bloqueios anti-IDOR para Operador 1 tentando acessar Empresa B ou recursos dela
    forbidden_calls = [
        ("PUT", f"/api/clients/{cli_b_id}", {"data": {"razao_social": "Hack"}}),
        ("DELETE", f"/api/clients/{cli_b_id}", {}),
        ("DELETE", f"/api/clients/{cli_a_id}", {}),  # apenas admin ou manager criador exclui
        ("GET", f"/api/invoices?client_id={cli_b_id}", {}),
        ("GET", f"/api/analytics/stats?client_id={cli_b_id}", {}),
        ("GET", f"/api/analytics/chart?client_id={cli_b_id}", {}),
        ("GET", f"/api/reports/export?format=json&client_id={cli_b_id}", {}),
        ("GET", f"/api/reports/competencia?client_id={cli_b_id}", {}),
        ("GET", f"/api/adn/fila?client_id={cli_b_id}", {}),
        ("POST", "/api/adn/fila/reenviar", {"json": {"client_id": cli_b_id}}),
        ("POST", "/api/adn/fila/reenviar", {"json": {"invoice_ids": [inv_b_id]}}),
        ("DELETE", f"/api/adn/fila/{inv_b_id}", {}),
        ("POST", f"/api/adn/nfse/{inv_b_id}/enviar-email", {"json": {"destinatario": "a@b.com"}}),
        ("POST", "/api/adn/cofre/sincronizar", {"json": {"client_id": cli_b_id}}),
        ("POST", "/api/adn/dps/preview", {"json": {"client_id": cli_b_id}}),
        ("POST", "/api/adn/dps/emitir", {"json": {"client_id": cli_b_id, "transmitir": False}}),
        ("POST", "/api/adn/dps/emitir", {"json": {"prestador": {"cnpj": "22222222000191"}, "transmitir": False}}),
        ("GET", f"/api/customers?client_id={cli_b_id}", {}),
        ("PUT", f"/api/customers/{cust_b_id}", {"json": {"razao_social": "Hack"}}),
        ("DELETE", f"/api/customers/{cust_b_id}", {}),
        ("GET", f"/api/service-items?client_id={cli_b_id}", {}),
        ("PUT", f"/api/service-items/{srv_b_id}", {"json": {"titulo": "Hack"}}),
        ("DELETE", f"/api/service-items/{srv_b_id}", {}),
        ("GET", f"/api/batch-emission?client_id={cli_b_id}", {}),
        ("GET", f"/api/batch-emission/{batch_b_id}", {}),
        ("DELETE", f"/api/batch-emission/{batch_b_id}", {}),
        ("GET", f"/api/download/file?path={xml_b_rel}", {}),
        ("POST", "/api/download/batch", {"json": {"arquivos": [xml_b_rel]}}),
        ("POST", "/api/download/sync-portal", {"json": {"client_id": cli_b_id, "invoice_ids": [inv_b_id], "action_type": "emitidas"}}),
    ]
    for method, url, kwargs in forbidden_calls:
        resp = client.request(method, url, headers=op1_headers, **kwargs)
        assert resp.status_code == 403, f"Esperado 403 em {method} {url}, obtido {resp.status_code}: {resp.text}"

    # 4. Operador 1 emite DPS em homologação para Empresa A -> grava created_by e ambiente, e NÃO infla Dashboard
    emit_payload = {
        "client_id": cli_a_id,
        "ambiente": "homologacao",
        "transmitir": True,  # sem certificado -> fila_contingencia
        "tomador": {"documento": "15459431000198", "razao_social": "SERTAO COMERCIAL LTDA"},
        "servico": {"cTribNac": "010101", "descricao": "Dev Customizado", "valor": 1000.0, "aliquota_iss": 5.0},
    }
    r_emit = client.post("/api/adn/dps/emitir", headers=op1_headers, json=emit_payload)
    assert r_emit.status_code == 200, r_emit.text
    emit_data = r_emit.json()
    assert emit_data["status_nota"] == "fila_contingencia"

    invs_a = client.get(f"/api/invoices?client_id={cli_a_id}", headers=op1_headers).json()
    created_inv = next(i for i in invs_a if i["id"] == emit_data["invoice_id"])
    assert created_inv["created_by_user_id"] == op1_id
    assert created_inv["created_by_username"] == "op_isolado_1"
    assert created_inv["ambiente"] == "homologacao"

    # Dashboard NÃO soma fila_contingencia (deve continuar R$ 1500,00 da inv_a gerada)
    stats_after = client.get(f"/api/analytics/stats?client_id={cli_a_id}", headers=op1_headers).json()
    assert stats_after["valor_emitidas"] == 1500.0
    assert stats_after["total_emitidas"] == 1

    # 5. Admin atualiza vínculos de Operador 1 via PATCH /api/auth/users/{id}
    r_patch = client.patch(
        f"/api/auth/users/{op1_id}",
        headers=admin_headers,
        json={"client_ids": [cli_a_id, cli_b_id]},
    )
    assert r_patch.status_code == 200, r_patch.text
    assert sorted(r_patch.json()["client_ids"]) == sorted([cli_a_id, cli_b_id])
    assert len(client.get("/api/clients", headers=op1_headers).json()) == 2


@pytest.mark.real_auth
def test_operator_self_service_client_creation_and_flag(monkeypatch):
    """Operador que cria empresa fica vinculado como gestor só dela; flag =0 bloqueia criação."""
    _reset_all()
    create_admin_user("adm_ss", "adm_ss@empresa.com", "AdminPass1!", "Admin SS")
    admin_headers = _login_headers("adm_ss", "AdminPass1!")

    r_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"username": "op_creator", "password": "OpPass123!", "role": "operador"},
    )
    assert r_op.status_code == 200
    op_headers = _login_headers("op_creator", "OpPass123!")

    # Com NFSE_ALLOW_OPERATOR_CREATE_CLIENT=1 (padrão), operador cria Empresa C e vira manager dela
    monkeypatch.setenv("NFSE_ALLOW_OPERATOR_CREATE_CLIENT", "1")
    r_c = client.post(
        "/api/clients",
        headers=op_headers,
        data={"cnpj": "33333333000191", "razao_social": "Minha Empresa Propria LTDA"},
    )
    assert r_c.status_code == 200, r_c.text
    cli_c_id = r_c.json()["id"]

    op_clients = client.get("/api/clients", headers=op_headers).json()
    assert [c["id"] for c in op_clients] == [cli_c_id]

    # Como criador (manager), pode editar e excluir a própria empresa
    assert client.put(f"/api/clients/{cli_c_id}", headers=op_headers, data={"razao_social": "Minha Empresa Editada"}).status_code == 200
    assert client.delete(f"/api/clients/{cli_c_id}", headers=op_headers).status_code == 200

    # Com NFSE_ALLOW_OPERATOR_CREATE_CLIENT=0, operador não cria novas empresas
    monkeypatch.setenv("NFSE_ALLOW_OPERATOR_CREATE_CLIENT", "0")
    r_blocked = client.post(
        "/api/clients",
        headers=op_headers,
        data={"cnpj": "44444444000191", "razao_social": "Bloqueada LTDA"},
    )
    assert r_blocked.status_code == 403


def test_frontend_views_help_users_and_about_served():
    """Garante que as novas views SPA (`users.html`, `help.html`) e `about.html` são servidas corretamente."""
    r_users = client.get("/views/users.html")
    assert r_users.status_code == 200
    assert "admin-users-section" in r_users.text
    assert "admin-audit-section" in r_users.text

    r_help = client.get("/views/help.html")
    assert r_help.status_code == 200
    assert "sup-email" in r_help.text
    assert "Guia Rápido" in r_help.text

    r_about = client.get("/views/about.html")
    assert r_about.status_code == 200
    assert "admin-users-section" not in r_about.text
    assert "sup-email" not in r_about.text


def test_background_sync_marks_failed_when_all_clients_fail(monkeypatch):
    """Garante que background_sync marque status='failed' se todas as empresas falharem."""
    from app.api.routers import invoices as inv_router
    from app.api.state import TaskStore
    from app.models import Client

    db = SessionLocal()
    try:
        cli = Client(
            cnpj="77665544000133",
            razao_social="Empresa Sync Falha",
            username="77665544000133",
            password="123",
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)
        cli_id = cli.id
    finally:
        db.close()

    class FailingPortalClient:
        def autenticar(self):
            raise RuntimeError("Portal indisponível no teste")

    monkeypatch.setattr(inv_router, "get_nfse_client", lambda _c: FailingPortalClient())
    sync_id = "sync_test_all_fail"
    inv_router.background_sync(
        sync_id,
        cli_id,
        "01/01/2026",
        "31/01/2026",
        "emitidas",
        allowed_client_ids=None,
        created_by=None,
    )
    task = TaskStore.get_task(sync_id)
    assert task is not None
    assert task["status"] == "failed"
    assert "falhou para todas as empresas" in task["message"]


@pytest.mark.real_auth
def test_operator_batch_zip_conversion_guards_and_client_delete_with_batches(tmp_path: Path, monkeypatch):
    """Valida ZIP em lote para operador, bloqueio de gravação/IDOR em conversões e exclusão de cliente com lotes."""
    from app.models import BatchImportItem

    _reset_all()
    dl_dir = tmp_path / "dl"
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(dl_dir))

    create_admin_user("adm_dl", "adm_dl@empresa.com", "AdminPass1!", "Admin DL")
    admin_headers = _login_headers("adm_dl", "AdminPass1!")

    r_a = client.post(
        "/api/clients",
        headers=admin_headers,
        data={"cnpj": "55555555000191", "razao_social": "Emp A DL LTDA"},
    )
    r_b = client.post(
        "/api/clients",
        headers=admin_headers,
        data={"cnpj": "66666666000191", "razao_social": "Emp B DL LTDA"},
    )
    cli_a_id = r_a.json()["id"]
    cli_b_id = r_b.json()["id"]

    r_op = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={"username": "op_dl", "password": "OpPass123!", "role": "operador", "client_ids": [cli_a_id]},
    )
    assert r_op.status_code == 200
    op_headers = _login_headers("op_dl", "OpPass123!")

    xml_a_rel = "adn/nfse/A_OK.xml"
    xml_a_full = dl_dir / xml_a_rel
    xml_a_full.parent.mkdir(parents=True, exist_ok=True)
    xml_a_full.write_text("<NFSe/>", encoding="utf-8")

    chave_b = "32013082666666660001910090000000000000000000000099"
    db = SessionLocal()
    try:
        inv_a = Invoice(
            client_id=cli_a_id,
            numero="1",
            chave="32013082555555550001910090000000000000000000000001",
            status="gerada",
            tipo="emitidas",
            valor=100.0,
            xml_path=xml_a_rel,
            data_emissao=datetime.datetime.now(datetime.UTC),
        )
        inv_b = Invoice(
            client_id=cli_b_id,
            numero="99",
            chave=chave_b,
            status="gerada",
            tipo="emitidas",
            valor=200.0,
            data_emissao=datetime.datetime.now(datetime.UTC),
        )
        db.add_all([inv_a, inv_b])
        db.commit()
        db.refresh(inv_a)

        batch_b = BatchImport(client_id=cli_b_id, filename="lote_b.csv", file_hash="h_b", total_items=1)
        db.add(batch_b)
        db.commit()
        db.refresh(batch_b)

        item_b = BatchImportItem(
            batch_id=batch_b.id,
            row_number=1,
            payload_json="{}",
            invoice_id=inv_b.id,
        )
        db.add(item_b)
        db.commit()
    finally:
        db.close()

    # 1. Operador gera ZIP de arquivo da própria empresa A e consegue baixá-lo via /api/download/file
    r_batch = client.post("/api/download/batch", headers=op_headers, json={"arquivos": [xml_a_rel]})
    assert r_batch.status_code == 200, r_batch.text
    zip_path = r_batch.json()["zip_path"]
    r_file = client.get("/api/download/file", headers=op_headers, params={"path": zip_path})
    assert r_file.status_code == 200, r_file.text

    # 2. Bloqueio de path traversal / escrita arbitrária em /html-to-xml e /xml-to-pdf
    r_bad_out1 = client.post(
        "/api/download/html-to-xml",
        headers=op_headers,
        json={"html_content": "<html></html>", "xml_output_path": "/tmp/hacked.xml"},
    )
    assert r_bad_out1.status_code == 403

    r_bad_out2 = client.post(
        "/api/download/xml-to-pdf",
        headers=op_headers,
        json={"xml_content": f'<NFSe><infNFSe Id="NFS{chave_b}"/></NFSe>', "pdf_output_path": "../hack.pdf"},
    )
    assert r_bad_out2.status_code in (400, 403)

    # 3. Bloqueio IDOR quando XML em xml-to-pdf ou HTML em html-to-xml traz chave pertencente a outra empresa (B) sem efeito colateral em disco
    r_idor_pdf = client.post(
        "/api/download/xml-to-pdf",
        headers=op_headers,
        json={
            "xml_content": (
                f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS{chave_b}">'
                "<nNFSe>99</nNFSe></infNFSe></NFSe>"
            )
        },
    )
    assert r_idor_pdf.status_code == 403

    from tests.test_html_to_xml_and_pdf import SAMPLE_HTML_IMPRESSAO

    html_b = SAMPLE_HTML_IMPRESSAO.replace(
        "32013081219495981000113000000000086326010205340809",
        chave_b,
    )
    r_idor_html = client.post(
        "/api/download/html-to-xml",
        headers=op_headers,
        json={"html_content": html_b},
    )
    assert r_idor_html.status_code == 403
    assert not (dl_dir / "converted" / "xmls" / f"{chave_b}.xml").exists()
    assert not (dl_dir / "converted" / "pdfs" / f"{chave_b}.pdf").exists()

    # 4. Admin exclui Empresa B que possui BatchImport + BatchImportItem apontando para Invoice sem IntegrityError
    r_del_b = client.delete(f"/api/clients/{cli_b_id}", headers=admin_headers)
    assert r_del_b.status_code == 200, r_del_b.text

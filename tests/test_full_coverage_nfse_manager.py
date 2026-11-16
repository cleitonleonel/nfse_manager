"""Testes abrangentes para elevar a cobertura do nfse_manager para ~100% em todos os módulos."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api.deps import ClienteNfsePortalWrapper, get_nfse_client, has_valid_certificate
from app.api.routers import downloads, invoices, system
from app.api.state import tasks_status
from app.database import SessionLocal
from app.main import app
from app.models import Client, Invoice, init_db
from app.services.email_service import EmailService
from app.services.lookup_service import LookupService, _CEP_CACHE, _CNPJ_CACHE
from app.version import _read_pyproject_version


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    init_db()
    return TestClient(app)


# ==============================================================================
# 1. LOOKUP SERVICE (CEP: ViaCEP + BrasilAPI fallback; CNPJ: BrasilAPI + ReceitaWS fallback)
# ==============================================================================


@pytest.mark.anyio
async def test_lookup_service_cep_and_cnpj_all_providers_and_cache():
    _CEP_CACHE.clear()
    _CNPJ_CACHE.clear()

    # CEP inválido
    with pytest.raises(HTTPException) as exc_cep:
        await LookupService.consultar_cep("123")
    assert exc_cep.value.status_code == 400

    # CNPJ inválido
    with pytest.raises(HTTPException) as exc_cnpj:
        await LookupService.consultar_cnpj("12345")
    assert exc_cnpj.value.status_code == 400

    # 1. ViaCEP sucesso + hit no cache
    mock_resp_viacep = MagicMock()
    mock_resp_viacep.status_code = 200
    mock_resp_viacep.json.return_value = {
        "cep": "29140-000",
        "logradouro": "Av Central",
        "complemento": "Sala 1",
        "bairro": "Centro",
        "localidade": "Cariacica",
        "uf": "ES",
        "ibge": "3201308",
    }
    with patch("app.services.lookup_service.httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_viacep
        res1 = await LookupService.consultar_cep("29140-000")
        assert res1["codigo_municipio"] == "3201308"
        # Segunda chamada vem do cache sem chamar httpx
        res2 = await LookupService.consultar_cep("29140000")
        assert res2["municipio"] == "Cariacica"
        assert mock_get.call_count == 1

    # 2. ViaCEP retorna {"erro": True} -> fallback para BrasilAPI CEP v2
    resp_viacep_erro = MagicMock(status_code=200)
    resp_viacep_erro.json.return_value = {"erro": True}
    resp_brasilapi_cep = MagicMock(status_code=200)
    resp_brasilapi_cep.json.return_value = {
        "street": "Rua Fallback",
        "neighborhood": "Bairro Fallback",
        "city": "Vitoria",
        "state": "ES",
    }
    with patch(
        "app.services.lookup_service.httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=[resp_viacep_erro, resp_brasilapi_cep],
    ):
        res_fb = await LookupService.consultar_cep("29000-000")
        assert res_fb["logradouro"] == "Rua Fallback"
        assert res_fb["uf"] == "ES"

    # 3. Ambos falham -> 404
    with patch(
        "app.services.lookup_service.httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network error"),
    ):
        with pytest.raises(HTTPException) as exc_404:
            await LookupService.consultar_cep("99999999")
        assert exc_404.value.status_code == 404

    # 4. CNPJ BrasilAPI (MEI / Simples + cache)
    resp_cnpj_bapi = MagicMock(status_code=200)
    resp_cnpj_bapi.json.return_value = {
        "razao_social": "EMPRESA BRASILAPI LTDA",
        "nome_fantasia": "FANTASIA",
        "email": "CONTATO@EMPRESA.COM",
        "ddd_telefone_1": "2733334444",
        "cep": "29140000",
        "logradouro": "RUA A",
        "numero": "10",
        "complemento": "",
        "bairro": "CENTRO",
        "municipio": "CARIACICA",
        "uf": "ES",
        "codigo_municipio_ibge": 3201308,
        "opcao_pelo_mei": False,
        "opcao_pelo_simples": True,
        "cnae_fiscal": 6201501,
        "cnae_fiscal_descricao": "Desenvolvimento de software",
    }
    with patch("app.services.lookup_service.httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get_cnpj:
        mock_get_cnpj.return_value = resp_cnpj_bapi
        c1 = await LookupService.consultar_cnpj("19.495.981/0001-13")
        assert c1["regime_tributario"] == "simples"
        assert c1["codigo_municipio"] == "3201308"
        # Cache hit
        c2 = await LookupService.consultar_cnpj("19495981000113")
        assert c2["razao_social"] == "EMPRESA BRASILAPI LTDA"
        assert mock_get_cnpj.call_count == 1

    # 5. CNPJ Fallback ReceitaWS (com MEI = True)
    resp_bapi_fail = MagicMock(status_code=500)
    resp_receitaws = MagicMock(status_code=200)
    resp_receitaws.json.return_value = {
        "status": "OK",
        "nome": "MEI RECEITAWS",
        "fantasia": "MEI",
        "email": "mei@teste.com",
        "telefone": "(27) 99999-0000",
        "cep": "29.140-000",
        "logradouro": "RUA B",
        "numero": "20",
        "complemento": "",
        "bairro": "CENTRO",
        "municipio": "CARIACICA",
        "uf": "ES",
        "simples": {"optante": True},
        "simei": {"optante": True},
    }
    with patch(
        "app.services.lookup_service.httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=[resp_bapi_fail, resp_receitaws],
    ):
        c_fb = await LookupService.consultar_cnpj("11.222.333/0001-44")
        assert c_fb["regime_tributario"] == "mei"
        assert c_fb["codigo_municipio"] == "3201308"  # resolvido via cache de CEP 29140000!

    # 6. CNPJ não encontrado em nenhum provedor -> 404
    with patch(
        "app.services.lookup_service.httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=RuntimeError("offline"),
    ):
        with pytest.raises(HTTPException) as exc_cnpj_404:
            await LookupService.consultar_cnpj("88.888.888/0001-88")
        assert exc_cnpj_404.value.status_code == 404


# ==============================================================================
# 2. REGISTRY ROUTER (GET/PUT/DELETE /api/customers e /api/service-items + 404/400)
# ==============================================================================


def test_registry_router_full_crud_and_filters(api_client: TestClient):
    # Documento inválido -> 400
    r_bad = api_client.post("/api/customers", json={"documento": "123", "razao_social": "Invalido"})
    assert r_bad.status_code == 400

    # Criar, listar com filtro q, atualizar e remover Customer
    r_c = api_client.post(
        "/api/customers",
        json={
            "documento": "12345678901",
            "razao_social": "PESSOA FISICA TOMADORA",
            "email": "pf@tomador.com",
            "codigo_municipio": "3201308",
            "uf": "ES",
        },
    )
    assert r_c.status_code == 200
    cid = r_c.json()["id"]

    r_list = api_client.get("/api/customers", params={"client_id": 1, "q": "PESSOA FISICA"})
    assert r_list.status_code == 200
    assert any(x["id"] == cid for x in r_list.json())

    r_put = api_client.put(
        f"/api/customers/{cid}",
        json={"documento": "123.456.789-01", "cep": "29140-000", "codigo_municipio": "3201308"},
    )
    assert r_put.status_code == 200
    assert r_put.json()["cep"] == "29140000"

    assert api_client.put("/api/customers/999999", json={"razao_social": "X"}).status_code == 404
    assert api_client.delete("/api/customers/999999").status_code == 404
    assert api_client.delete(f"/api/customers/{cid}").status_code == 200

    # Criar, listar com filtro q, atualizar e remover ServiceItem
    r_s = api_client.post(
        "/api/service-items",
        json={
            "titulo": "Servico Teste Cobertura",
            "descricao": "Descricao completa do servico",
            "valor_unitario": 500.0,
            "c_trib_nac": "010101",
            "iss_retido": True,
            "reter_federais": True,
        },
    )
    assert r_s.status_code == 200
    sid = r_s.json()["id"]

    r_s_list = api_client.get("/api/service-items", params={"client_id": 1, "q": "Cobertura"})
    assert r_s_list.status_code == 200
    assert any(x["id"] == sid for x in r_s_list.json())

    r_s_put = api_client.put(
        f"/api/service-items/{sid}",
        json={"titulo": "Servico Atualizado", "iss_retido": False, "reter_federais": False},
    )
    assert r_s_put.status_code == 200
    assert r_s_put.json()["titulo"] == "Servico Atualizado"

    assert api_client.put("/api/service-items/999999", json={"titulo": "X"}).status_code == 404
    assert api_client.delete("/api/service-items/999999").status_code == 404
    assert api_client.delete(f"/api/service-items/{sid}").status_code == 200


# ==============================================================================
# 3. REPORTS (CSV, XLSX, JSON e formato inválido), ANALYTICS (enrich-xml) & CLIENTS (GET)
# ==============================================================================


def test_reports_csv_xlsx_json_and_analytics_enrich_and_clients_list(api_client: TestClient, tmp_path: Path):
    r_clients = api_client.get("/api/clients")
    assert r_clients.status_code == 200

    # Export JSON, CSV, XLSX e formato inválido
    assert api_client.get("/api/reports/export", params={"format": "json", "period": "30d"}).status_code == 200
    r_csv = api_client.get("/api/reports/export", params={"format": "csv", "period": "30d", "client_id": 1})
    assert r_csv.status_code == 200
    assert "RESUMO FINANCEIRO" in r_csv.text

    r_xlsx = api_client.get("/api/reports/export", params={"format": "xlsx", "period": "30d"})
    assert r_xlsx.status_code == 200
    assert len(r_xlsx.content) > 100

    r_invalid = api_client.get("/api/reports/export", params={"format": "pdf"})
    assert r_invalid.status_code == 400

    # Analytics: chart, ranking e enrich-xml
    assert api_client.get("/api/analytics/chart", params={"period": "7d", "client_id": 1}).status_code == 200
    assert api_client.get("/api/analytics/ranking", params={"period": "30d"}).status_code == 200

    xml_sample = tmp_path / "nota_enrich.xml"
    xml_sample.write_text(
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        '<infNFSe Id="NFS32013082212345678000113202604000000000077710999999">'
        "<nNFSe>777</nNFSe><dhProc>2026-04-10T10:00:00-03:00</dhProc>"
        "<valores><vLiq>950.00</vLiq></valores>"
        "</infNFSe></NFSe>",
        encoding="utf-8",
    )
    db = SessionLocal()
    try:
        inv = Invoice(
            numero="",
            chave="32013082212345678000113202604000000000077710999999",
            status="gerada",
            tipo="emitidas",
            valor=0.0,
            xml_path=str(xml_sample),
        )
        db.add(inv)
        db.commit()
    finally:
        db.close()

    r_enrich = api_client.post("/api/analytics/enrich-xml")
    assert r_enrich.status_code == 200
    assert r_enrich.json()["updated"] >= 1


# ==============================================================================
# 4. INVOICES ROUTER (background_sync, /api/sync, /api/tasks, /api/invoices filters)
# ==============================================================================


def test_invoices_sync_tasks_and_date_filters(api_client: TestClient):
    # 1. Trigger /api/sync
    with patch("app.api.routers.invoices.background_sync") as mock_bg:
        r_sync = api_client.post(
            "/api/sync",
            json={"client_id": 1, "data_inicio": "01/01/2026", "data_fim": "31/01/2026", "tipo": "emitidas"},
        )
        assert r_sync.status_code == 200
        assert "task_id" in r_sync.json()
        assert mock_bg.called

    # 2. Task status 404 e 200
    assert api_client.get("/api/tasks/inexistente").status_code == 404
    tasks_status["sync_test_1"] = {"status": "completed", "progress": 100}
    r_task = api_client.get("/api/tasks/sync_test_1")
    assert r_task.status_code == 200
    assert r_task.json()["status"] == "completed"

    # 3. Listagem de invoices com filtros de data válidos e inválidos
    r_inv_ok = api_client.get(
        "/api/invoices",
        params={"client_id": 1, "tipo": "emitidas", "data_inicio": "01/01/2026", "data_fim": "31/12/2026"},
    )
    assert r_inv_ok.status_code == 200

    r_inv_bad_date = api_client.get(
        "/api/invoices",
        params={"data_inicio": "data-invalida", "data_fim": "outra-invalida"},
    )
    assert r_inv_bad_date.status_code == 200

    # 4. Execução direta do background_sync (sem clientes e com cliente mockado)
    invoices.background_sync("sync_none", 999999, "01/01/2026", "31/01/2026", "emitidas")
    assert tasks_status["sync_none"]["status"] == "failed"

    db = SessionLocal()
    try:
        cli = db.query(Client).first()
        cid = cli.id
    finally:
        db.close()

    mock_nfse = MagicMock()
    mock_nfse.listar_notas_emitidas.return_value = {
        "notas": [
            {
                "download_xml": "https://www.nfse.gov.br/Notas/Download/NFSe/32013082212345678000113202604000000000088810999999",
                "download_danfs-e": "https://www.nfse.gov.br/Notas/Download/DANFSe/32013082212345678000113202604000000000088810999999",
                "valor": "R$ 1.234,56",
                "data_emissao": "15/04/2026",
                "numero": "888",
                "status_danfs-e": "gerada",
            }
        ]
    }
    with patch("app.api.routers.invoices.get_nfse_client", return_value=mock_nfse):
        invoices.background_sync("sync_ok", cid, "01/04/2026", "30/04/2026", "emitidas")
        assert tasks_status["sync_ok"]["status"] == "completed"
        # Segunda execução exercita o branch de atualização de nota já existente
        invoices.background_sync("sync_ok_2", cid, "01/04/2026", "30/04/2026", "emitidas")
        assert tasks_status["sync_ok_2"]["status"] == "completed"


# ==============================================================================
# 5. DOWNLOADS ROUTER (batch ZIP, background_download, sync-portal) & DEPS
# ==============================================================================


def test_downloads_batch_zip_and_background_download(api_client: TestClient, tmp_path: Path):
    # Batch vazio -> 400; Batch com arquivos inexistentes -> 404
    assert api_client.post("/api/download/batch", json={"arquivos": []}).status_code == 400
    assert api_client.post("/api/download/batch", json={"arquivos": ["/nao/existe/x.xml"]}).status_code == 404

    # Batch com arquivo real -> cria ZIP
    dummy_xml = tmp_path / "teste_lote.xml"
    dummy_xml.write_text("<NFSe/>", encoding="utf-8")
    r_zip = api_client.post("/api/download/batch", json={"arquivos": [str(dummy_xml)]})
    assert r_zip.status_code == 200
    assert r_zip.json()["zip_path"].endswith(".zip")

    # /api/download/sync-portal
    with patch("app.api.routers.downloads.background_download") as mock_dl:
        r_sp = api_client.post(
            "/api/download/sync-portal",
            json={"client_id": 1, "invoice_ids": [1], "action_type": "emitidas"},
        )
        assert r_sp.status_code == 200
        assert "task_id" in r_sp.json()
        assert mock_dl.called

    # background_download sem notas -> failed
    downloads.background_download("dl_empty", [9999999], 1, "emitidas")
    assert tasks_status["dl_empty"]["status"] == "failed"

    # background_download com nota e cliente certificado
    db = SessionLocal()
    try:
        cli = db.query(Client).first()
        inv = db.query(Invoice).filter(Invoice.client_id == cli.id).first()
        if not inv:
            inv = Invoice(
                client_id=cli.id,
                numero="1",
                chave="1" * 50,
                status="gerada",
                tipo="emitidas",
                download_url_xml="https://example.com/1.xml",
                download_url_pdf="https://example.com/1.pdf",
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)
        inv_id = inv.id
        cli_id = cli.id
    finally:
        db.close()

    mock_nfse_cert = MagicMock()
    mock_nfse_cert.usa_apenas_credenciais.return_value = False
    mock_nfse_cert.baixar_xml.return_value = str(dummy_xml)
    mock_nfse_cert.baixar_pdf.return_value = str(dummy_xml)
    with patch("app.api.routers.downloads.get_nfse_client", return_value=mock_nfse_cert):
        downloads.background_download("dl_ok", [inv_id], cli_id, "emitidas")
        assert tasks_status["dl_ok"]["status"] == "completed"


# ==============================================================================
# 6. SYSTEM ROUTER (support, list-folders, download/apply update) & EMAIL SSL/ERRORS
# ==============================================================================


def test_system_endpoints_and_update_download_apply(api_client: TestClient, tmp_path: Path):
    # Support message
    r_sup = api_client.post(
        "/api/support/message",
        json={"email": "user@test.com", "whatsapp": "27999999999", "message": "Preciso de ajuda"},
    )
    assert r_sup.status_code == 200

    # List folders
    r_folders = api_client.get("/api/system/list-folders", params={"path": str(tmp_path)})
    assert r_folders.status_code == 200
    assert r_folders.json()["current"] == str(tmp_path.resolve())

    # _download_release_package com zip em memória
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("nfse_manager-9.9.9/README.md", "# Updated")
    zip_bytes = zip_buf.getvalue()

    mock_stream_resp = MagicMock()
    mock_stream_resp.__enter__.return_value = mock_stream_resp
    mock_stream_resp.headers = {"Content-Length": str(len(zip_bytes))}
    mock_stream_resp.iter_bytes.return_value = [zip_bytes]

    mock_http_client = MagicMock()
    mock_http_client.__enter__.return_value = mock_http_client
    mock_http_client.stream.return_value = mock_stream_resp

    with (
        patch.object(
            system,
            "_latest_release_data",
            return_value={
                "tag_name": "v9.9.9",
                "zipball_url": "https://example.com/v9.9.9.zip",
                "html_url": "https://github.com/cleitonleonel/nfse_manager/releases/tag/v9.9.9",
            },
        ),
        patch.object(system.httpx, "Client", return_value=mock_http_client),
        patch.object(system, "DOWNLOAD_ROOT", tmp_path / "dl"),
        patch.object(system, "STAGING_ROOT", tmp_path / "stg"),
    ):
        system._download_release_package("upd_task_1", "9.9.9")
        assert tasks_status["upd_task_1"]["status"] == "completed"

        # Apply update
        with (
            patch.object(system, "PROJECT_ROOT", tmp_path / "proj"),
            patch.object(system, "BACKUP_ROOT", tmp_path / "bkp"),
            patch("app.api.routers.system.threading.Thread"),
        ):
            (tmp_path / "proj").mkdir(parents=True, exist_ok=True)
            r_apply = api_client.post("/api/system/update/apply", json={"task_id": "upd_task_1"})
            assert r_apply.status_code == 200

    # Erros em apply_downloaded_update
    assert api_client.post("/api/system/update/apply", json={"task_id": "nao_existe"}).status_code == 404
    tasks_status["upd_no_stage"] = {"status": "running"}
    assert api_client.post("/api/system/update/apply", json={"task_id": "upd_no_stage"}).status_code == 400


def test_email_service_ssl_465_and_error_branches(tmp_path: Path):
    cli = Client(
        id=1,
        cnpj="12345678000113",
        razao_social="EMPRESA EMAIL SSL",
        smtp_host="smtp.ssl.com",
        smtp_port=465,
        smtp_user="user@ssl.com",
        smtp_password="secret",
    )
    pdf_file = tmp_path / "danfse.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy")
    inv = Invoice(
        id=10,
        numero="10",
        chave="1" * 50,
        valor=100.0,
        tomador_email="cliente@destino.com",
        pdf_path=str(pdf_file),
    )

    with patch("app.services.email_service.smtplib.SMTP_SSL") as mock_ssl:
        res = EmailService.enviar_nfse_por_email(cli, inv)
        assert res["sucesso"] is True
        assert "pdf" in res["anexos"]
        assert mock_ssl.called

    # Sem destinatário -> 400
    inv_no_email = Invoice(id=11, numero="11", chave="2" * 50)
    with pytest.raises(HTTPException) as exc_to:
        EmailService.enviar_nfse_por_email(cli, inv_no_email)
    assert exc_to.value.status_code == 400

    # Sem SMTP no cliente nem no ambiente -> 400
    cli_empty = Client(id=2, cnpj="000", razao_social="SEM SMTP")
    with patch.dict("os.environ", {}, clear=False):
        with pytest.raises(HTTPException) as exc_cfg:
            EmailService.enviar_nfse_por_email(cli_empty, inv)
        assert exc_cfg.value.status_code == 400


def test_deps_and_version_edge_cases(tmp_path: Path):
    assert has_valid_certificate(None) is False
    cli_no_cert = Client(cnpj="123", razao_social="X", username="123", password="456", cert_path="", cert_password="")
    assert has_valid_certificate(cli_no_cert) is False

    cert_f = tmp_path / "dummy.pfx"
    cert_f.write_bytes(b"123")
    cli_with_cert = Client(
        cnpj="123",
        razao_social="X",
        username="123",
        password="456",
        cert_path=str(cert_f),
        cert_password="secret",
    )
    assert has_valid_certificate(cli_with_cert) is True

    nfse_cli = get_nfse_client(cli_no_cert)
    assert isinstance(nfse_cli, ClienteNfsePortalWrapper)
    assert nfse_cli.usa_apenas_credenciais() is True

    with patch.object(
        ClienteNfsePortalWrapper, "baixar_via_impressao_html", return_value={"xml_path": "/a.xml", "pdf_path": "/a.pdf"}
    ):
        assert nfse_cli.baixar_xml("https://x", "gerada") == "/a.xml"
        assert nfse_cli.baixar_pdf("https://x", "gerada") == "/a.pdf"

    # Version fallback com arquivo inexistente
    assert _read_pyproject_version(tmp_path / "inexistente.toml") is None
    poetry_toml = tmp_path / "poetry_only.toml"
    poetry_toml.write_text('[tool.poetry]\nversion = "1.2.3"\n', encoding="utf-8")
    assert _read_pyproject_version(poetry_toml) == "1.2.3"


# ==============================================================================
# 7. COBERTURA PROFUNDA DE ADN_SERVICE, DOWNLOADS, SYSTEM E CLIENTS
# ==============================================================================


@pytest.mark.anyio
async def test_adn_service_and_routers_edge_cases_and_error_branches(api_client: TestClient, tmp_path: Path):
    from app.schemas import (
        CancelarNfseRequest,
        EmitirDpsRequest,
        EnviarEmailNfseRequest,
        ReenviarFilaRequest,
        SincronizarCofreAdnRequest,
        SubstituirNfseRequest,
    )
    from app.services.adn_service import AdnService

    db = SessionLocal()
    try:
        # 1. Cliente inexistente -> 404
        with pytest.raises(HTTPException) as e404:
            AdnService.preview_dps(db, EmitirDpsRequest(client_id=9999999, servico={}))
        assert e404.value.status_code == 404

        # 2. Certificado Base64 inválido -> 400
        with pytest.raises(HTTPException) as e400:
            await AdnService.emitir_dps(
                db,
                EmitirDpsRequest(
                    certificado_pfx_b64="INVALIDO_B64",
                    senha_certificado="123",
                    servico={},
                ),
            )
        assert e400.value.status_code == 400

        # 3. Customer ou ServiceItem inexistente -> 404
        with pytest.raises(HTTPException) as ec404:
            AdnService.preview_dps(db, EmitirDpsRequest(customer_id=999999, servico={}))
        assert ec404.value.status_code == 404

        with pytest.raises(HTTPException) as es404:
            AdnService.preview_dps(db, EmitirDpsRequest(service_item_id=999999, servico={}))
        assert es404.value.status_code == 404

        # 4. emitir_dps sem certificado e transmitir=True -> fila_contingencia
        res_sem_cert = await AdnService.emitir_dps(
            db,
            EmitirDpsRequest(
                prestador={"cnpj": "12345678000113", "codigo_municipio": "5208707", "regime": "simples"},
                tomador={
                    "documento": "12345678000195",
                    "razao_social": "TOMADOR CONTINGENCIA",
                    "endereco": {
                        "codigo_municipio": "5208707",
                        "cep": "74805100",
                        "logradouro": "RUA X",
                        "numero": "10",
                        "bairro": "CENTRO",
                    },
                },
                servico={
                    "codigo_municipio_prestacao": "5208707",
                    "cTribNac": "010101",
                    "cNBS": "115021000",
                    "cClassTrib": "000001",
                    "indop": "030101",
                    "descricao": "Teste contingencia sem cert",
                    "valor": 500.0,
                },
                serie_dps="902",
                numero_dps=777,
                transmitir=True,
            ),
        )
        assert res_sem_cert["status_nota"] == "fila_contingencia"
        inv_sem_cert_id = res_sem_cert["invoice_id"]

        # 5. Reenviar fila quando nota não tem certificado no cliente -> registra falha sem quebrar
        res_reenvio_falha = await AdnService.reenviar_fila_contingencia(
            db, ReenviarFilaRequest(invoice_ids=[inv_sem_cert_id])
        )
        assert res_reenvio_falha["falhas"] == 1

        # 6. Cancelar sem documento_autor nem client_id -> 400
        with pytest.raises(HTTPException) as ecanc400:
            await AdnService.cancelar_nfse(
                db,
                CancelarNfseRequest(
                    chave_nfse="1" * 50,
                    motivo_codigo=1,
                    motivo_descricao="Motivo valido com mais de quinze caracteres",
                ),
            )
        assert ecanc400.value.status_code == 400

        # 7. Substituir com chave != 50 dígitos -> 400
        with pytest.raises(HTTPException) as esub400:
            await AdnService.substituir_nfse(
                db,
                SubstituirNfseRequest(
                    chave_nfse_substituida="12345",
                    motivo_codigo="01",
                    motivo_descricao="Motivo valido com mais de quinze caracteres",
                    servico={},
                ),
            )
        assert esub400.value.status_code == 400

        # 8. enviar_email_nfse com nota inexistente -> 404; nota sem client_id -> 400
        with pytest.raises(HTTPException) as eem404:
            AdnService.enviar_email_nfse(db, 9999999, EnviarEmailNfseRequest(destinatario="a@b.com"))
        assert eem404.value.status_code == 404

        with pytest.raises(HTTPException) as eem400:
            AdnService.enviar_email_nfse(db, inv_sem_cert_id, EnviarEmailNfseRequest(destinatario="a@b.com"))
        assert eem400.value.status_code == 400

        # 9. sincronizar_cofre_adn com cliente inexistente -> 404
        with pytest.raises(HTTPException) as ecofre404:
            await AdnService.sincronizar_cofre_adn(db, SincronizarCofreAdnRequest(client_id=9999999))
        assert ecofre404.value.status_code == 404
    finally:
        db.close()


def test_downloads_and_system_internal_helpers(api_client: TestClient, tmp_path: Path):
    # _path_candidates, _infer_file_kind, _clear_stale_reference
    assert downloads._path_candidates("") == []
    inv = Invoice(id=1, numero="1", chave="1" * 50, xml_path="/x/a.dat", pdf_path="/x/b.dat")
    assert downloads._infer_file_kind("nota.xml") == "xml"
    assert downloads._infer_file_kind("nota.pdf") == "pdf"
    assert downloads._infer_file_kind("nota.html") == "pdf"
    assert downloads._infer_file_kind("/x/a.dat", inv) == "xml"
    assert downloads._infer_file_kind("/x/b.dat", inv) == "pdf"
    assert downloads._infer_file_kind("/x/c.bin", inv) is None

    # convert_html_to_xml_endpoint com html_content direto e com falta de parâmetros (400)
    assert api_client.post("/api/download/html-to-xml", json={}).status_code == 400
    assert api_client.post("/api/download/xml-to-pdf", json={}).status_code == 400

    from tests.test_html_to_xml_and_pdf import SAMPLE_HTML_IMPRESSAO

    out_xml = tmp_path / "conv_direct.xml"
    r_h2x = api_client.post(
        "/api/download/html-to-xml",
        json={"html_content": SAMPLE_HTML_IMPRESSAO, "xml_output_path": str(out_xml)},
    )
    assert r_h2x.status_code == 200
    assert out_xml.exists()

    # convert_xml_to_pdf_endpoint com download=True
    out_pdf = tmp_path / "conv_direct.pdf"
    r_x2p = api_client.post(
        "/api/download/xml-to-pdf?download=true",
        json={"xml_path": str(out_xml), "pdf_output_path": str(out_pdf)},
    )
    assert r_x2p.status_code == 200
    assert r_x2p.headers["content-type"] == "application/pdf"

    # System router: _version_tuple, start_update_download, check_system_update error branches, _restart_self_after_delay
    assert system._version_tuple("1.2.beta") == (1, 2)
    with patch("app.api.routers.system._download_release_package"):
        r_dl_upd = api_client.post("/api/system/update/download", json={"version": "9.9.9"})
        assert r_dl_upd.status_code == 200
        assert "task_id" in r_dl_upd.json()

    with patch.object(system, "_latest_release_data", side_effect=HTTPException(status_code=502, detail="Bad Gateway")):
        r_chk_502 = api_client.get("/api/system/check-update")
        assert r_chk_502.status_code == 200
        assert r_chk_502.json()["update_available"] is False

    with patch.object(system, "_latest_release_data", side_effect=RuntimeError("Erro inesperado")):
        r_chk_err = api_client.get("/api/system/check-update")
        assert r_chk_err.status_code == 200
        assert "error" in r_chk_err.json()

    with (
        patch("app.api.routers.system.time.sleep"),
        patch("app.api.routers.system.os.execv") as mock_execv,
        patch.dict("os.environ", {}, clear=False),
    ):
        system._restart_self_after_delay(0.0)
        assert mock_execv.called

    # Clients 404 branches e remover_arquivos_e_pastas_cliente com save_path dedicado
    assert api_client.delete("/api/clients/9999999").status_code == 404
    assert api_client.put("/api/clients/9999999", data={"razao_social": "X"}).status_code == 404

    from app.api.routers.clients import remover_arquivos_e_pastas_cliente

    custom_dir = tmp_path / "12345678000199_PASTA_DEDICADA"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "nota.xml").write_text("<xml/>", encoding="utf-8")
    cli_custom = Client(
        id=999,
        cnpj="12.345.678/0001-99",
        razao_social="PASTA DEDICADA LTDA",
        save_path=str(custom_dir),
    )
    res_rem = remover_arquivos_e_pastas_cliente(cli_custom, [])
    assert str(custom_dir) in res_rem["pastas_removidas"]
    assert not custom_dir.exists()

    # Downloads: _clear_stale_reference, _gerar_pdf_local, _download_invoice_file, _sincronizar_arquivos_nota_certificado
    db = SessionLocal()
    try:
        inv_dl = Invoice(
            client_id=1,
            numero="999",
            chave="9" * 50,
            status="gerada",
            tipo="emitidas",
            xml_path=str(out_xml),
            pdf_path=str(out_pdf),
            download_url_xml="https://example.com/xml",
            download_url_pdf="https://example.com/pdf",
        )
        db.add(inv_dl)
        db.commit()
        db.refresh(inv_dl)

        downloads._clear_stale_reference(db, inv_dl, "xml")
        assert inv_dl.xml_path is None
        inv_dl.xml_path = str(out_xml)
        downloads._clear_stale_reference(db, inv_dl, "pdf")
        assert inv_dl.pdf_path is None

        # _gerar_pdf_local a partir do XML existente
        pdf_loc = downloads._gerar_pdf_local(inv_dl)
        assert pdf_loc is not None and Path(pdf_loc).exists()

        # _sincronizar_arquivos_nota_certificado com callbacks de progresso
        inv_dl.xml_path = None
        inv_dl.pdf_path = None
        steps_called = []
        mock_nfse_dl = MagicMock()
        mock_nfse_dl.baixar_xml.return_value = str(out_xml)
        mock_nfse_dl.baixar_pdf.return_value = str(out_pdf)
        downloads._sincronizar_arquivos_nota_certificado(
            mock_nfse_dl,
            inv_dl,
            baixar_xml=True,
            baixar_pdf=True,
            on_progress=lambda s: steps_called.append(s),
        )
        assert "xml" in steps_called and "pdf" in steps_called

        # _download_invoice_file com cliente inexistente e com cliente credenciais
        inv_orphan = Invoice(client_id=888888, numero="0", chave="8" * 50)
        assert downloads._download_invoice_file(db, inv_orphan, "x.xml") is None
        assert downloads._download_invoice_file(db, inv_dl, "arquivo_sem_extensao") is None

        db.delete(inv_dl)
        db.commit()
    finally:
        db.close()

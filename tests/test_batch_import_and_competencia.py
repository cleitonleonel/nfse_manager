import io
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pynfse.adn import DpsSigner

from app.api.routers.auth import get_current_user
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Client, Customer, Invoice, ServiceItem, User


@pytest.fixture()
def api_client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=999,
        username="pytest_batch",
        role="admin",
        is_active=True,
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _create_test_client_with_cert(tmp_path, cnpj="22345678000188") -> int:
    pfx_bytes = DpsSigner.gerar_pfx_autoassinado(
        cnpj=cnpj,
        razao_social="PRESTADOR LOTE TESTE LTDA",
        senha="batchpassword",
    )
    pfx_path = tmp_path / f"{cnpj}.pfx"
    pfx_path.write_bytes(pfx_bytes)

    db = SessionLocal()
    try:
        existing = db.query(Client).filter(Client.cnpj == cnpj).first()
        if existing:
            db.query(Invoice).filter(Invoice.client_id == existing.id).delete()
            db.query(Customer).filter(Customer.client_id == existing.id).delete()
            db.query(ServiceItem).filter(ServiceItem.client_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        c = Client(
            razao_social="PRESTADOR LOTE TESTE LTDA",
            cnpj=cnpj,
            username=cnpj,
            password="123",
            cert_path=str(pfx_path),
            cert_password="batchpassword",
            codigo_municipio="3201308",
            uf="ES",
            regime_tributario="normal",
            serie_dps_padrao="900",
            ultimo_numero_dps=0,
            ambiente_padrao="homologacao",
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c.id
    finally:
        db.close()


def test_import_customers_template_csv_and_xlsx_alphanumeric(api_client: TestClient, tmp_path):
    client_id = _create_test_client_with_cert(tmp_path, "22345678000188")

    r_tpl_csv = api_client.get("/api/customers/import/template?format=csv")
    assert r_tpl_csv.status_code == 200
    assert "documento;razao_social" in r_tpl_csv.text

    r_tpl_xlsx = api_client.get("/api/customers/import/template?format=xlsx")
    assert r_tpl_xlsx.status_code == 200
    wb_tpl = openpyxl.load_workbook(io.BytesIO(r_tpl_xlsx.content))
    assert wb_tpl.active.cell(1, 1).value == "documento"

    csv_content = (
        "documento;razao_social;email;telefone;cep;logradouro;numero;complemento;bairro;codigo_municipio;uf;inscricao_municipal\n"
        "11.222.333/0001-81;Cliente Numerico Ltda;num@example.com;27999990001;29160-000;Av A;10;;Centro;3201308;ES;1001\n"
        "12.ABC.345/0001-99;Cliente Alfanumerico S.A.;alfa@example.com;27999990002;01001-000;Rua B;20;Sala 2;Se;3550308;SP;2002\n"
    ).encode("utf-8")

    r_imp = api_client.post(
        "/api/customers/import",
        data={"client_id": str(client_id), "atualizar_existentes": "true"},
        files={"file": ("tomadores.csv", csv_content, "text/csv")},
    )
    assert r_imp.status_code == 200, r_imp.text
    res = r_imp.json()
    assert res["total_lidas"] == 2
    assert res["criados"] == 2
    assert res["erros"] == []

    db = SessionLocal()
    try:
        alfa = db.query(Customer).filter(
            Customer.client_id == client_id,
            Customer.documento == "12ABC345000199",
        ).first()
        assert alfa is not None
        assert alfa.razao_social == "Cliente Alfanumerico S.A."
    finally:
        db.close()

    # Atualiza o cliente alfanumérico via XLSX
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["documento", "razao_social", "email", "codigo_municipio"])
    ws.append(["12ABC345000199", "Cliente Alfanumerico Atualizado", "novo@example.com", "3550308"])
    buf = io.BytesIO()
    wb.save(buf)

    r_upd = api_client.post(
        "/api/customers/import",
        data={"client_id": str(client_id), "atualizar_existentes": "true"},
        files={
            "file": (
                "tomadores_upd.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r_upd.status_code == 200, r_upd.text
    assert r_upd.json()["atualizados"] == 1

    db = SessionLocal()
    try:
        alfa = db.query(Customer).filter(
            Customer.client_id == client_id,
            Customer.documento == "12ABC345000199",
        ).first()
        assert alfa.razao_social == "Cliente Alfanumerico Atualizado"
        assert alfa.email == "novo@example.com"
    finally:
        db.close()


def test_import_service_items_with_anexo_viii_enrichment(api_client: TestClient, tmp_path):
    client_id = _create_test_client_with_cert(tmp_path, "32345678000188")

    r_tpl = api_client.get("/api/service-items/import/template?format=xlsx")
    assert r_tpl.status_code == 200
    wb_tpl = openpyxl.load_workbook(io.BytesIO(r_tpl.content))
    assert wb_tpl.active.cell(1, 1).value == "titulo"

    csv_srv = (
        "titulo;descricao;c_trib_nac;c_nbs;c_class_trib;cst;indop;valor_unitario;aliquota_iss;iss_retido;reter_federais\n"
        "Desenvolvimento SaaS;Licenciamento mensal de plataforma SaaS;010101;;000001;;100301;3500.50;2.0;nao;sim\n"
    ).encode("utf-8")

    r_imp = api_client.post(
        "/api/service-items/import",
        data={"client_id": str(client_id), "atualizar_existentes": "true"},
        files={"file": ("servicos.csv", csv_srv, "text/csv")},
    )
    assert r_imp.status_code == 200, r_imp.text
    assert r_imp.json()["criados"] == 1

    db = SessionLocal()
    try:
        srv = db.query(ServiceItem).filter(
            ServiceItem.client_id == client_id,
            ServiceItem.titulo == "Desenvolvimento SaaS",
        ).first()
        assert srv is not None
        assert srv.valor_unitario == 3500.50
        assert bool(srv.reter_federais) is True
        assert bool(srv.iss_retido) is False
        assert srv.c_nbs  # Enriquecido via Anexo VIII
        assert srv.cst_ibscbs
    finally:
        db.close()


def test_emitir_lote_partial_errors_and_competencia(api_client: TestClient, tmp_path):
    client_id = _create_test_client_with_cert(tmp_path, "42345678000188")

    db = SessionLocal()
    try:
        c1 = Customer(
            client_id=client_id,
            documento="55666777000110",
            razao_social="Tomador Um Ltda",
            codigo_municipio="3201308",
        )
        c2 = Customer(
            client_id=client_id,
            documento="66777888000120",
            razao_social="Tomador Dois Ltda",
            codigo_municipio="3201308",
        )
        srv = ServiceItem(
            client_id=client_id,
            titulo="Consultoria Cloud",
            descricao="Consultoria em infraestrutura cloud",
            c_trib_nac="010101",
            c_nbs="115021000",
            c_class_trib="000001",
            cst_ibscbs="000",
            c_ind_op="100301",
            valor_unitario=1500.00,
            aliquota_iss=2.0,
        )
        db.add_all([c1, c2, srv])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)
        db.refresh(srv)
        c1_id, c2_id, srv_id = c1.id, c2.id, srv.id
    finally:
        db.close()

    mock_resp = AsyncMock(
        side_effect=[
            {
                "sucesso": True,
                "status_code": 201,
                "chave_acesso": "32013082242345678000188009000000000000126060000001",
                "nfse_xml": "<NFSe versao='1.01'/>",
                "mensagem": "Autorizada",
            },
            {
                "sucesso": False,
                "erro_transporte": True,
                "mensagem": "Timeout ADN simulado",
            },
        ]
    )

    with patch("app.services.adn_service.AdnNfseClient.emitir_dps", mock_resp):
        r_lote = api_client.post(
            "/api/adn/dps/emitir-lote",
            json={
                "client_id": client_id,
                "transmitir": True,
                "enviar_email": False,
                "data_competencia": "2026-06-15",
                "itens": [
                    {"customer_id": c1_id, "service_item_id": srv_id},
                    {"customer_id": c2_id, "service_item_id": srv_id, "servico": {"valor": 2000.00}},
                    {"customer_id": 9999999, "service_item_id": srv_id},
                ],
            },
        )

    assert r_lote.status_code == 200, r_lote.text
    data = r_lote.json()
    assert data["total"] == 3
    assert data["autorizadas"] == 1
    assert data["fila_contingencia"] == 1
    assert data["erros"] == 1
    assert data["resultados"][0]["status_nota"] == "gerada"
    assert data["resultados"][1]["status_nota"] == "fila_contingencia"
    assert data["resultados"][2]["status_nota"] == "erro"

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.tomador_documento == "55666777000110",
        ).first()
        assert inv is not None
        assert json.loads(inv.payload_dps_json)["data_competencia"] == "2026-06-15"
    finally:
        db.close()


def test_relatorio_competencia_json_csv_xlsx(api_client: TestClient, tmp_path):
    client_id = _create_test_client_with_cert(tmp_path, "52345678000188")

    db = SessionLocal()
    try:
        db.add_all(
            [
                Invoice(
                    client_id=client_id,
                    chave="CHAVE_COMP_AT_1",
                    tipo="emitidas",
                    status="gerada",
                    numero="1",
                    tomador_nome="Tomador Ativo",
                    valor=1000.0,
                    valor_liquido=950.0,
                    valor_iss=50.0,
                    valor_ibs=10.0,
                    valor_cbs=9.0,
                    data_emissao=datetime(2026, 6, 10, 10, 0),
                    payload_dps_json=json.dumps({"data_competencia": "2026-06-10"}),
                ),
                Invoice(
                    client_id=client_id,
                    chave="CHAVE_COMP_CANC",
                    tipo="emitidas",
                    status="cancelada",
                    numero="2",
                    tomador_nome="Tomador Cancelado",
                    valor=5000.0,
                    valor_liquido=4750.0,
                    valor_iss=250.0,
                    valor_ibs=50.0,
                    valor_cbs=45.0,
                    data_emissao=datetime(2026, 6, 12, 10, 0),
                ),
                Invoice(
                    client_id=client_id,
                    chave="CHAVE_COMP_REC",
                    tipo="recebidas",
                    status="gerada",
                    numero="3",
                    tomador_nome="Fornecedor X",
                    valor=300.0,
                    valor_liquido=300.0,
                    data_emissao=datetime(2026, 6, 15, 10, 0),
                ),
                Invoice(
                    client_id=client_id,
                    chave="CHAVE_COMP_FILA",
                    tipo="emitidas",
                    status="fila_contingencia",
                    numero="4",
                    tomador_nome="Tomador Fila",
                    valor=200.0,
                    valor_liquido=200.0,
                    data_emissao=datetime(2026, 6, 18, 10, 0),
                ),
                Invoice(
                    client_id=client_id,
                    chave="CHAVE_OUTRO_MES",
                    tipo="emitidas",
                    status="gerada",
                    numero="5",
                    valor=9999.0,
                    valor_liquido=9999.0,
                    data_emissao=datetime(2026, 5, 20, 10, 0),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    r_json = api_client.get(
        "/api/reports/competencia",
        params={"competencia": "2026-06", "client_id": client_id, "format": "json"},
    )
    assert r_json.status_code == 200, r_json.text
    resumo = r_json.json()["resumo"]
    assert resumo["competencia"] == "2026-06"
    assert resumo["qtd_total"] == 4
    assert resumo["qtd_emitidas_ativas"] == 2
    assert resumo["qtd_recebidas_ativas"] == 1
    assert resumo["qtd_canceladas_substituidas"] == 1
    assert resumo["qtd_pendentes_fila"] == 1
    assert resumo["total_emitidas_bruto"] == 1200.0
    assert resumo["total_emitidas_liquido"] == 1150.0
    assert resumo["total_recebidas"] == 300.0
    assert resumo["saldo_operacional"] == 900.0
    assert resumo["total_iss"] == 50.0
    assert resumo["total_ibs"] == 10.0
    assert resumo["total_cbs"] == 9.0

    r_csv = api_client.get(
        "/api/reports/competencia",
        params={"competencia": "2026-06", "client_id": client_id, "format": "csv"},
    )
    assert r_csv.status_code == 200
    assert "CHAVE_COMP_AT_1" in r_csv.text
    assert "CHAVE_OUTRO_MES" not in r_csv.text

    r_xlsx = api_client.get(
        "/api/reports/competencia",
        params={"competencia": "2026-06", "client_id": client_id, "format": "xlsx"},
    )
    assert r_xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content))
    assert "Resumo Competência" in wb.sheetnames
    assert "Notas da Competência" in wb.sheetnames

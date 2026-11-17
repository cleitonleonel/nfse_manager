import io
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import openpyxl
from pynfse.adn import AdnNfseClient, DpsSigner
import pytest

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import BatchImport, BatchImportItem, Client, Invoice, ServiceItem


@pytest.fixture()
def api_client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        yield client


def _setup_client_and_service(tmp_path, cnpj: str = "62345678000188") -> tuple[int, str]:
    pfx_bytes = DpsSigner.gerar_pfx_autoassinado(
        cnpj=cnpj,
        razao_social="PRESTADOR LOTE V2 LTDA",
        senha="v2password",
    )
    pfx_path = tmp_path / f"{cnpj}.pfx"
    pfx_path.write_bytes(pfx_bytes)

    db = SessionLocal()
    try:
        existing = db.query(Client).filter(Client.cnpj == cnpj).first()
        if existing:
            batches = db.query(BatchImport).filter(BatchImport.client_id == existing.id).all()
            for b in batches:
                db.query(BatchImportItem).filter(BatchImportItem.batch_id == b.id).delete()
                db.delete(b)
            db.query(Invoice).filter(Invoice.client_id == existing.id).delete()
            db.query(ServiceItem).filter(ServiceItem.client_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        c = Client(
            razao_social="PRESTADOR LOTE V2 LTDA",
            cnpj=cnpj,
            username=cnpj,
            password="123",
            cert_path=str(pfx_path),
            cert_password="v2password",
            codigo_municipio="3201308",
            uf="ES",
            regime_tributario="normal",
            serie_dps_padrao="900",
            ultimo_numero_dps=0,
            ambiente_padrao="homologacao",
        )
        db.add(c)
        db.flush()

        srv = ServiceItem(
            client_id=c.id,
            codigo_interno="CONS-TI",
            titulo="Consultoria TI Padrão",
            descricao="Serviço recorrente de consultoria TI",
            c_trib_nac="010101",
            c_nbs="115021000",
            c_class_trib="000001",
            cst_ibscbs="000",
            c_ind_op="100301",
            valor_unitario=1500.00,
            aliquota_iss=2.0,
        )
        db.add(srv)
        db.commit()
        db.refresh(c)
        return c.id, srv.codigo_interno
    finally:
        db.close()


def test_batch_template_and_importer_csv_delimiters_xlsx_leading_zeros(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "62345678000188")

    # 1. Modelos CSV e XLSX (com aba Instrucoes)
    r_csv = api_client.get("/api/batch-emission/template?format=csv")
    assert r_csv.status_code == 200
    assert "documento_tomador;nome_tomador" in r_csv.text

    r_xlsx = api_client.get("/api/batch-emission/template?format=xlsx")
    assert r_xlsx.status_code == 200
    wb_tpl = openpyxl.load_workbook(io.BytesIO(r_xlsx.content))
    assert "Notas Lote" in wb_tpl.sheetnames
    assert "Instrucoes" in wb_tpl.sheetnames

    # 2. CSV com ';' + valor monetário BR + data BR (sem transmitir no import)
    csv_semi = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Empresa Ponto Virgula Ltda;CONS-TI;Consultoria TI;1.250,50;15/06/2026;Suporte mensal junho\n"
    ).encode("utf-8")
    with patch("app.services.batch_emission.processor.AdnNfseClient.emitir_dps", new_callable=AsyncMock) as mock_emit:
        r_semi = api_client.post(
            "/api/batch-emission/import",
            data={"client_id": str(client_id)},
            files={"file": ("lote_semi.csv", csv_semi, "text/csv")},
        )
        assert mock_emit.call_count == 0
    assert r_semi.status_code == 200, r_semi.text
    b_semi = r_semi.json()
    assert b_semi["valid_items"] == 1
    assert b_semi["invalid_items"] == 0

    items_semi = api_client.get(f"/api/batch-emission/{b_semi['id']}/items").json()
    assert items_semi[0]["payload"]["valor_servico"] == 1250.50
    assert items_semi[0]["payload"]["competencia"] == "2026-06-15"

    # 3. CSV com ',' + data ISO
    csv_comma = (
        "documento_tomador,nome_tomador,codigo_servico,descricao_servico,valor_servico,competencia,discriminacao\n"
        "11222333000181,Empresa Virgula Ltda,CONS-TI,Consultoria TI,800.25,2026-06-20,Ajuste infra\n"
    ).encode("utf-8")
    r_comma = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id), "delimiter": ","},
        files={"file": ("lote_comma.csv", csv_comma, "text/csv")},
    )
    assert r_comma.status_code == 200, r_comma.text
    assert r_comma.json()["valid_items"] == 1

    # 4. XLSX preservando zeros à esquerda em CPF
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["documento_tomador", "nome_tomador", "codigo_servico", "descricao_servico", "valor_servico", "competencia", "discriminacao"])
    ws.append(["01234567890", "Pessoa Fisica Zero", "CONS-TI", "Mentoria TI", "350,00", "06/2026", "Sessao mentoria"])
    ws.cell(row=2, column=1).number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)

    r_up_xlsx = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={
            "file": (
                "lote_zeros.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r_up_xlsx.status_code == 200, r_up_xlsx.text
    b_xlsx = r_up_xlsx.json()
    assert b_xlsx["valid_items"] == 1
    it_xlsx = api_client.get(f"/api/batch-emission/{b_xlsx['id']}/items").json()[0]
    assert it_xlsx["payload"]["documento_tomador"] == "01234567890"
    assert it_xlsx["payload"]["competencia"] == "2026-06-01"


def test_batch_3_level_validation_and_inline_patch_revalidation(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "72345678000188")

    csv_mixed = (
        "documento_tomador;nome_tomador;codigo_servico;c_trib_nac;descricao_servico;valor_servico;competencia;discriminacao;cst_ibs_cbs;cclasstrib\n"
        "11222333000181;Tomador Valido Numeric;CONS-TI;;Consultoria;1000.00;2026-06-10;Valida 1;;\n"
        "12345678900;Tomador CPF Ruim;CONS-TI;;Consultoria;500.00;2026-06-10;Erro DV;;\n"
        "11222333000181;Servico Inexistente;NAO_EXISTE;;Outro;400.00;2026-06-10;Erro servico;;\n"
        "11222333000181;CST Incompativel;;010101;Consultoria;600.00;2026-06-10;Erro fiscal;999;000001\n"
        "12ABC345000188;Tomador CNPJ Alfanumerico;;010101;Consultoria;900.00;2026-06-10;Alfanumerico valido;000;000001\n"
    ).encode("utf-8")

    r_imp = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={"file": ("misto.csv", csv_mixed, "text/csv")},
    )
    assert r_imp.status_code == 200, r_imp.text
    b = r_imp.json()
    assert b["status"] == "PARTIAL"
    assert b["total_items"] == 5
    assert b["valid_items"] == 2
    assert b["invalid_items"] == 3

    items = api_client.get(f"/api/batch-emission/{b['id']}/items").json()
    assert items[0]["status"] == "VALID"
    assert items[1]["status"] == "INVALID"
    assert any(e["field"] == "documento_tomador" and e["level"] == "estrutural" for e in items[1]["validation_errors"])
    assert items[2]["status"] == "INVALID"
    assert any(e["field"] == "codigo_servico" and e["level"] == "cadastral" for e in items[2]["validation_errors"])
    assert items[3]["status"] == "INVALID"
    assert any(e["level"] == "fiscal" for e in items[3]["validation_errors"])
    assert items[4]["status"] == "VALID"  # CNPJ alfanumérico válido

    # Corrige apenas a linha 3 (CPF inválido -> válido) via PATCH sem reconstruir o lote
    r_patch = api_client.patch(
        f"/api/batch-emission/{b['id']}/items/{items[1]['id']}",
        json={"documento_tomador": "01234567890"},
    )
    assert r_patch.status_code == 200, r_patch.text
    assert r_patch.json()["status"] == "VALID"
    assert r_patch.json()["validation_errors"] == []

    b_after = api_client.get(f"/api/batch-emission/{b['id']}").json()
    assert b_after["valid_items"] == 3
    assert b_after["invalid_items"] == 2


def test_batch_processing_rejected_continuity_no_reemit_and_unknown_recovery(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "82345678000188")

    csv_valid = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Nota Um OK;CONS-TI;Consultoria;1000.00;2026-06-10;Item 1\n"
        "12ABC345000188;Nota Dois Rejeitada;CONS-TI;Consultoria;1200.00;2026-06-11;Item 2\n"
        "01234567890;Nota Tres Timeout Unknown;CONS-TI;Consultoria;1300.00;2026-06-12;Item 3\n"
        "11222333000181;Nota Quatro Retry 404;CONS-TI;Consultoria;1400.00;2026-06-13;Item 4\n"
    ).encode("utf-8")

    b = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={"file": ("processar.csv", csv_valid, "text/csv")},
    ).json()
    assert b["valid_items"] == 4

    xml_nfse_mock = "<NFSe xmlns='http://www.sped.fazenda.gov.br/nfse'><infNFSe/></NFSe>"
    mock_emit = AsyncMock(
        side_effect=[
            {
                "sucesso": True,
                "status_code": 201,
                "chave_acesso": "32013082282345678000188009000000000000126060000001",
                "nfse_xml": xml_nfse_mock,
            },
            {
                "sucesso": False,
                "status_code": 422,
                "resposta": {"erros": ["E0999 - Erro simulado Sefin"]},
            },
            TimeoutError("Timeout simulado após POST"),
            {
                "sucesso": False,
                "status_code": 503,
                "mensagem": "Sefin indisponível",
            },
        ]
    )

    with patch("app.services.batch_emission.processor.AdnNfseClient.emitir_dps", mock_emit):
        r_proc = api_client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": True})

    assert r_proc.status_code == 200, r_proc.text
    res_b = r_proc.json()
    assert res_b["authorized_items"] == 1
    assert res_b["rejected_items"] == 1
    assert res_b["unknown_items"] == 2

    items = api_client.get(f"/api/batch-emission/{b['id']}/items").json()
    assert [it["status"] for it in items] == ["AUTHORIZED", "REJECTED", "UNKNOWN", "UNKNOWN"]
    dps_id_item4 = items[3]["id_dps"]
    assert dps_id_item4

    # Tentar reprocessar diretamente NÃO deve reenviar AUTHORIZED, REJECTED ou UNKNOWN sem consultar primeiro
    with patch("app.services.batch_emission.processor.AdnNfseClient.emitir_dps", new_callable=AsyncMock) as mock_no_send:
        r_again = api_client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": True})
        assert r_again.status_code == 400
        assert mock_no_send.call_count == 0

    # Recuperação segura via /retry:
    # - item3 (UNKNOWN) encontra 200 na consulta -> vira AUTHORIZED sem chamar emitir_dps!
    # - item4 (UNKNOWN) recebe 404 na consulta -> vira RETRY e reenvia usando o MESMO id_dps -> vira AUTHORIZED!
    nfse_b64 = AdnNfseClient.compactar_xml_gzip_b64(xml_nfse_mock)
    mock_consultar = AsyncMock(
        side_effect=[
            {
                "sucesso": True,
                "status_code": 200,
                "id_dps": items[2]["id_dps"],
                "conteudo": {
                    "chaveAcesso": "32013082282345678000188009000000000000326060000003",
                    "nfseXmlGZipB64": nfse_b64,
                },
            },
            {
                "sucesso": False,
                "status_code": 404,
                "id_dps": dps_id_item4,
                "conteudo": None,
            },
        ]
    )
    mock_emit_retry = AsyncMock(
        return_value={
            "sucesso": True,
            "status_code": 201,
            "chave_acesso": "32013082282345678000188009000000000000426060000004",
            "nfse_xml": xml_nfse_mock,
        }
    )

    with (
        patch("app.services.batch_emission.processor.AdnNfseClient.consultar_dps", mock_consultar),
        patch("app.services.batch_emission.processor.AdnNfseClient.emitir_dps", mock_emit_retry),
    ):
        r_retry = api_client.post(f"/api/batch-emission/{b['id']}/retry", json={"transmitir": True})

    assert r_retry.status_code == 200, r_retry.text
    assert mock_consultar.call_count == 2
    # emitir_dps chamado SOMENTE 1 vez (para o item4 que deu 404), nunca para item3 (que já estava autorizado)
    assert mock_emit_retry.call_count == 1
    assert dps_id_item4 in mock_emit_retry.call_args.args[0]

    b_final = r_retry.json()
    assert b_final["authorized_items"] == 3
    assert b_final["rejected_items"] == 1
    assert b_final["unknown_items"] == 0


def test_batch_cancellation_and_export_csv_xlsx(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "92345678000188")

    csv_data = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Tomador Cancelavel;CONS-TI;Consultoria;500.00;2026-06-15;Cancelavel\n"
    ).encode("utf-8")

    b = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={"file": ("cancelar.csv", csv_data, "text/csv")},
    ).json()

    r_cancel = api_client.post(f"/api/batch-emission/{b['id']}/cancel")
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == "CANCELLED"

    r_proc = api_client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": True})
    assert r_proc.status_code == 409

    r_exp_csv = api_client.get(f"/api/batch-emission/{b['id']}/export?format=csv")
    assert r_exp_csv.status_code == 200
    assert "Tomador Cancelavel" in r_exp_csv.text
    assert "CANCELLED" in r_exp_csv.text

    r_exp_xlsx = api_client.get(f"/api/batch-emission/{b['id']}/export?format=xlsx")
    assert r_exp_xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r_exp_xlsx.content))
    assert "Resumo Lote" in wb.sheetnames
    assert "Itens do Lote" in wb.sheetnames


def test_batch_delete_one_many_all_and_registry_batch_delete(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "93345678000188")

    csv_data = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Item 1;CONS-TI;Consultoria;100.00;2026-06-15;Item 1\n"
        "12ABC345000188;Item 2;CONS-TI;Consultoria;200.00;2026-06-15;Item 2\n"
        "01234567890;Item 3;CONS-TI;Consultoria;300.00;2026-06-15;Item 3\n"
        "11222333000181;Item 4;CONS-TI;Consultoria;400.00;2026-06-15;Item 4\n"
        "12345678900;Item 5 Invalido;CONS-TI;Consultoria;500.00;2026-06-15;Item 5\n"
    ).encode("utf-8")

    b = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={"file": ("excluir.csv", csv_data, "text/csv")},
    ).json()
    assert b["total_items"] == 5

    items = api_client.get(f"/api/batch-emission/{b['id']}/items").json()
    assert len(items) == 5

    # Excluir 1 item (o inválido da linha 6)
    r_del_one = api_client.delete(f"/api/batch-emission/{b['id']}/items/{items[4]['id']}")
    assert r_del_one.status_code == 200
    assert r_del_one.json()["deleted"] == 1
    assert r_del_one.json()["batch"]["total_items"] == 4
    assert r_del_one.json()["batch"]["invalid_items"] == 0

    # Excluir múltiplos selecionados (2 itens)
    r_del_many = api_client.post(
        f"/api/batch-emission/{b['id']}/items/delete",
        json={"item_ids": [items[0]["id"], items[1]["id"]], "delete_all": False},
    )
    assert r_del_many.status_code == 200
    assert r_del_many.json()["deleted"] == 2
    assert r_del_many.json()["batch"]["total_items"] == 2

    # Excluir todos os itens restantes
    r_del_all = api_client.post(
        f"/api/batch-emission/{b['id']}/items/delete",
        json={"delete_all": True},
    )
    assert r_del_all.status_code == 200
    assert r_del_all.json()["deleted"] == 2
    assert r_del_all.json()["batch"]["total_items"] == 0

    # Excluir o lote inteiro
    r_del_batch = api_client.delete(f"/api/batch-emission/{b['id']}")
    assert r_del_batch.status_code == 200
    assert api_client.get(f"/api/batch-emission/{b['id']}").status_code == 404

    # Exclusão em lote de tomadores e serviços importados
    csv_cust = (
        "documento;razao_social;codigo_municipio\n"
        "11222333000181;Cust A;3201308\n"
        "12ABC345000188;Cust B;3201308\n"
        "01234567890;Cust C;3201308\n"
    ).encode("utf-8")
    api_client.post(
        "/api/customers/import",
        data={"client_id": str(client_id)},
        files={"file": ("custs.csv", csv_cust, "text/csv")},
    )
    custs = api_client.get("/api/customers", params={"client_id": client_id}).json()
    assert len(custs) >= 3

    r_del_cust_sel = api_client.post(
        "/api/customers/delete-batch",
        json={"ids": [custs[0]["id"], custs[1]["id"]], "delete_all": False},
    )
    assert r_del_cust_sel.status_code == 200
    assert r_del_cust_sel.json()["deleted"] == 2

    r_del_cust_all = api_client.post(
        "/api/customers/delete-batch",
        json={"client_id": client_id, "delete_all": True},
    )
    assert r_del_cust_all.status_code == 200
    assert r_del_cust_all.json()["deleted"] >= 1

    r_del_srv_all = api_client.post(
        "/api/service-items/delete-batch",
        json={"client_id": client_id, "delete_all": True},
    )
    assert r_del_srv_all.status_code == 200
    assert r_del_srv_all.json()["deleted"] >= 1


def test_batch_and_contingency_queue_sync_on_delete_and_cancel(api_client: TestClient, tmp_path):
    client_id, _ = _setup_client_and_service(tmp_path, "94345678000188")

    csv_data = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Fila Nota A;CONS-TI;Consultoria;100.00;2026-06-15;Nota A\n"
        "12ABC345000188;Fila Nota B;CONS-TI;Consultoria;200.00;2026-06-15;Nota B\n"
        "01234567890;Autorizada Nota C;CONS-TI;Consultoria;300.00;2026-06-15;Nota C\n"
    ).encode("utf-8")

    b = api_client.post(
        "/api/batch-emission/import",
        data={"client_id": str(client_id)},
        files={"file": ("fila_sync.csv", csv_data, "text/csv")},
    ).json()

    # Nota A e Nota B vão para contingência (UNKNOWN -> fila_contingencia); Nota C autoriza
    mock_emit = AsyncMock(
        side_effect=[
            TimeoutError("Timeout A"),
            TimeoutError("Timeout B"),
            {
                "sucesso": True,
                "status_code": 201,
                "chave_acesso": "32013082294345678000188009000000000000326060000003",
                "nfse_xml": "<NFSe xmlns='http://www.sped.fazenda.gov.br/nfse'><infNFSe/></NFSe>",
            },
        ]
    )
    with patch("app.services.batch_emission.processor.AdnNfseClient.emitir_dps", mock_emit):
        r_proc = api_client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": True})
    assert r_proc.status_code == 200

    fila_antes = api_client.get("/api/adn/fila", params={"client_id": client_id}).json()
    assert len(fila_antes) == 2

    items = api_client.get(f"/api/batch-emission/{b['id']}/items").json()
    item_a = items[0]
    item_b = items[1]
    item_c = items[2]

    # 1. Excluir item_a da lista do lote remove também a pendência da fila de contingência
    r_del_a = api_client.delete(f"/api/batch-emission/{b['id']}/items/{item_a['id']}")
    assert r_del_a.status_code == 200
    assert r_del_a.json()["removed_from_contingency"] == 1

    fila_meio = api_client.get("/api/adn/fila", params={"client_id": client_id}).json()
    assert len(fila_meio) == 1
    assert fila_meio[0]["id"] == item_b["invoice_id"]

    # 2. Cancelar diretamente pela Fila de Contingência remove da fila e marca item_b como CANCELLED
    r_cancel_fila = api_client.delete(f"/api/adn/fila/{item_b['invoice_id']}")
    assert r_cancel_fila.status_code == 200
    assert b["id"] in r_cancel_fila.json()["updated_batches"]

    fila_depois = api_client.get("/api/adn/fila", params={"client_id": client_id}).json()
    assert len(fila_depois) == 0

    items_after = api_client.get(f"/api/batch-emission/{b['id']}/items").json()
    item_b_after = next(x for x in items_after if x["id"] == item_b["id"])
    assert item_b_after["status"] == "CANCELLED"

    # 3. Cancelar nota já autorizada (item_c) pela fila retorna 409; excluir item_c NÃO apaga a NFS-e autorizada
    assert api_client.delete(f"/api/adn/fila/{item_c['invoice_id']}").status_code == 409
    r_del_c = api_client.delete(f"/api/batch-emission/{b['id']}/items/{item_c['id']}")
    assert r_del_c.status_code == 200
    assert r_del_c.json()["removed_from_contingency"] == 0
    invs = api_client.get("/api/invoices", params={"client_id": client_id}).json()
    assert any(inv["id"] == item_c["invoice_id"] for inv in invs)

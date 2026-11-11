"""Testes de exclusão de clientes, limpeza de arquivos físicos e organização de certificados por CNPJ."""

import io
from pathlib import Path
from fastapi.testclient import TestClient

from app.api.deps import DOWNLOADS_DIR
from app.api.routers.clients import CERTIFICADOS_DIR
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Client, Invoice


def setup_function():
    Base.metadata.create_all(bind=engine)


def teardown_function():
    # Limpeza básica pós-teste se necessário
    pass


def test_certificado_salvo_em_subpasta_por_cnpj():
    client = TestClient(app)
    cnpj = "12.345.678/0001-90"
    safe_cnpj = "12345678000190"

    # Simular upload de certificado .pfx
    fake_pfx = io.BytesIO(b"PFX_CONTENT_FICTICIO_1234")
    response = client.post(
        "/api/clients",
        data={
            "cnpj": cnpj,
            "razao_social": "Empresa Teste Subpasta Certificado",
            "cert_password": "senha_teste_123",
        },
        files={"cert_file": ("meu_certificado.pfx", fake_pfx, "application/x-pkcs12")},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    client_id = data["id"]
    cert_path_str = data["cert_path"]

    # Verificar que o arquivo foi gravado dentro de uma subpasta nomeada com o CNPJ
    cert_path = Path(cert_path_str)
    assert cert_path.exists()
    assert cert_path.parent.name == safe_cnpj
    assert cert_path.name == "meu_certificado.pfx"
    assert cert_path.read_bytes() == b"PFX_CONTENT_FICTICIO_1234"

    # Limpeza do teste deletando o cliente via API
    del_resp = client.delete(f"/api/clients/{client_id}")
    assert del_resp.status_code == 200
    assert not cert_path.exists()
    assert not cert_path.parent.exists()


def test_delecao_completa_cliente_notas_e_arquivos_fisicos():
    client = TestClient(app)
    cnpj = "98.765.432/0001-11"
    safe_cnpj = "98765432000111"

    # 1. Cadastrar cliente com certificado
    fake_pfx = io.BytesIO(b"PFX_CONTEUDO_PARA_DELECAO")
    res_cli = client.post(
        "/api/clients",
        data={
            "cnpj": cnpj,
            "razao_social": "Cliente Completo Para Excluir",
            "cert_password": "123",
        },
        files={"cert_file": ("cert_excluir.pfx", fake_pfx, "application/x-pkcs12")},
    )
    assert res_cli.status_code == 200
    client_id = res_cli.json()["id"]

    # Verificar pasta de certificados criada
    cert_dir = CERTIFICADOS_DIR / safe_cnpj
    assert cert_dir.exists() and cert_dir.is_dir()

    # 2. Criar pasta de downloads e arquivos de notas físicas simuladas
    client_dl_dir = DOWNLOADS_DIR / safe_cnpj
    client_dl_dir.mkdir(parents=True, exist_ok=True)
    xml_nota = client_dl_dir / "nota_teste_999.xml"
    pdf_nota = client_dl_dir / "nota_teste_999.pdf"
    xml_nota.write_text("<xml>teste nota</xml>", encoding="utf-8")
    pdf_nota.write_bytes(b"%PDF-1.4 teste pdf")

    # Inserir nota associada ao cliente no banco de dados
    db = SessionLocal()
    try:
        inv = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000999",
            numero="999",
            status="gerada",
            tipo="emitidas",
            valor=1500.50,
            xml_path=str(xml_nota),
            pdf_path=str(pdf_nota),
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)
        invoice_id = inv.id
    finally:
        db.close()

    # Verificar que analytics contabiliza o valor do cliente
    stats_pre = client.get(f"/api/analytics/stats?client_id={client_id}").json()
    assert stats_pre["total_notas"] == 1
    assert stats_pre["valor_emitidas"] == 1500.50

    # 3. Deletar o cliente
    res_del = client.delete(f"/api/clients/{client_id}")
    assert res_del.status_code == 200
    del_data = res_del.json()
    assert del_data["notas_excluidas"] == 1

    # 4. Verificar remoção física dos arquivos e diretórios
    assert not cert_dir.exists(), "A pasta de certificados do cliente deveria ter sido excluída."
    assert not client_dl_dir.exists(), "A pasta de downloads do cliente deveria ter sido excluída."
    assert not xml_nota.exists(), "O arquivo XML da nota deveria ter sido removido."
    assert not pdf_nota.exists(), "O arquivo PDF da nota deveria ter sido removido."

    # 5. Verificar remoção no banco de dados
    db = SessionLocal()
    try:
        assert db.query(Client).filter(Client.id == client_id).first() is None
        assert db.query(Invoice).filter(Invoice.id == invoice_id).first() is None
    finally:
        db.close()

    # 6. Verificar que estatísticas do cliente agora retornam 0 notas e 0 valores
    stats_post = client.get(f"/api/analytics/stats?client_id={client_id}").json()
    assert stats_post["total_notas"] == 0
    assert stats_post["valor_emitidas"] == 0.0

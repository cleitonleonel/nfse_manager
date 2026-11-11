"""Testes de conversão do HTML de impressão da NFS-e em XML e geração de PDF via pynfse."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.html_xml_service import (
    converter_arquivo_html_para_xml,
    converter_html_para_xml,
    converter_xml_para_pdf_pynfse,
    extrair_chave_do_xml,
)
from pynfse.xml_parser import extrair_dados_nfse

SAMPLE_HTML_IMPRESSAO = """<!DOCTYPE html>
<html>
<head><title>NFS-e | Emissor Nacional</title></head>
<body class="impressao">
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Identificação da NFS-e</h3>
  <div class="panel-body">
    <div class="row">
      <div class="col-md-7">
        <div class="form-group"><label class="control-label"><span>Chave de acesso</span></label><span class="form-control-static texto">32013081219495981000113000000000086326010205340809</span></div>
      </div>
      <div class="col-md-3">
        <div class="form-group"><label class="control-label"><span>Data de geração</span></label><span class="form-control-static texto">31/01/2026 às 00:00:00-03:00</span></div>
      </div>
      <div class="col-md-2">
        <div class="form-group"><label class="control-label"><span>Versão</span></label><span class="form-control-static texto">1.00</span></div>
      </div>
    </div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Identificação do DPS</h3>
  <div class="panel-body">
    <div class="row">
      <div class="col-md-4">
        <div class="form-group"><label class="control-label"><span>Número</span></label><span class="form-control-static texto">863</span></div>
      </div>
      <div class="col-md-3">
        <div class="form-group"><label class="control-label"><span>Série</span></label><span class="form-control-static texto">49999</span></div>
      </div>
      <div class="col-md-3">
        <div class="form-group"><label class="control-label"><span>Data de emissão</span></label><span class="form-control-static texto">31/01/2026 às 00:00:00-03:00</span></div>
      </div>
      <div class="col-md-2">
        <div class="form-group"><label class="control-label"><span>Versão</span></label><span class="form-control-static texto">1.00</span></div>
      </div>
    </div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Emitente</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>Razão Social</span></label><span class="form-control-static texto">OTMA SOLUCOES LTDA</span></div>
    <div class="form-group"><label class="control-label"><span>CNPJ</span></label><span class="form-control-static texto">19.495.981/0001-13</span></div>
    <div class="form-group"><label class="control-label"><span>Inscrição Municipal</span></label><span class="form-control-static texto">126655</span></div>
    <div class="form-group"><label class="control-label"><span>Situação Perante o Simples Nacional</span></label><span class="form-control-static texto">Microempresa ou Empresa de Pequeno Porte (ME/EPP)</span></div>
    <div class="form-group"><label class="control-label"><span>Regime Especial de Tributação</span></label><span class="form-control-static texto">Nenhum</span></div>
    <div class="form-group"><label class="control-label"><span>Endereço do Estabelecimento/Domicílio</span></label><span class="form-control-static texto">29151-260 - RUA DEMÓSTHENES NUNES VIEIRA, 60 , 0 , Bairro ALTO LAJE , CEP 29151260 , Cariacica/ES</span></div>
    <div class="form-group"><label class="control-label"><span>Telefone</span></label><span class="form-control-static texto">(27)99223-0428</span></div>
    <div class="form-group"><label class="control-label"><span>Email</span></label><span class="form-control-static texto">contato@otmasolucoes.com.br</span></div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Tributação Municipal</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>Tributação do ISSQN</span></label><span class="form-control-static texto">1 - Operação Tributável</span></div>
    <div class="form-group"><label class="control-label"><span>Município de Incidência</span></label><span class="form-control-static texto">Cariacica/ES</span></div>
    <div class="form-group"><label class="control-label"><span>Valor do Serviço</span></label><span class="form-control-static texto numero">320,00</span></div>
    <div class="form-group"><label class="control-label"><span>Desconto incondicionado</span></label><span class="form-control-static texto numero">0,00</span></div>
    <div class="form-group"><label class="control-label"><span>Base de Cálculo</span></label><span class="form-control-static texto numero">320,00</span></div>
    <div class="form-group"><label class="control-label"><span>Alíquota</span></label><span class="form-control-static texto numero">5,00</span></div>
    <div class="form-group"><label class="control-label"><span>Valor do ISSQN</span></label><span class="form-control-static texto numero">16,00</span></div>
    <div class="form-group"><label class="control-label"><span>Retenção</span></label><span class="form-control-static texto">1 - Não Retido</span></div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Outras Informações</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>Versão da Aplicação</span></label><span class="form-control-static texto">SilTecnologia_v1.00</span></div>
    <div class="form-group"><label class="control-label"><span>Ambiente Gerador</span></label><span class="form-control-static texto">1 - Sistema Próprio do Município</span></div>
    <div class="form-group"><label class="control-label"><span>Situação da NFS-e</span></label><span class="form-control-static texto">100 - NFS-e Gerada</span></div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Tomador</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>CNPJ</span></label><span class="form-control-static texto">05.411.003/0001-31</span></div>
    <div class="form-group"><label class="control-label"><span>Inscrição Municipal</span></label><span class="form-control-static texto">-</span></div>
    <div class="form-group"><label class="control-label"><span>Nome/Razão Social</span></label><span class="form-control-static texto">PCNS TECNOLOGIA E SOLUÇÕES LTDA</span></div>
    <div class="form-group"><label class="control-label"><span>Endereço do Estabelecimento/Domicílio</span></label><span class="form-control-static texto">RUA DEMOSTENES NUNES N.60 , 58 , Bairro ALTO LAGE , CEP 29151260 , Cariacica/ES</span></div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Serviço Prestado</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>País</span></label><span class="form-control-static texto">Brasil</span></div>
    <div class="form-group"><label class="control-label"><span>Município</span></label><span class="form-control-static texto">Cariacica/ES</span></div>
    <div class="form-group"><label class="control-label"><span>Código de Tributação Nacional</span></label><span class="form-control-static texto">010701 - Suporte técnico em informática, inclusive instalação, configuração e manutenção de programas de computação e bancos de dados.</span></div>
    <div class="form-group"><label class="control-label"><span>Item da NBS correspondente ao serviço prestado</span></label><span class="form-control-static texto">115013000 - </span></div>
    <div class="form-group"><label class="control-label"><span>Descrição do serviço</span></label><span class="form-control-static texto">PRESTAÇAO SERVICOS INFORMATICA</span></div>
  </div>
</div>
<div class="panel panel-default panelExterno">
  <h3 class="panel-title">Total dos tributos</h3>
  <div class="panel-body">
    <div class="form-group"><label class="control-label"><span>Federal</span></label><span class="form-control-static texto numero">0,00</span></div>
    <div class="form-group"><label class="control-label"><span>Estadual</span></label><span class="form-control-static texto numero">0,00</span></div>
    <div class="form-group"><label class="control-label"><span>Municipal</span></label><span class="form-control-static texto numero">16,00</span></div>
  </div>
</div>
</body>
</html>
"""


def test_converter_html_para_xml_e_extrair_dados(tmp_path):
    html_file = tmp_path / "pdfs" / "32013081219495981000113000000000086326010205340809.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(SAMPLE_HTML_IMPRESSAO, encoding="utf-8")

    xml_path = converter_arquivo_html_para_xml(html_file)
    assert Path(xml_path).exists()
    assert "/xmls/" in xml_path.replace("\\", "/")

    dados = extrair_dados_nfse(xml_path)
    assert dados["numero"] == "863"
    assert dados["chave"] == "32013081219495981000113000000000086326010205340809"
    assert dados["valor"] == 320.0
    assert dados["cnpj_prestador"] == "19495981000113"
    assert dados["cnpj_tomador"] == "05411003000131"
    assert dados["nome_tomador"] == "PCNS TECNOLOGIA E SOLUÇÕES LTDA"


def test_servicos_html_xml_e_pdf_diretamente(tmp_path):
    xml_content = converter_html_para_xml(SAMPLE_HTML_IMPRESSAO)
    chave = extrair_chave_do_xml(xml_content)
    assert chave == "32013081219495981000113000000000086326010205340809"

    res = converter_xml_para_pdf_pynfse(
        xml_content=xml_content,
        default_dir=tmp_path,
        status="NORMAL",
    )
    assert Path(res["pdf_path"]).exists()
    assert Path(res["xml_path"]).exists()
    assert res["chave"] == chave

    with pytest.raises(ValueError):
        converter_xml_para_pdf_pynfse()


def test_rotas_html_to_xml_e_xml_to_pdf_via_pynfse(tmp_path):
    client = TestClient(app)

    html_file = tmp_path / "pdfs" / "32013081219495981000113000000000086326010205340809.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(SAMPLE_HTML_IMPRESSAO, encoding="utf-8")
    xml_out = tmp_path / "xmls" / "32013081219495981000113000000000086326010205340809.xml"
    pdf_out = tmp_path / "pdfs" / "32013081219495981000113000000000086326010205340809.pdf"

    # 1. Converte HTML baixado para XML pela rota /api/download/html-to-xml
    resp_xml = client.post(
        "/api/download/html-to-xml",
        json={
            "html_path": str(html_file),
            "xml_output_path": str(xml_out),
        },
    )
    assert resp_xml.status_code == 200
    body_xml = resp_xml.json()
    assert body_xml["chave"] == "32013081219495981000113000000000086326010205340809"
    assert Path(body_xml["xml_path"]).exists()
    assert "<NFSe" in body_xml["xml_content"]

    # 2. Envia o XML gerado para a rota /api/download/xml-to-pdf converter em PDF via pynfse
    resp_pdf = client.post(
        "/api/download/xml-to-pdf",
        json={
            "xml_content": body_xml["xml_content"],
            "xml_path": body_xml["xml_path"],
            "pdf_output_path": str(pdf_out),
            "status": "NORMAL",
        },
    )
    assert resp_pdf.status_code == 200
    body_pdf = resp_pdf.json()
    assert body_pdf["pdf_path"] == str(pdf_out)
    assert pdf_out.exists()
    assert pdf_out.read_bytes().startswith(b"%PDF")

    # 3. Testa download direto (?download=true) na rota /api/download/xml-to-pdf
    resp_dl = client.post(
        "/api/download/xml-to-pdf?download=true",
        json={
            "xml_content": body_xml["xml_content"],
            "pdf_output_path": str(tmp_path / "pdfs" / "direto.pdf"),
            "status": "CANCELADA",
        },
    )
    assert resp_dl.status_code == 200
    assert resp_dl.headers["content-type"] == "application/pdf"
    assert resp_dl.content.startswith(b"%PDF")


def test_download_file_converte_html_automaticamente_em_xml_e_pdf(tmp_path):
    client = TestClient(app)

    html_file = tmp_path / "pdfs" / "32013081219495981000113000000000086326010205340809.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(SAMPLE_HTML_IMPRESSAO, encoding="utf-8")

    resp = client.get("/api/download/file", params={"path": str(html_file)})
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    expected_xml = tmp_path / "xmls" / "32013081219495981000113000000000086326010205340809.xml"
    expected_pdf = tmp_path / "pdfs" / "32013081219495981000113000000000086326010205340809.pdf"
    assert expected_xml.exists()
    assert expected_pdf.exists()


def test_cliente_usuario_senha_sem_certificado_vai_direto_para_html_impressao(tmp_path, monkeypatch):
    """
    Garante que quando o cliente usa usuário e senha e não possui certificado,
    o sistema NÃO tenta fazer download direto de XML ou PDF (/Download/NFSe ou /Download/DANFSe),
    indo diretamente para `obter_impressao_html` e gerando XML e PDF a partir dele.
    """
    from app.api.deps import get_nfse_client
    from app.api.routers.downloads import background_download
    from app.database import SessionLocal
    from app.models import Client, Invoice, init_db

    init_db()
    db = SessionLocal()
    chave = "32013081219495981000113000000000086326010205340809"

    try:
        db.query(Invoice).filter(Invoice.chave == chave).delete()
        db.query(Client).filter(Client.cnpj == "19.495.981/0001-13").delete()
        db.commit()

        client_db = Client(
            cnpj="19.495.981/0001-13",
            razao_social="OTMA SOLUCOES LTDA",
            username="19495981000113",
            password="senha_portal_123",
            cert_path="",
            cert_password="",
            save_path=str(tmp_path),
            path_structure="{CNPJ}/{ANO}/{MES}",
        )
        db.add(client_db)
        db.commit()
        db.refresh(client_db)

        invoice_db = Invoice(
            client_id=client_db.id,
            chave=chave,
            numero=chave,
            status="gerada",
            tipo="emitidas",
            valor=0.0,
            download_url_xml=f"https://www.nfse.gov.br/EmissorNacional/Notas/Download/NFSe/{chave}",
            download_url_pdf=f"https://www.nfse.gov.br/EmissorNacional/Notas/Download/DANFSe/{chave}",
        )
        db.add(invoice_db)
        db.commit()
        db.refresh(invoice_db)

        chamadas_http = []
        chamadas_html = []

        nfse_instance = get_nfse_client(client_db)
        assert nfse_instance.usa_apenas_credenciais() is True

        def fake_enviar_requisicao(metodo, url, **kwargs):
            chamadas_http.append((metodo, url))
            raise AssertionError(f"Não deveria requisitar URL de download direto: {url}")

        def fake_obter_impressao_html(chave_arg):
            chamadas_html.append(chave_arg)
            return SAMPLE_HTML_IMPRESSAO

        monkeypatch.setattr(nfse_instance, "autenticar", lambda *a, **kw: True)
        monkeypatch.setattr(nfse_instance.http, "enviar_requisicao", fake_enviar_requisicao)
        monkeypatch.setattr(nfse_instance, "obter_impressao_html", fake_obter_impressao_html)
        monkeypatch.setattr("app.api.routers.downloads.get_nfse_client", lambda c: nfse_instance)

        background_download("task_test_html_direto", [invoice_db.id], client_db.id, "emitidas")

        db.expire_all()
        updated_inv = db.query(Invoice).filter(Invoice.id == invoice_db.id).first()
        assert chamadas_http == []
        assert chamadas_html == [chave]
        assert updated_inv.xml_path is not None and Path(updated_inv.xml_path).exists()
        assert updated_inv.pdf_path is not None and Path(updated_inv.pdf_path).exists()
        assert updated_inv.pdf_path.endswith(".pdf")
        assert Path(updated_inv.pdf_path).read_bytes().startswith(b"%PDF")
        assert updated_inv.valor == 320.0
        assert updated_inv.numero == "863"
    finally:
        db.query(Invoice).filter(Invoice.chave == chave).delete()
        db.query(Client).filter(Client.cnpj == "19.495.981/0001-13").delete()
        db.commit()
        db.close()

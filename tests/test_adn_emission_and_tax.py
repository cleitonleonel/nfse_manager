"""Suíte completa de testes automatizados do nfse_manager para:
1. CRUD de Clientes com campos fiscais ADN / Sefin Nacional v1.01
2. Endpoints e serviço de Catálogos Fiscais (CST, cClassTrib, cTribNac, LC 116, Anexo VIII, cIndOp, Favoritos)
3. Calculadora Tributária e Validador de Regras IBS/CBS (NT 1.101 / LC 214/2025)
4. Preview, Emissão, Cancelamento (e101101), Substituição (<subst> + e105102) e Parâmetros Municipais via AdnService
"""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Client, Invoice, init_db
from pynfse.adn import (
    DpsSigner,
    XsdValidator,
    build_dps_xml,
    build_evento_cancelamento_xml,
    build_evento_substituicao_xml,
    calcular_tributacao,
    formatar_id_dps,
    listar_cclasstrib,
    listar_cst,
    listar_indop,
    listar_servicos_ctribnac,
    obter_cclasstrib,
    obter_servico_ctribnac,
)


@pytest.fixture(scope="module")
def test_pfx_file(tmp_path_factory) -> tuple[str, str, bytes]:
    """Gera um certificado A1 .pfx RSA-2048 temporário via pynfse.adn.DpsSigner."""
    password = "testpassword123"
    pfx_bytes = DpsSigner.gerar_pfx_autoassinado(
        cnpj="12345678000113",
        razao_social="EMPRESA TESTE LTDA",
        senha=password,
    )
    pfx_dir = tmp_path_factory.mktemp("certs")
    pfx_path = pfx_dir / "test_cert.pfx"
    pfx_path.write_bytes(pfx_bytes)
    return str(pfx_path), password, pfx_bytes


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    init_db()
    return TestClient(app)


# ==============================================================================
# 1. TESTES DE CRUD DE CLIENTES COM CAMPOS FISCAIS ADN v1.01
# ==============================================================================


def test_client_fiscal_fields_crud(api_client: TestClient, test_pfx_file: tuple[str, str, bytes]):
    pfx_path, pfx_password, _ = test_pfx_file
    cnpj_crud = "98765432000198"

    db = SessionLocal()
    try:
        old = db.query(Client).filter(Client.cnpj == cnpj_crud).first()
        if old:
            db.delete(old)
            db.commit()
    finally:
        db.close()

    r_create = api_client.post(
        "/api/clients",
        data={
            "cnpj": cnpj_crud,
            "razao_social": "PRESTADOR FISCAL CRUD LTDA",
            "username": cnpj_crud,
            "password": "secret",
            "cert_password": pfx_password,
            "inscricao_municipal": "123456",
            "codigo_municipio": "5208707",
            "uf": "GO",
            "cep": "74805100",
            "logradouro": "AV T-63",
            "numero": "500",
            "complemento": "SALA 10",
            "bairro": "SETOR BUENO",
            "telefone": "6230001122",
            "email": "fiscal@prestador.com.br",
            "regime_tributario": "simples",
            "regime_apuracao_sn": "1",
            "regime_especial": "0",
            "serie_dps_padrao": "800",
            "ultimo_numero_dps": 5,
            "ambiente_padrao": "homologacao",
        },
        files={"cert_file": ("test.pfx", Path(pfx_path).read_bytes(), "application/x-pkcs12")},
    )
    assert r_create.status_code == 200, r_create.text
    created = r_create.json()
    cid = created["id"]
    assert created["inscricao_municipal"] == "123456"
    assert created["codigo_municipio"] == "5208707"
    assert created["regime_tributario"] == "simples"
    assert created["serie_dps_padrao"] == "800"
    assert created["ultimo_numero_dps"] == 5
    assert "backend/certificados/" in created["cert_path"].replace("\\", "/")
    assert Path(created["cert_path"]).exists()

    # Atualiza campos fiscais via PUT
    r_upd = api_client.put(
        f"/api/clients/{cid}",
        data={
            "regime_tributario": "normal",
            "serie_dps_padrao": "901",
            "ultimo_numero_dps": 12,
        },
    )
    assert r_upd.status_code == 200, r_upd.text
    updated = r_upd.json()
    assert updated["regime_tributario"] == "normal"
    assert updated["serie_dps_padrao"] == "901"
    assert updated["ultimo_numero_dps"] == 12

    # Remove cliente temporário
    r_del = api_client.delete(f"/api/clients/{cid}")
    assert r_del.status_code == 200


# ==============================================================================
# 2. TESTES DOS CATÁLOGOS FISCAIS (cClassTrib, CST, cTribNac, LC 116, Anexo VIII, cIndOp)
# ==============================================================================


def test_catalog_counts_and_lookup():
    assert len(listar_cst()) == 18
    assert len(listar_cclasstrib(apenas_nfse=False)) == 138
    assert len(listar_servicos_ctribnac()) == 338
    assert len(listar_indop()) == 28

    ct_saude = obter_cclasstrib("200029")
    assert ct_saude is not None
    assert ct_saude["cst"] == "200"
    assert ct_saude["perc_red_ibs"] == 60.0
    assert ct_saude["perc_red_cbs"] == 60.0

    ct_prouni = obter_cclasstrib("200025")
    assert ct_prouni is not None
    assert ct_prouni["perc_red_ibs"] == 60.0
    assert ct_prouni["perc_red_cbs"] == 100.0

    srv = obter_servico_ctribnac("010101")
    assert srv is not None
    assert srv["item_lc116"] == "01.01"
    assert "Análise e desenvolvimento de sistemas" in srv["descricao"]


def test_catalog_api_endpoints_comprehensive(api_client: TestClient):
    r_cst = api_client.get("/api/catalogs/cst")
    assert r_cst.status_code == 200
    assert len(r_cst.json()) == 18

    r_cst_nfse = api_client.get("/api/catalogs/cst", params={"apenas_nfse": True})
    assert r_cst_nfse.status_code == 200
    assert len(r_cst_nfse.json()) > 5

    r_ct = api_client.get("/api/catalogs/cclasstrib", params={"cst": "200"})
    assert r_ct.status_code == 200
    assert len(r_ct.json()) > 30

    r_ct_anexo = api_client.get("/api/catalogs/cclasstrib", params={"apenas_anexo_viii": True})
    assert r_ct_anexo.status_code == 200
    assert len(r_ct_anexo.json()) == 27

    r_ct_detail = api_client.get("/api/catalogs/cclasstrib/200029")
    assert r_ct_detail.status_code == 200
    assert r_ct_detail.json()["cst"] == "200"

    r_ct_404 = api_client.get("/api/catalogs/cclasstrib/999999")
    assert r_ct_404.status_code == 404

    r_srv = api_client.get("/api/catalogs/servicos", params={"q": "sistemas"})
    assert r_srv.status_code == 200
    assert len(r_srv.json()) >= 1

    r_srv_detail = api_client.get("/api/catalogs/servicos/010101")
    assert r_srv_detail.status_code == 200
    assert len(r_srv_detail.json()["correlacoes_anexo_viii"]) >= 1

    r_srv_404 = api_client.get("/api/catalogs/servicos/999999")
    assert r_srv_404.status_code == 404

    r_lc116 = api_client.get("/api/catalogs/lc116")
    assert r_lc116.status_code == 200
    assert len(r_lc116.json()) > 100

    r_corr = api_client.get(
        "/api/catalogs/correlacoes",
        params={"c_trib_nac": "010101", "c_class_trib": "000001"},
    )
    assert r_corr.status_code == 200
    assert len(r_corr.json()) >= 1

    r_indop = api_client.get("/api/catalogs/indop")
    assert r_indop.status_code == 200
    assert len(r_indop.json()) == 28

    r_fav = api_client.get("/api/catalogs/favoritos")
    assert r_fav.status_code == 200
    assert len(r_fav.json()) >= 6


# ==============================================================================
# 3. TESTES DA CALCULADORA TRIBUTÁRIA E REGRAS IBS/CBS (NT 1.101 / LC 214/2025)
# ==============================================================================


def test_tax_calculator_2026_vs_2027_vs_2033_and_reductions():
    # Cenário 1: Regime Normal em 2026 - Tributação Integral (000001)
    res_2026 = calcular_tributacao(
        valor_servicos=10000.00,
        ano_competencia=2026,
        regime_prestador="normal",
        aliquota_iss_informada=5.0,
        iss_retido=False,
        reter_federais=True,
        cClassTrib="000001",
        p_ibs_uf=0.10,
        p_ibs_mun=0.00,
        p_cbs=0.90,
    )
    assert res_2026["iss"]["valor"] == 500.00
    assert res_2026["retencoes_federais"]["pis"] == 65.00
    assert res_2026["retencoes_federais"]["cofins"] == 300.00
    # vBC = 10000 - 500 (ISS) - 65 (PIS) - 300 (COFINS) = 9135.00
    assert res_2026["reforma_tributaria"]["vBC"] == 9135.00
    assert res_2026["reforma_tributaria"]["valor_ibs_uf"] == 9.13
    assert res_2026["reforma_tributaria"]["valor_cbs"] == 82.22
    assert res_2026["valor_total_nf"] == res_2026["valor_liquido"]

    # Cenário 2: Em 2027, PIS/COFINS são extintos e vTotNF soma IBS + CBS por fora
    res_2027 = calcular_tributacao(
        valor_servicos=10000.00,
        ano_competencia=2027,
        regime_prestador="normal",
        aliquota_iss_informada=5.0,
        iss_retido=False,
        reter_federais=False,
        cClassTrib="000001",
        p_ibs_uf=0.05,
        p_ibs_mun=0.05,
        p_cbs=8.80,
    )
    assert res_2027["reforma_tributaria"]["vBC"] == 9500.00
    assert res_2027["valor_total_nf"] == round(
        res_2027["valor_liquido"]
        + res_2027["reforma_tributaria"]["valor_ibs"]
        + res_2027["reforma_tributaria"]["valor_cbs"],
        2,
    )

    # Cenário 3: Em 2033+, ISSQN também é extinto (vBC não deduz ISSQN)
    res_2033 = calcular_tributacao(
        valor_servicos=10000.00,
        ano_competencia=2033,
        regime_prestador="normal",
        aliquota_iss_informada=5.0,
        cClassTrib="000001",
        desconto_incondicionado=200.0,
        reembolso_repasse_ressarcimento=300.0,
        deducao_reducao_ibscbs=500.0,
    )
    assert res_2033["reforma_tributaria"]["vBC"] == 9000.00

    # Cenário 4: Saúde (200029 -> redução de 60% na alíquota)
    res_saude = calcular_tributacao(
        valor_servicos=1000.00,
        ano_competencia=2026,
        regime_prestador="normal",
        aliquota_iss_informada=2.0,
        cClassTrib="200029",
        p_ibs_uf=1.00,
        p_ibs_mun=0.50,
        p_cbs=2.00,
    )
    assert res_saude["reforma_tributaria"]["cst"] == "200"
    assert res_saude["reforma_tributaria"]["ibs_uf"]["pRedAliqUF"] == 60.0
    assert res_saude["reforma_tributaria"]["ibs_uf"]["pAliqEfetUF"] == 0.40
    assert res_saude["reforma_tributaria"]["ibs_mun"]["pAliqEfetMun"] == 0.20
    assert res_saude["reforma_tributaria"]["cbs"]["pAliqEfetCBS"] == 0.80

    # Cenário 5: Prouni (200025 -> redução assimétrica: 60% IBS e 100% CBS)
    res_prouni = calcular_tributacao(
        valor_servicos=1000.00,
        ano_competencia=2026,
        regime_prestador="normal",
        aliquota_iss_informada=2.0,
        cClassTrib="200025",
        p_ibs_uf=1.00,
        p_ibs_mun=0.0,
        p_cbs=2.00,
    )
    assert res_prouni["reforma_tributaria"]["ibs_uf"]["pRedAliqUF"] == 60.0
    assert res_prouni["reforma_tributaria"]["cbs"]["pRedAliqCBS"] == 100.0
    assert res_prouni["reforma_tributaria"]["valor_cbs"] == 0.00

    # Cenário 6: Profissão Regulamentada (200052 -> redução de 30%) e Locação Imóvel (200027 -> redução de 70%)
    res_prof = calcular_tributacao(
        valor_servicos=1000.00,
        ano_competencia=2026,
        regime_prestador="normal",
        cClassTrib="200052",
        p_ibs_uf=1.00,
        p_cbs=1.00,
    )
    assert res_prof["reforma_tributaria"]["ibs_uf"]["pRedAliqUF"] == 30.0
    assert res_prof["reforma_tributaria"]["cbs"]["pRedAliqCBS"] == 30.0

    res_loc = calcular_tributacao(
        valor_servicos=1000.00,
        ano_competencia=2026,
        regime_prestador="normal",
        cClassTrib="200027",
        p_ibs_uf=1.00,
        p_cbs=1.00,
    )
    assert res_loc["reforma_tributaria"]["ibs_uf"]["pRedAliqUF"] == 70.0
    assert res_loc["reforma_tributaria"]["cbs"]["pRedAliqCBS"] == 70.0


def test_tax_api_special_regimes_and_validation_rules(api_client: TestClient):
    # 1. Endpoint /api/tax/calculate com Diferimento, Crédito Presumido, Tributação Regular e Compra Governamental
    r_calc = api_client.post(
        "/api/tax/calculate",
        json={
            "valor_servicos": 10000.0,
            "regime_prestador": "simples",
            "apurar_ibscbs_simples": True,
            "cClassTrib": "200029",
            "cIndOp": "030101",
            "cTribNac": "040101",
            "ano_competencia": 2027,
            "iss_retido": True,
            "p_ibs_uf": 1.0,
            "p_ibs_mun": 0.5,
            "p_cbs": 2.0,
            "p_dif_uf": 50.0,
            "c_cred_pres": "01",
            "p_cred_pres_ibs": 2.0,
            "p_cred_pres_cbs": 3.0,
            "cst_reg": "000",
            "c_class_trib_reg": "000001",
            "tp_ente_gov": 1,
            "p_redutor_gov": 10.0,
        },
    )
    assert r_calc.status_code == 200
    calc_json = r_calc.json()
    assert calc_json["iss"]["retido"] is True
    assert calc_json["reforma_tributaria"]["ibs_uf"]["vDifUF"] > 0
    assert calc_json["reforma_tributaria"]["credito_presumido"]["cCredPres"] == "01"
    assert calc_json["reforma_tributaria"]["tributacao_regular"]["cClassTribReg"] == "000001"
    assert calc_json["reforma_tributaria"]["compras_governamentais"]["tpEnteGov"] == 1

    # 2. CST incompatível com cClassTrib -> erro E0959
    r_bad = api_client.post(
        "/api/tax/validate-ibscbs",
        json={"cClassTrib": "200029", "cst": "000", "cIndOp": "030101"},
    )
    assert r_bad.status_code == 200
    assert r_bad.json()["valido"] is False
    assert any("E0959" in err["codigo"] for err in r_bad.json()["erros"])

    # 3. cClassTrib inexistente -> erro E0958
    r_not_found = api_client.post(
        "/api/tax/validate-ibscbs",
        json={"cClassTrib": "999999", "cst": "999"},
    )
    assert r_not_found.status_code == 200
    assert r_not_found.json()["valido"] is False
    assert any("E0958" in err["codigo"] for err in r_not_found.json()["erros"])

    # 4. Construção civil (070201) com grupo imóvel em IBSCBS -> erro E0931
    r_imovel = api_client.post(
        "/api/tax/validate-ibscbs",
        json={
            "cClassTrib": "200027",
            "cst": "200",
            "cIndOp": "020101",
            "cTribNac": "070201",
            "temImovel": True,
        },
    )
    assert r_imovel.status_code == 200
    assert r_imovel.json()["valido"] is False
    assert any("E0931" in err["codigo"] for err in r_imovel.json()["erros"])

    # 5. tpOper = 2 sem gRefNFSe -> erro E0905; indDest = 0 com destinatário -> erro E0910
    r_oper = api_client.post(
        "/api/tax/validate-ibscbs",
        json={
            "cClassTrib": "000001",
            "cst": "000",
            "tpOper": 2,
            "temRefNFSe": False,
            "indDest": 0,
            "temDestinatario": True,
        },
    )
    assert r_oper.status_code == 200
    codigos_erro = {e["codigo"] for e in r_oper.json()["erros"]}
    assert "E0905" in codigos_erro
    assert "E0910" in codigos_erro

    # 6. Doação / Estorno de crédito (410026) sem indDoacao -> erro E0966
    r_doacao = api_client.post(
        "/api/tax/validate-ibscbs",
        json={"cClassTrib": "410026", "cst": "410"},
    )
    assert r_doacao.status_code == 200
    assert any("E0966" in e["codigo"] for e in r_doacao.json()["erros"])


# ==============================================================================
# 4. TESTES DE PREVIEW, EMISSÃO, CANCELAMENTO, SUBSTITUIÇÃO E PARÂMETROS MUNICIPAIS
# ==============================================================================


def test_dps_evento_xsd_and_xmldsig(test_pfx_file: tuple[str, str, bytes]):
    pfx_path, pfx_password, _ = test_pfx_file
    signer = DpsSigner(pfx_path=pfx_path, pfx_password=pfx_password)

    prestador = {
        "cnpj": "12345678000113",
        "codigo_municipio": "5208707",
        "regime": "simples",
        "reg_ap_trib_sn": "1",
        "reg_esp_trib": "0",
    }
    tomador = {
        "documento": "12345678000195",
        "razao_social": "CLIENTE TESTE LTDA",
        "endereco": {
            "codigo_municipio": "5208707",
            "cep": "74805100",
            "logradouro": "AV T-63",
            "numero": "1200",
            "bairro": "SETOR BUENO",
        },
    }
    servico = {
        "codigo_municipio_prestacao": "5208707",
        "cTribNac": "010101",
        "descricao": "Desenvolvimento de sistema web sob encomenda",
        "cNBS": "115021000",
        "valor": 2500.00,
        "cClassTrib": "000001",
        "indop": "030101",
    }
    tributacao = calcular_tributacao(
        valor_servicos=2500.00,
        regime_prestador="simples",
        cClassTrib="000001",
        cIndOp="030101",
        cTribNac="010101",
        cNBS="115021000",
    )

    xml_dps = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        intermediario=None,
        servico=servico,
        tributacao=tributacao,
        serie_dps="900",
        numero_dps=123,
        ambiente="homologacao",
        incluir_ibscbs=True,
    )
    id_dps = formatar_id_dps("5208707", "12345678000113", "900", 123)
    assert len(id_dps) == 45
    assert id_dps.startswith("DPS")

    val_unsigned = XsdValidator.validar_dps(xml_dps)
    assert val_unsigned["valido"] is True, val_unsigned["erros"]

    xml_dps_signed = signer.sign_xml(xml_dps, tag_to_sign="infDPS")
    val_signed = XsdValidator.validar_dps(xml_dps_signed)
    assert val_signed["valido"] is True, val_signed["erros"]

    chave_50 = "52087072212345678000113202604000000000012310123456"
    xml_canc = build_evento_cancelamento_xml(
        chave_nfse=chave_50,
        documento_autor="12345678000113",
        motivo_codigo=1,
        motivo_descricao="Erro no preenchimento da discriminacao do servico prestado",
        ambiente=2,
    )
    val_canc = XsdValidator.validar_evento(signer.sign_xml(xml_canc, tag_to_sign="infPedReg"))
    assert val_canc["valido"] is True, val_canc["erros"]

    chave_substituta = "52087072212345678000113202604000000000012410654321"
    xml_subst_evt = build_evento_substituicao_xml(
        chave_nfse_substituida=chave_50,
        chave_nfse_substituta=chave_substituta,
        documento_autor="12345678000113",
        motivo_codigo="02",
        motivo_descricao="Substituicao da nota fiscal por alteracao de valor do servico",
        ambiente=2,
    )
    val_subst_evt = XsdValidator.validar_evento(signer.sign_xml(xml_subst_evt, tag_to_sign="infPedReg"))
    assert val_subst_evt["valido"] is True, val_subst_evt["erros"]


def test_emission_api_endpoints_offline_and_online_mocked(
    api_client: TestClient, test_pfx_file: tuple[str, str, bytes]
):
    pfx_path, pfx_password, pfx_bytes = test_pfx_file
    pfx_b64 = base64.b64encode(pfx_bytes).decode("ascii")

    db = SessionLocal()
    try:
        existing = db.query(Client).filter(Client.cnpj == "12345678000113").first()
        if existing:
            db.query(Invoice).filter(Invoice.client_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        client_obj = Client(
            razao_social="EMPRESA TESTE EMISSAO ADN LTDA",
            cnpj="12345678000113",
            username="12345678000113",
            password="123",
            cert_path=pfx_path,
            cert_password=pfx_password,
            codigo_municipio="5208707",
            uf="GO",
            regime_tributario="simples",
            regime_apuracao_sn="1",
            regime_especial="0",
            serie_dps_padrao="900",
            ultimo_numero_dps=10,
            ambiente_padrao="homologacao",
        )
        db.add(client_obj)
        db.commit()
        db.refresh(client_obj)
        client_id = client_obj.id
    finally:
        db.close()

    tomador_payload = {
        "documento": "12345678000195",
        "razao_social": "TOMADOR TESTE S.A.",
        "endereco": {
            "codigo_municipio": "5208707",
            "cep": "74805100",
            "logradouro": "AV T-63",
            "numero": "100",
            "bairro": "SETOR BUENO",
        },
    }
    servico_payload = {
        "codigo_municipio_prestacao": "5208707",
        "cTribNac": "010101",
        "descricao": "Consultoria e desenvolvimento em tecnologia da informacao",
        "cNBS": "115021000",
        "valor": 5000.00,
        "cClassTrib": "000001",
        "indop": "030101",
    }

    # 1. Preview DPS (/api/adn/dps/preview)
    r_prev = api_client.post(
        "/api/adn/dps/preview",
        json={
            "client_id": client_id,
            "tomador": tomador_payload,
            "servico": servico_payload,
        },
    )
    assert r_prev.status_code == 200, r_prev.text
    assert r_prev.json()["validacao_xsd"]["valido"] is True
    assert r_prev.json()["numero_dps"] == 11

    # 2. Emitir DPS com transmissão online mockada (transmitir=True) e certificado via Base64
    chave_autorizada = "52087072212345678000113202604000000000001110123456"
    with patch(
        "app.services.adn_service.AdnNfseClient.emitir_dps",
        new_callable=AsyncMock,
        return_value={
            "sucesso": True,
            "status_code": 201,
            "chave_acesso": chave_autorizada,
            "nfse_xml": "<NFSe versao='1.01'/>",
            "mensagem": "Autorizada com sucesso",
        },
    ):
        r_emit = api_client.post(
            "/api/adn/dps/emitir",
            json={
                "client_id": client_id,
                "transmitir": True,
                "certificado_pfx_b64": pfx_b64,
                "senha_certificado": pfx_password,
                "tomador": tomador_payload,
                "servico": servico_payload,
            },
        )
    assert r_emit.status_code == 200, r_emit.text
    emit_data = r_emit.json()
    assert emit_data["validacao_xsd"]["valido"] is True
    assert emit_data["assinado_com_certificado"] is True
    assert emit_data["chave_acesso"] == chave_autorizada
    assert emit_data["envio_adn"]["sucesso"] is True
    assert "backend/downloads/adn/dps/" in emit_data["xml_dps_path"].replace("\\", "/")
    invoice_id_emitida = emit_data["invoice_id"]

    # 3. Substituir a NFS-e recém-emitida (/api/adn/nfse/substituir) com transmissão online mockada
    chave_substituta_online = "52087072212345678000113202604000000000001210654321"
    with patch(
        "app.services.adn_service.AdnNfseClient.emitir_dps",
        new_callable=AsyncMock,
        return_value={
            "sucesso": True,
            "status_code": 201,
            "chave_acesso": chave_substituta_online,
            "mensagem": "Substituta autorizada",
        },
    ):
        r_subst = api_client.post(
            "/api/adn/nfse/substituir",
            json={
                "client_id": client_id,
                "invoice_id_substituida": invoice_id_emitida,
                "chave_nfse_substituida": chave_autorizada,
                "motivo_codigo": "02",
                "motivo_descricao": "Substituicao de NFS-e para retificacao do valor do servico prestado",
                "transmitir": True,
                "tomador": tomador_payload,
                "servico": {**servico_payload, "valor": 6000.00},
            },
        )
    assert r_subst.status_code == 200, r_subst.text
    subst_data = r_subst.json()
    assert subst_data["validacao_xsd_dps"]["valido"] is True
    assert subst_data["validacao_xsd_evento_e105102"]["valido"] is True
    assert subst_data["chave_nfse_substituta"] == chave_substituta_online
    assert f"<chSubstda>{chave_autorizada}</chSubstda>" in subst_data["xml_dps_substituta"]

    # Verifica que a nota original ficou com status='substituida' no banco
    db = SessionLocal()
    try:
        inv_orig = db.query(Invoice).filter(Invoice.id == invoice_id_emitida).first()
        assert inv_orig is not None
        assert inv_orig.status == "substituida"
        assert inv_orig.chave_substituta == chave_substituta_online
    finally:
        db.close()

    # 4. Cancelar a NFS-e substituta (/api/adn/nfse/cancelar) com transmissão online mockada
    with patch(
        "app.services.adn_service.AdnNfseClient.enviar_evento",
        new_callable=AsyncMock,
        return_value={"sucesso": True, "status_code": 200, "resposta": {"ok": True}},
    ):
        r_canc = api_client.post(
            "/api/adn/nfse/cancelar",
            json={
                "client_id": client_id,
                "chave_nfse": chave_substituta_online,
                "motivo_codigo": 1,
                "motivo_descricao": "Cancelamento de nota fiscal emitida em duplicidade no teste",
                "transmitir": True,
            },
        )
    assert r_canc.status_code == 200, r_canc.text
    canc_data = r_canc.json()
    assert canc_data["validacao_xsd"]["valido"] is True
    assert "<e101101>" in canc_data["xml_assinado"]

    db = SessionLocal()
    try:
        inv_sub = db.query(Invoice).filter(Invoice.chave == chave_substituta_online).first()
        assert inv_sub is not None
        assert inv_sub.status == "cancelada"
        assert inv_sub.data_cancelamento is not None
    finally:
        db.close()

    # 5. Consultar parâmetros municipais (/api/adn/parametros-municipais/{cod_ibge})
    with patch(
        "app.services.adn_service.AdnNfseClient.consultar_parametros_municipais",
        new_callable=AsyncMock,
        return_value={"sucesso": True, "status_code": 200, "municipio": "5208707", "dados": {"convenio": "ATIVO"}},
    ):
        r_mun = api_client.get("/api/adn/parametros-municipais/5208707")
    assert r_mun.status_code == 200
    assert r_mun.json()["sucesso"] is True
    assert r_mun.json()["dados"]["convenio"] == "ATIVO"

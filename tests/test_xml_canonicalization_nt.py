import base64
import hashlib
from lxml import etree

from pynfse.adn import (
    DpsSigner,
    Endereco,
    Prestador,
    Servico,
    Substituicao,
    Tomador,
    XsdValidator,
    build_dps_xml,
    build_evento_cancelamento_xml,
    build_evento_substituicao_xml,
)

DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def _canonicalize_element(el: etree._Element, exclusive: bool = False) -> bytes:
    """Canonicaliza um elemento XML conforme C14N 1.0 (inclusive ou exclusivo)."""
    return etree.tostring(el, method="c14n", exclusive=exclusive)


def _assert_no_empty_leaf_tags(xml_str: str) -> None:
    """Garante ausência de tags folha vazias no XML final (ex.: <xCpl/>)."""
    root = etree.fromstring(xml_str.encode("utf-8"))
    empties = [
        el.tag
        for el in root.iter()
        if len(el) == 0 and (el.text is None or el.text == "") and len(el.attrib) == 0
    ]
    assert empties == [], f"Tags vazias encontradas no XML: {empties}"


def _build_base_actors():
    prestador = Prestador(
        cnpj="12345678000113",
        inscricao_municipal="123456",
        razao_social="Tech Solutions NT Ltda",
        codigo_municipio="3201308",
        regime="normal",
        endereco=Endereco(
            logradouro="Av. Central",
            numero="100",
            bairro="Centro",
            codigo_municipio="3201308",
            uf="ES",
            cep="29160000",
        ),
    )
    tomador = Tomador(
        cnpj="98765432000199",
        razao_social="Cliente Tomador Corporativo S.A.",
        email="financeiro@tomador.example",
        endereco=Endereco(
            logradouro="Rua das Flores",
            numero="250",
            bairro="Jardim",
            codigo_municipio="3550308",
            uf="SP",
            cep="01001000",
        ),
    )
    return prestador, tomador


def test_c14n_determinism_and_strict_order_nt_2026():
    prestador, tomador = _build_base_actors()
    servico = Servico(
        valor=2500.00,
        cTribNac="010101",
        cNBS="115021000",
        cClassTrib="000001",
        cst="000",
        indop="100301",
        descricao="Desenvolvimento e licenciamento de sistemas em nuvem",
        codigo_municipio_prestacao="3201308",
        aliquota_iss=2.0,
    )

    xml_1 = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        servico=servico,
        serie_dps="900",
        numero_dps=101,
        data_competencia="2026-06-15",
        data_emissao="2026-06-15T10:00:00-03:00",
        ambiente="homologacao",
        incluir_ibscbs=True,
    )
    xml_2 = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        servico=servico,
        serie_dps="900",
        numero_dps=101,
        data_competencia="2026-06-15",
        data_emissao="2026-06-15T10:00:00-03:00",
        ambiente="homologacao",
        incluir_ibscbs=True,
    )

    assert xml_1 == xml_2
    _assert_no_empty_leaf_tags(xml_1)

    xsd = XsdValidator.validar_dps(xml_1)
    assert xsd["valido"] is True, xsd

    root = etree.fromstring(xml_1.encode("utf-8"))
    ns = {"n": root.nsmap[None]}
    inf_dps = root.find("n:infDPS", namespaces=ns)
    assert inf_dps is not None

    child_names = [etree.QName(child).localname for child in inf_dps]
    expected_prefix = [
        "tpAmb",
        "dhEmi",
        "verAplic",
        "serie",
        "nDPS",
        "dCompet",
        "tpEmit",
        "cLocEmi",
        "prest",
        "toma",
        "serv",
        "valores",
    ]
    assert child_names[: len(expected_prefix)] == expected_prefix

    c14n_a = _canonicalize_element(inf_dps)
    c14n_b = _canonicalize_element(etree.fromstring(xml_2.encode("utf-8")).find("n:infDPS", namespaces=ns))
    assert hashlib.sha256(c14n_a).hexdigest() == hashlib.sha256(c14n_b).hexdigest()


def test_c14n_and_xmldsig_digest_value_integrity():
    prestador, tomador = _build_base_actors()
    servico = Servico(
        valor=1800.00,
        cTribNac="010101",
        cNBS="115021000",
        cClassTrib="000001",
        cst="000",
        indop="100301",
        descricao="Consultoria técnica especializada",
        codigo_municipio_prestacao="3201308",
    )

    xml_raw = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        servico=servico,
        serie_dps="900",
        numero_dps=102,
        data_competencia="2026-07-01",
        data_emissao="2026-07-01T09:30:00-03:00",
        ambiente="homologacao",
        incluir_ibscbs=True,
    )

    pfx_bytes = DpsSigner.gerar_pfx_autoassinado(
        cnpj="12345678000113",
        razao_social="Tech Solutions NT Ltda",
        senha="test-password",
    )
    signer = DpsSigner(pfx_data=pfx_bytes, pfx_password="test-password")

    signed_1 = signer.sign_xml(xml_raw, tag_to_sign="infDPS")
    signed_2 = signer.sign_xml(xml_raw, tag_to_sign="infDPS")

    xsd = XsdValidator.validar_dps(signed_1)
    assert xsd["valido"] is True, xsd

    root_1 = etree.fromstring(signed_1.encode("utf-8"))
    root_2 = etree.fromstring(signed_2.encode("utf-8"))

    digest_1 = root_1.findtext(f".//{{{DS_NS}}}DigestValue")
    digest_2 = root_2.findtext(f".//{{{DS_NS}}}DigestValue")
    assert digest_1 and digest_1 == digest_2

    transforms = [
        el.get("Algorithm", "")
        for el in root_1.findall(f".//{{{DS_NS}}}Transform")
    ]
    assert "http://www.w3.org/2000/09/xmldsig#enveloped-signature" in transforms
    assert any("c14n" in alg for alg in transforms)

    # Verificação criptográfica completa (C14N + DigestValue + SignatureValue) via signxml
    from signxml import XMLVerifier

    verified = XMLVerifier().verify(signed_1.encode("utf-8"), x509_cert=signer.get_pem_certificate())
    assert verified.signed_xml is not None
    expected_digest = base64.b64encode(hashlib.sha256(verified.signed_data).digest()).decode("ascii")
    assert digest_1 == expected_digest


def test_nt_2026_health_reduction_and_2027_and_substitution_order():
    prestador, tomador = _build_base_actors()

    # Cenário 1: NT Saúde com redução / cClassTrib específico (ex.: 200029)
    srv_saude = Servico(
        valor=1200.00,
        cTribNac="040101",
        cNBS="123011100",
        cClassTrib="200029",
        cst="200",
        indop="100301",
        descricao="Atendimento médico ambulatorial",
        codigo_municipio_prestacao="3201308",
    )
    xml_saude = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        servico=srv_saude,
        serie_dps="900",
        numero_dps=103,
        data_competencia="2026-08-10",
        data_emissao="2026-08-10T14:00:00-03:00",
        ambiente="homologacao",
        incluir_ibscbs=True,
    )
    _assert_no_empty_leaf_tags(xml_saude)
    assert XsdValidator.validar_dps(xml_saude)["valido"] is True
    assert "<cClassTrib>200029</cClassTrib>" in xml_saude

    # Cenário 2: Competência 2027 + Substituição
    srv_2027 = Servico(
        valor=3500.00,
        cTribNac="010101",
        cNBS="115021000",
        cClassTrib="000001",
        cst="000",
        indop="100301",
        descricao="Manutenção evolutiva competência 2027",
        codigo_municipio_prestacao="3201308",
    )
    xml_subst = build_dps_xml(
        prestador=prestador,
        tomador=tomador,
        servico=srv_2027,
        serie_dps="900",
        numero_dps=104,
        data_competencia="2027-01-15",
        data_emissao="2027-01-15T11:00:00-03:00",
        ambiente="homologacao",
        substituicao=Substituicao(
            chSubstda="32013082212345678000113000000000000126061234567890",
            cMotivo="01",
            xMotivo="Retificação de valor da competência anterior",
        ),
        incluir_ibscbs=True,
    )
    _assert_no_empty_leaf_tags(xml_subst)
    xsd_subst = XsdValidator.validar_dps(xml_subst)
    assert xsd_subst["valido"] is True, xsd_subst

    root_subst = etree.fromstring(xml_subst.encode("utf-8"))
    ns = {"n": root_subst.nsmap[None]}
    inf_dps_subst = root_subst.find("n:infDPS", namespaces=ns)
    order_subst = [etree.QName(c).localname for c in inf_dps_subst]
    assert order_subst.index("cLocEmi") < order_subst.index("subst") < order_subst.index("prest")


def test_nt_events_cancelamento_and_substituicao_c14n_and_xsd():
    chave_orig = "32013082212345678000113000000000000126061234567890"
    chave_nova = "32013082212345678000113000000000000226061234567891"

    ev_cancel_1 = build_evento_cancelamento_xml(
        chave_nfse=chave_orig,
        documento_autor="12345678000113",
        motivo_codigo=1,
        motivo_descricao="Erro na identificação do serviço prestado.",
        ambiente=2,
        data_evento="2026-06-15T15:00:00-03:00",
    )
    ev_cancel_2 = build_evento_cancelamento_xml(
        chave_nfse=chave_orig,
        documento_autor="12345678000113",
        motivo_codigo=1,
        motivo_descricao="Erro na identificação do serviço prestado.",
        ambiente=2,
        data_evento="2026-06-15T15:00:00-03:00",
    )
    assert ev_cancel_1 == ev_cancel_2
    _assert_no_empty_leaf_tags(ev_cancel_1)
    assert "<e101101>" in ev_cancel_1
    xsd_cancel = XsdValidator.validar_evento(ev_cancel_1)
    assert xsd_cancel["valido"] is True, xsd_cancel

    ev_subst = build_evento_substituicao_xml(
        chave_nfse_substituida=chave_orig,
        chave_nfse_substituta=chave_nova,
        documento_autor="12345678000113",
        motivo_codigo="01",
        motivo_descricao="Substituição por alteração cadastral do tomador.",
        ambiente=2,
        data_evento="2026-06-15T15:05:00-03:00",
    )
    _assert_no_empty_leaf_tags(ev_subst)
    assert "<e105102>" in ev_subst
    xsd_subst = XsdValidator.validar_evento(ev_subst)
    assert xsd_subst["valido"] is True, xsd_subst

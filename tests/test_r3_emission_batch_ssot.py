"""Testes abrangentes para Milestone M2 (F08–F12):
- F08: Cofre ADN (`sincronizar_cofre_adn`): envio de `cnpj`, tratamento de erros (página 1 -> 502; página > 1 -> parcial), eventos XML (`<evento>` e101101/e105102) e proteção anti-IDOR/RBAC
- F09: Batch SSoT (`valor_deducao` vs `desconto_incondicionado`, defaults ISS por regime, `cIndOp`/`cNBS`, whitespace bool, zero-padding, RBAC/PG ordering no lookup de cadastros)
- F10: Batch Processor (`try/except` por item sem travar em `PROCESSING`, recuperação stale, `EmailService.enviar_nfse_por_email`, `consultar_nfse` `conteudo`, `list_batches` SQL RBAC antes do `LIMIT`, `AuditService`)
- F11: `_calcular_tributacao_se_necessario` (preservação de `0.0` e 51 campos NT 1.101), `emitir_dps` (pré-validação antes de reservar DPS, `4xx` -> `rejeitada`, e-mail somente `gerada`), `emitir_dps_lote`
- F12: `cancelar_nfse` / `substituir_nfse` (validação `400`/`404` mismatch, zero mutação em falha ADN, XML/PDF da substituta), `reenviar_fila_contingencia` (`consultar_dps` idempotente, `4xx` -> `rejeitada`, sync `BatchImportItem`), `POST /api/adn/fila/{id}/consultar`, `SchedulerService` sem `FOR UPDATE` e `AuditService`
"""

from __future__ import annotations

import datetime
import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import openpyxl
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pynfse.adn import AdnNfseClient, DpsSigner
from sqlalchemy import event

from app.api.state import tasks_status
from app.core.migrations import create_admin_user
from app.database import SessionLocal, engine
from app.main import app
from app.models import (
    AuditLog,
    BackgroundTask,
    BatchImport,
    BatchImportItem,
    Client,
    Customer,
    Invoice,
    ServiceItem,
    User,
    UserClient,
    init_db,
)
from app.schemas import TaxCalculationRequest
from app.services.adn_service import AdnService
from app.services.batch_emission.processor import recover_stale_processing_batch
from app.services.batch_emission.validator import build_tax_validation_request, validate_batch_item
from app.services.scheduler_service import SchedulerService

client = TestClient(app)


def _reset_db() -> None:
    init_db()
    tasks_status.clear()
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.query(UserClient).delete()
        db.query(BatchImportItem).delete()
        db.query(BatchImport).delete()
        db.query(Invoice).delete()
        db.query(Customer).delete()
        db.query(ServiceItem).delete()
        db.query(Client).delete()
        db.query(User).delete()
        db.query(BackgroundTask).delete()
        db.commit()
    finally:
        db.close()


def _login_headers(username: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_operator(
    admin_headers: dict[str, str],
    username: str,
    password: str = "OpPass123",
    client_ids: list[int] | None = None,
) -> dict:
    payload: dict = {
        "username": username,
        "email": f"{username}@empresa.com.br",
        "full_name": username.upper(),
        "password": password,
        "role": "operador",
    }
    if client_ids is not None:
        payload["client_ids"] = client_ids
    res = client.post("/api/auth/users", headers=admin_headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _make_pfx(tmp_path: Path, cnpj: str, password: str = "senha_cert_m2") -> Path:
    pfx_bytes = DpsSigner.gerar_pfx_autoassinado(
        cnpj=cnpj,
        razao_social=f"EMPRESA {cnpj} LTDA",
        senha=password,
    )
    p = tmp_path / f"{cnpj}.pfx"
    p.write_bytes(pfx_bytes)
    return p


def _create_client_db(
    tmp_path: Path,
    cnpj: str,
    *,
    regime: str = "normal",
    with_cert: bool = True,
    ultimo_numero_dps: int = 0,
    smtp_host: str | None = None,
    enviar_email_automatico: int = 0,
) -> int:
    cert_path = str(_make_pfx(tmp_path, cnpj)) if with_cert else None
    db = SessionLocal()
    try:
        cli = Client(
            razao_social=f"PRESTADOR {cnpj} LTDA",
            cnpj=cnpj,
            username=cnpj,
            password="portal_pwd",
            cert_path=cert_path,
            cert_password="senha_cert_m2" if with_cert else None,
            codigo_municipio="3201308",
            uf="ES",
            regime_tributario=regime,
            regime_apuracao_sn="1",
            regime_especial="0",
            serie_dps_padrao="900",
            ultimo_numero_dps=ultimo_numero_dps,
            ambiente_padrao="homologacao",
            smtp_host=smtp_host,
            smtp_port=587 if smtp_host else None,
            smtp_user="no-reply@empresa.example" if smtp_host else None,
            smtp_password="smtp_pwd" if smtp_host else None,
            smtp_from="no-reply@empresa.example" if smtp_host else None,
            smtp_tls=1,
            enviar_email_automatico=enviar_email_automatico,
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)
        return cli.id
    finally:
        db.close()


def _isolate_storage(monkeypatch, tmp_path: Path) -> None:
    certs_dir = tmp_path / "certs"
    dl_dir = tmp_path / "downloads"
    certs_dir.mkdir(parents=True, exist_ok=True)
    dl_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NFSE_CERTS_DIR", str(certs_dir))
    monkeypatch.setenv("NFSE_DOWNLOADS_DIR", str(dl_dir))


# ==============================================================================
# F08 — Cofre ADN (`sincronizar_cofre_adn`)
# ==============================================================================


def test_f08_cofre_adn_passes_cnpj_handles_failures_and_events(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    cid = _create_client_db(tmp_path, "11222333000181", with_cert=True)
    cid_no_cert = _create_client_db(tmp_path, "22333444000171", with_cert=False)

    chave_orig_canc = "32013082211222333000181009000000000000126060000001"
    chave_orig_subst = "32013082211222333000181009000000000000226060000002"
    chave_nova_subst = "32013082211222333000181009000000000000326060000003"
    chave_mesma_pag = "32013082299888777000166009000000000001026060000010"
    chave_emit_ok = "32013082211222333000181009000000000001126060000011"

    db = SessionLocal()
    try:
        db.add(
            Invoice(
                client_id=cid,
                numero="1",
                chave=chave_orig_canc,
                status="gerada",
                tipo="emitidas",
                valor=500.0,
            )
        )
        db.add(
            Invoice(
                client_id=cid,
                numero="2",
                chave=chave_orig_subst,
                status="gerada",
                tipo="emitidas",
                valor=700.0,
            )
        )
        db.commit()
    finally:
        db.close()

    xml_nfse_emit = (
        f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        f'<infNFSe Id="NFS{chave_emit_ok}"><nNFSe>11</nNFSe><cStat>100</cStat>'
        f"<emit><CNPJ>11222333000181</CNPJ></emit>"
        f"<valores><vServ>1500.00</vServ></valores>"
        f"<DPS><infDPS><tpAmb>2</tpAmb>"
        f"<toma><CNPJ>99888777000166</CNPJ><xNome>TOMADOR COFRE</xNome></toma>"
        f"</infDPS></DPS></infNFSe></NFSe>"
    )
    xml_nfse_rec = (
        f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        f'<infNFSe Id="NFS{chave_mesma_pag}"><nNFSe>10</nNFSe><cStat>100</cStat>'
        f"<emit><CNPJ>99888777000166</CNPJ></emit>"
        f"<valores><vServ>800.00</vServ></valores></infNFSe></NFSe>"
    )
    xml_evt_canc_existing = (
        '<evento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        "<infEvento><dhProc>2026-06-15T10:30:00-03:00</dhProc>"
        "<pedRegEvento><infPedReg>"
        f"<chNFSe>{chave_orig_canc}</chNFSe>"
        "<e101101><cMotivo>1</cMotivo><xMotivo>Cancelamento no portal</xMotivo></e101101>"
        "</infPedReg></pedRegEvento></infEvento></evento>"
    )
    xml_evt_canc_same_page = (
        '<evento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        "<infEvento><dhProc>2026-06-15T11:00:00-03:00</dhProc>"
        "<pedRegEvento><infPedReg>"
        f"<chNFSe>{chave_mesma_pag}</chNFSe>"
        "<e101101><cMotivo>2</cMotivo><xMotivo>Cancelamento na mesma pagina</xMotivo></e101101>"
        "</infPedReg></pedRegEvento></infEvento></evento>"
    )
    xml_evt_subst = (
        '<evento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
        "<infEvento><dhProc>2026-06-15T12:00:00-03:00</dhProc>"
        "<pedRegEvento><infPedReg>"
        f"<chNFSe>{chave_orig_subst}</chNFSe>"
        f"<e105102><cMotivo>02</cMotivo><xMotivo>Substituicao oficial</xMotivo><chSubstituta>{chave_nova_subst}</chSubstituta></e105102>"
        "</infPedReg></pedRegEvento></infEvento></evento>"
    )

    with patch(
        "app.services.adn_service.AdnNfseClient.listar_dfe_adn",
        new_callable=AsyncMock,
        return_value={
            "sucesso": True,
            "status_code": 200,
            "dados": {
                "LoteDFe": [
                    {"NSU": 10, "ChaveAcesso": chave_emit_ok, "xml_descompactado": xml_nfse_emit},
                    {"NSU": 11, "ChaveAcesso": chave_mesma_pag, "xml_descompactado": xml_nfse_rec},
                    {"NSU": 12, "ChaveAcesso": chave_orig_canc, "xml_descompactado": xml_evt_canc_existing},
                    {"NSU": 13, "ChaveAcesso": chave_mesma_pag, "xml_descompactado": xml_evt_canc_same_page},
                    {"NSU": 14, "ChaveAcesso": chave_orig_subst, "xml_descompactado": xml_evt_subst},
                ]
            },
        },
    ) as mock_dfe:
        r_ok = client.post("/api/adn/cofre/sincronizar", json={"client_id": cid, "max_paginas": 1})

    assert r_ok.status_code == 200, r_ok.text
    data_ok = r_ok.json()
    assert data_ok["sucesso"] is True
    assert data_ok["parcial"] is False
    assert data_ok["ultimo_nsu"] == 14
    assert data_ok["novas_notas"] == 2
    assert data_ok["eventos_processados"] == 3
    assert mock_dfe.call_args.kwargs.get("cnpj") == "11222333000181"
    assert mock_dfe.call_args.kwargs.get("ultimo_nsu") == 0

    db = SessionLocal()
    try:
        all_invs = db.query(Invoice).filter(Invoice.client_id == cid).all()
        assert len(all_invs) == 4  # 2 iniciais + 2 NFSe novas; zero linhas falsas para <evento>
        inv_c = db.query(Invoice).filter(Invoice.chave == chave_orig_canc).first()
        assert inv_c.status == "cancelada"
        assert inv_c.xml_evento_path is not None
        inv_same = db.query(Invoice).filter(Invoice.chave == chave_mesma_pag).first()
        assert inv_same.status == "cancelada"
        assert inv_same.tipo == "recebidas"
        inv_s = db.query(Invoice).filter(Invoice.chave == chave_orig_subst).first()
        assert inv_s.status == "substituida"
        assert inv_s.chave_substituta == chave_nova_subst
        inv_e = db.query(Invoice).filter(Invoice.chave == chave_emit_ok).first()
        assert inv_e.status == "gerada"
        assert inv_e.tipo == "emitidas"
        assert inv_e.tomador_documento == "99888777000166"
    finally:
        db.close()

    # Página 1 falha -> HTTP 502, ultimo_nsu_adn não muda (continua 14)
    with patch(
        "app.services.adn_service.AdnNfseClient.listar_dfe_adn",
        new_callable=AsyncMock,
        return_value={"sucesso": False, "status_code": 502, "erro": "Timeout ADN"},
    ):
        r_fail1 = client.post("/api/adn/cofre/sincronizar", json={"client_id": cid, "max_paginas": 2})
    assert r_fail1.status_code == 502

    db = SessionLocal()
    try:
        assert db.query(Client).filter(Client.id == cid).first().ultimo_nsu_adn == 14
    finally:
        db.close()

    # Página 1 (50 itens) OK, Página 2 falha -> parcial=True com aviso e NSU=64 salvo
    page1_lote = []
    for idx in range(50):
        nsu_val = 15 + idx
        ch_i = f"320130822112223330001810090000000000{nsu_val:03d}2606000{nsu_val:03d}"
        page1_lote.append(
            {
                "NSU": nsu_val,
                "ChaveAcesso": ch_i,
                "xml_descompactado": (
                    f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
                    f'<infNFSe Id="NFS{ch_i}"><nNFSe>{nsu_val}</nNFSe><cStat>100</cStat>'
                    f"<emit><CNPJ>11222333000181</CNPJ></emit>"
                    f"<valores><vServ>100.00</vServ></valores></infNFSe></NFSe>"
                ),
            }
        )

    with patch(
        "app.services.adn_service.AdnNfseClient.listar_dfe_adn",
        new_callable=AsyncMock,
        side_effect=[
            {"sucesso": True, "status_code": 200, "dados": {"LoteDFe": page1_lote}},
            {"sucesso": False, "status_code": 503, "erro": "Indisponível página 2"},
        ],
    ):
        r_part = client.post("/api/adn/cofre/sincronizar", json={"client_id": cid, "max_paginas": 2})

    assert r_part.status_code == 200, r_part.text
    part_json = r_part.json()
    assert part_json["sucesso"] is True
    assert part_json["parcial"] is True
    assert "página 2" in (part_json.get("aviso") or "")
    assert part_json["novas_notas"] == 50
    assert part_json["ultimo_nsu"] == 64

    db = SessionLocal()
    try:
        assert db.query(Client).filter(Client.id == cid).first().ultimo_nsu_adn == 64
    finally:
        db.close()

    # Negativos: 404 cliente inexistente; 400 cliente sem certificado
    assert client.post("/api/adn/cofre/sincronizar", json={"client_id": 999999}).status_code == 404
    assert client.post("/api/adn/cofre/sincronizar", json={"client_id": cid_no_cert}).status_code == 400


@pytest.mark.real_auth
def test_f08_cofre_adn_auth_and_anti_idor(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    create_admin_user("adm_f08", "adm_f08@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f08", "AdminPass123")
    cid_a = _create_client_db(tmp_path, "11222333000181", with_cert=True)
    cid_b = _create_client_db(tmp_path, "22333444000171", with_cert=True)
    _create_operator(adm_headers, "op_f08", client_ids=[cid_a])
    op_headers = _login_headers("op_f08", "OpPass123")

    assert client.post("/api/adn/cofre/sincronizar", json={"client_id": cid_a}).status_code == 401
    assert client.post("/api/adn/cofre/sincronizar", headers=op_headers, json={"client_id": cid_b}).status_code == 403


# ==============================================================================
# F09 — Batch SSoT, Importer & Registry Lookup Isolation/PG Ordering
# ==============================================================================


def test_f09_batch_ssot_deducao_vs_desconto_and_regime_defaults(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    cid_norm = _create_client_db(tmp_path, "31222333000181", regime="normal", with_cert=True)
    cid_simp = _create_client_db(tmp_path, "32222333000181", regime="simples", with_cert=True)
    cid_mei = _create_client_db(tmp_path, "33222333000181", regime="mei", with_cert=True)

    # 1. valor_deducao=200.00 vs valor_desconto=50.00 no lote (normal, aliq=5.0, reter_federais=sim)
    csv_ssot = (
        "documento_tomador;nome_tomador;c_trib_nac;descricao_servico;discriminacao;valor_servico;valor_deducao;valor_desconto;aliquota_iss;reter_federais;competencia;cst_ibs_cbs;cclasstrib;indop\n"
        "11222333000181;Tomador Deducao;010101;Consultoria;Desc 50 Ded 200;1000.00;200.00;50.00;5.0;sim;2026-06-15;000;000001;100301\n"
        "11222333000181;Tomador Sem Desconto;010101;Consultoria;Desc 0 Ded 200;1000.00;200.00;0.00;;nao;2026-06-15;000;000001;100301\n"
        "11222333000181;Tomador ISS Zero Explicito;010101;Consultoria;ISS 0 explicito;1000.00;0.00;0.00;0.0;nao;2026-06-15;000;000001;100301\n"
    ).encode("utf-8")

    b = client.post(
        "/api/batch-emission/import",
        data={"client_id": str(cid_norm)},
        files={"file": ("ssot.csv", csv_ssot, "text/csv")},
    ).json()
    assert b["valid_items"] == 3, b

    r_proc = client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": False})
    assert r_proc.status_code == 200, r_proc.text
    items = client.get(f"/api/batch-emission/{b['id']}/items").json()

    ref_row1 = AdnService.calcular_tributos(
        TaxCalculationRequest(
            valor_servicos=1000.0,
            regime_prestador="normal",
            cClassTrib="000001",
            cst="000",
            cIndOp="100301",
            cTribNac="010101",
            data_competencia="2026-06-15",
            desconto_incondicionado=50.0,
            deducao_reducao_iss=200.0,
            aliquota_iss=5.0,
            reter_federais=True,
        )
    )
    ref_row2 = AdnService.calcular_tributos(
        TaxCalculationRequest(
            valor_servicos=1000.0,
            regime_prestador="normal",
            cClassTrib="000001",
            cst="000",
            cIndOp="100301",
            cTribNac="010101",
            data_competencia="2026-06-15",
            desconto_incondicionado=0.0,
            deducao_reducao_iss=200.0,
            aliquota_iss=None,  # normal -> 5.0%
            reter_federais=False,
        )
    )

    db = SessionLocal()
    try:
        inv1 = db.query(Invoice).filter(Invoice.id == items[0]["invoice_id"]).first()
        inv2 = db.query(Invoice).filter(Invoice.id == items[1]["invoice_id"]).first()
        inv3 = db.query(Invoice).filter(Invoice.id == items[2]["invoice_id"]).first()

        assert inv1.valor_iss == ref_row1["iss"]["valor"] == 37.50
        assert inv1.valor_liquido == ref_row1["valor_liquido"]
        assert inv1.valor_ibs == ref_row1["reforma_tributaria"]["valor_ibs"]
        assert inv1.valor_cbs == ref_row1["reforma_tributaria"]["valor_cbs"]
        xml1 = (tmp_path / "downloads" / inv1.xml_dps_path).read_text(encoding="utf-8")
        assert "<vDescIncond>50.00</vDescIncond>" in xml1
        assert "<vDescIncond>250.00</vDescIncond>" not in xml1

        assert inv2.valor_iss == ref_row2["iss"]["valor"] == 40.00  # (1000 - 200) * 5.0%
        assert inv2.valor_liquido == ref_row2["valor_liquido"]
        xml2 = (tmp_path / "downloads" / inv2.xml_dps_path).read_text(encoding="utf-8")
        assert "<vDescIncond>" not in xml2

        assert inv3.valor_iss == 0.0  # alíquota 0.0 explícita preservada
    finally:
        db.close()

    # 2. Defaults ISS por regime quando aliquota_iss omitida: simples -> 2.0%, mei -> 0.0%
    for cid_reg, expected_iss in ((cid_simp, 20.0), (cid_mei, 0.0)):
        csv_reg = (
            "documento_tomador;nome_tomador;c_trib_nac;descricao_servico;discriminacao;valor_servico;competencia\n"
            "11222333000181;Tomador Regime;010101;Consultoria;Regime default;1000.00;2026-06-15\n"
        ).encode("utf-8")
        b_reg = client.post(
            "/api/batch-emission/import",
            data={"client_id": str(cid_reg)},
            files={"file": ("reg.csv", csv_reg, "text/csv")},
        ).json()
        assert b_reg["valid_items"] == 1
        client.post(f"/api/batch-emission/{b_reg['id']}/process", json={"transmitir": False})
        it_reg = client.get(f"/api/batch-emission/{b_reg['id']}/items").json()[0]
        db = SessionLocal()
        try:
            inv_r = db.query(Invoice).filter(Invoice.id == it_reg["invoice_id"]).first()
            assert inv_r.valor_iss == expected_iss
        finally:
            db.close()

    # 3. Encaminhamento real de cIndOp + cNBS em validate_batch_item e erro fiscal E0959
    req_val = build_tax_validation_request(
        {
            "cClassTrib": "000001",
            "cst": "000",
            "cIndOp": "020101",
            "cTribNac": "010101",
            "cNBS": "115021000",
        }
    )
    assert req_val.cIndOp == "020101"
    assert req_val.cNBS == "115021000"
    res_val_ibs = AdnService.validar_ibscbs(req_val)
    assert any(a["codigo"] == "E0932" for a in res_val_ibs["avisos"])

    db = SessionLocal()
    try:
        cli_norm = db.query(Client).filter(Client.id == cid_norm).first()
        errs_e0959 = validate_batch_item(
            db,
            cli_norm,
            {
                "documento_tomador": "11222333000181",
                "nome_tomador": "Tomador Erro Fiscal",
                "c_trib_nac": "010101",
                "discriminacao": "Teste E0959",
                "valor_servico": 500.0,
                "competencia": "2026-06-15",
                "cst_ibs_cbs": "000",
                "cclasstrib": "200029",
                "indop": "100301",
            },
        )
        assert any(e["level"] == "fiscal" and "E0959" in e["message"] for e in errs_e0959)
    finally:
        db.close()


def test_f09_batch_importer_whitespace_booleans_and_zero_padding(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    cid = _create_client_db(tmp_path, "34222333000181", regime="normal", with_cert=True)
    db = SessionLocal()
    try:
        db.add(
            ServiceItem(
                client_id=cid,
                codigo_interno="SRV-RET",
                titulo="Serviço com Retenção",
                descricao="Serviço padrão retido",
                c_trib_nac="010101",
                c_nbs="115021000",
                c_class_trib="000001",
                cst_ibscbs="000",
                c_ind_op="100301",
                valor_unitario=1000.0,
                aliquota_iss=3.0,
                iss_retido=1,
                reter_federais=1,
            )
        )
        db.commit()
    finally:
        db.close()

    # XLSX com células numéricas sem zeros à esquerda + whitespace em booleanos
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(
        [
            "documento_tomador",
            "nome_tomador",
            "codigo_servico",
            "c_trib_nac",
            "c_nbs",
            "descricao_servico",
            "discriminacao",
            "valor_servico",
            "iss_retido",
            "reter_federais",
            "competencia",
            "cst_ibs_cbs",
            "cclasstrib",
            "indop",
        ]
    )
    ws.append(
        [
            "11222333000181",
            "Tomador Excel Numerico",
            "SRV-RET",
            10101,
            11502100,
            "Consultoria",
            "Excel numerico + whitespace bool",
            1000.0,
            "   ",
            "  ",
            "2026-06-15",
            0,
            1,
            30101,
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)

    r_imp = client.post(
        "/api/batch-emission/import",
        data={"client_id": str(cid)},
        files={
            "file": (
                "zeros_pad.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r_imp.status_code == 200, r_imp.text
    b = r_imp.json()
    assert b["valid_items"] == 1

    item = client.get(f"/api/batch-emission/{b['id']}/items").json()[0]
    p = item["payload"]
    assert p["iss_retido"] is None
    assert p["reter_federais"] is None
    assert p["c_trib_nac"] == "010101"
    assert p["c_nbs"] == "011502100"
    assert p["cst_ibs_cbs"] == "000"
    assert p["cclasstrib"] == "000001"
    assert p["indop"] == "030101"

    # PATCH com código sem zero à esquerda também normaliza e preserva herança de retenção do ServiceItem
    r_patch = client.patch(
        f"/api/batch-emission/{b['id']}/items/{item['id']}",
        json={"c_trib_nac": "10101", "cclasstrib": "1", "cst_ibs_cbs": "0"},
    )
    assert r_patch.status_code == 200, r_patch.text
    assert r_patch.json()["payload"]["c_trib_nac"] == "010101"
    assert r_patch.json()["payload"]["cclasstrib"] == "000001"
    assert r_patch.json()["payload"]["cst_ibs_cbs"] == "000"

    # Processa offline e confirma que iss_retido=True (herdado do ServiceItem apesar de "   " na planilha)
    client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": False})
    it_after = client.get(f"/api/batch-emission/{b['id']}/items").json()[0]
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == it_after["invoice_id"]).first()
        xml_txt = (tmp_path / "downloads" / inv.xml_dps_path).read_text(encoding="utf-8")
        assert "<tpRetISSQN>2</tpRetISSQN>" in xml_txt
        assert "<vRetIRRF>" in xml_txt
    finally:
        db.close()


@pytest.mark.real_auth
def test_f09_registry_lookup_rbac_and_pg_ordering(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    create_admin_user("adm_f09", "adm_f09@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f09", "AdminPass123")
    cid_a = _create_client_db(tmp_path, "35222333000181", regime="normal", with_cert=True)
    _create_operator(adm_headers, "op_f09", client_ids=[cid_a])
    op_headers = _login_headers("op_f09", "OpPass123")

    db = SessionLocal()
    try:
        # Registro global (client_id=None) e registro específico da empresa (client_id=cid_a)
        db.add(
            Customer(
                client_id=None,
                documento="11222333000181",
                razao_social="TOMADOR GLOBAL",
                email="global@tomador.example",
                codigo_municipio="3201308",
            )
        )
        db.add(
            Customer(
                client_id=cid_a,
                documento="11222333000181",
                razao_social="TOMADOR EMPRESA A",
                email="empresa_a@tomador.example",
                codigo_municipio="3201308",
            )
        )
        db.add(
            ServiceItem(
                client_id=None,
                codigo_interno="SRV-GLOBAL-ONLY",
                titulo="Serviço Global",
                descricao="Global",
                c_trib_nac="010101",
                aliquota_iss=4.0,
            )
        )
        db.add(
            ServiceItem(
                client_id=None,
                codigo_interno="SRV-SHADOW",
                titulo="Serviço Global Shadow",
                descricao="Global Shadow",
                c_trib_nac="010101",
                aliquota_iss=4.5,
            )
        )
        db.add(
            ServiceItem(
                client_id=cid_a,
                codigo_interno="SRV-SHADOW",
                titulo="Serviço Específico Empresa A",
                descricao="Empresa A",
                c_trib_nac="010101",
                aliquota_iss=2.5,
            )
        )
        db.commit()
    finally:
        db.close()

    # 1. Operador NÃO pode resolver ServiceItem global (client_id=None)
    csv_op = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Tomador;SRV-GLOBAL-ONLY;Srv;1000.00;2026-06-15;Teste operador\n"
    ).encode("utf-8")
    r_op = client.post(
        "/api/batch-emission/import",
        headers=op_headers,
        data={"client_id": str(cid_a)},
        files={"file": ("op_global.csv", csv_op, "text/csv")},
    )
    assert r_op.status_code == 200, r_op.text
    assert r_op.json()["invalid_items"] == 1
    it_op = client.get(
        f"/api/batch-emission/{r_op.json()['id']}/items",
        headers=op_headers,
    ).json()[0]
    assert any(e["field"] == "codigo_servico" for e in it_op["validation_errors"])

    # 2. Admin com ambos (client_id=None e client_id=cid_a): específico da empresa SEMPRE vence (SQLite e PG16)
    csv_adm = (
        "documento_tomador;nome_tomador;codigo_servico;descricao_servico;valor_servico;competencia;discriminacao\n"
        "11222333000181;Tomador;SRV-SHADOW;Srv;1000.00;2026-06-15;Empresa vence global\n"
    ).encode("utf-8")
    r_adm = client.post(
        "/api/batch-emission/import",
        headers=adm_headers,
        data={"client_id": str(cid_a)},
        files={"file": ("adm_shadow.csv", csv_adm, "text/csv")},
    )
    assert r_adm.status_code == 200, r_adm.text
    b_adm = r_adm.json()
    assert b_adm["valid_items"] == 1
    client.post(f"/api/batch-emission/{b_adm['id']}/process", headers=adm_headers, json={"transmitir": False})
    it_adm = client.get(f"/api/batch-emission/{b_adm['id']}/items", headers=adm_headers).json()[0]
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == it_adm["invoice_id"]).first()
        assert inv.tomador_email == "empresa_a@tomador.example"  # não "global@tomador.example"
        assert inv.valor_iss == 25.00  # 2.5% específico da empresa, não 4.5% global
    finally:
        db.close()


# ==============================================================================
# F10 — Batch Processor, Stale Recovery, Email, consultar_nfse & SQL RBAC
# ==============================================================================


def test_f10_batch_processor_recovery_email_and_consultar_nfse_conteudo(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    cid = _create_client_db(tmp_path, "41222333000181", with_cert=True, smtp_host="smtp.local.example")

    csv_data = (
        "documento_tomador;nome_tomador;email_tomador;c_trib_nac;descricao_servico;discriminacao;valor_servico;competencia\n"
        "11222333000181;Item Falha XML;a@t.example;010101;Consultoria;Linha 1;1000.00;2026-06-15\n"
        "12ABC345000188;Item Sucesso;b@t.example;010101;Consultoria;Linha 2;1200.00;2026-06-15\n"
    ).encode("utf-8")

    b = client.post(
        "/api/batch-emission/import",
        data={"client_id": str(cid)},
        files={"file": ("proc_err.csv", csv_data, "text/csv")},
    ).json()
    assert b["valid_items"] == 2

    # 1. Falha em build_dps_xml no item 1 -> item 1 vira REJECTED, item 2 prossegue e autoriza, e-mail falha sem reverter AUTHORIZED
    from pynfse.adn import build_dps_xml as real_build_dps_xml

    call_idx = {"n": 0}

    def _flaky_build(*args, **kwargs):
        call_idx["n"] += 1
        if call_idx["n"] == 1:
            raise RuntimeError("Falha simulada na geração do XML")
        return real_build_dps_xml(*args, **kwargs)

    with (
        patch("app.services.batch_emission.processor.build_dps_xml", side_effect=_flaky_build),
        patch(
            "app.services.batch_emission.processor.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": True,
                "status_code": 201,
                "chave_acesso": "32013082241222333000181009000000000000226060000002",
                "nfse_xml": "<NFSe versao='1.01'><infNFSe/></NFSe>",
            },
        ),
        patch(
            "app.services.batch_emission.processor.EmailService.enviar_nfse_por_email",
            side_effect=HTTPException(status_code=502, detail="Falha SMTP simulada"),
        ) as mock_email,
    ):
        r_proc = client.post(
            f"/api/batch-emission/{b['id']}/process",
            json={"transmitir": True, "enviar_email": True},
        )

    assert r_proc.status_code == 200, r_proc.text
    b_res = r_proc.json()
    assert b_res["status"] == "PARTIAL"
    assert b_res["authorized_items"] == 1
    assert b_res["rejected_items"] == 1
    assert mock_email.call_count == 1
    assert mock_email.call_args.kwargs["destinatario"] == "b@t.example"

    items = client.get(f"/api/batch-emission/{b['id']}/items").json()
    assert items[0]["status"] == "REJECTED"
    assert "geração do XML da DPS" in (items[0]["last_error"] or "")
    assert items[1]["status"] == "AUTHORIZED"

    # Batch não está travado em PROCESSING: PATCH no item 1 funciona (não dá 409)
    r_patch = client.patch(
        f"/api/batch-emission/{b['id']}/items/{items[0]['id']}",
        json={"discriminacao": "Linha 1 corrigida"},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["status"] == "VALID"

    # 2. Recuperação stale PROCESSING
    db = SessionLocal()
    try:
        b_obj = db.query(BatchImport).filter(BatchImport.id == b["id"]).first()
        it_obj = db.query(BatchImportItem).filter(BatchImportItem.id == items[0]["id"]).first()
        b_obj.status = "PROCESSING"
        it_obj.status = "PROCESSING"
        it_obj.id_dps = None
        it_obj.processed_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=20)
        db.commit()
        assert recover_stale_processing_batch(db, b_obj) is False  # Ainda recente (< 300s)

        it_obj.processed_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=600)
        db.commit()
        assert recover_stale_processing_batch(db, b_obj) is True
        db.refresh(it_obj)
        db.refresh(b_obj)
        assert it_obj.status == "RETRY"
        assert b_obj.status != "PROCESSING"
    finally:
        db.close()

    # 3. resolve_unknown_and_retry_batch lendo `consultar_nfse` via `conteudo` (XML str e dict gzip)
    db = SessionLocal()
    try:
        it_unk = db.query(BatchImportItem).filter(BatchImportItem.id == items[0]["id"]).first()
        it_unk.status = "UNKNOWN"
        it_unk.id_dps = "DPS320130824122233300018100900000000000000001"
        db.commit()
    finally:
        db.close()

    chave_cons = "32013082241222333000181009000000000000126060000001"
    with (
        patch(
            "app.services.batch_emission.processor.AdnNfseClient.consultar_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": True,
                "status_code": 200,
                "conteudo": {"chNFSe": chave_cons},
            },
        ),
        patch(
            "app.services.batch_emission.processor.AdnNfseClient.consultar_nfse",
            new_callable=AsyncMock,
            return_value={
                "sucesso": True,
                "status_code": 200,
                "conteudo": "<NFSe versao='1.01'><infNFSe>XML Conteudo Str</infNFSe></NFSe>",
            },
        ),
    ):
        r_retry = client.post(f"/api/batch-emission/{b['id']}/retry", json={"transmitir": True})

    assert r_retry.status_code == 200, r_retry.text
    assert r_retry.json()["authorized_items"] == 2
    assert r_retry.json()["unknown_items"] == 0
    it_resolved = client.get(f"/api/batch-emission/{b['id']}/items").json()[0]
    assert it_resolved["status"] == "AUTHORIZED"
    assert it_resolved["chave_acesso"] == chave_cons

    # 4. Negativos: 404 batch inexistente; 400 sem itens elegíveis; 409 batch cancelado
    assert client.post("/api/batch-emission/nao-existe/process", json={"transmitir": False}).status_code == 404
    assert client.post(f"/api/batch-emission/{b['id']}/process", json={"transmitir": False}).status_code == 400
    b_canc = client.post(
        "/api/batch-emission/import",
        data={"client_id": str(cid)},
        files={"file": ("canc.csv", csv_data, "text/csv")},
    ).json()
    assert client.post(f"/api/batch-emission/{b_canc['id']}/cancel").status_code == 200
    assert client.post(f"/api/batch-emission/{b_canc['id']}/process", json={"transmitir": False}).status_code == 409
    assert client.delete(f"/api/batch-emission/{b_canc['id']}").status_code == 200
    db = SessionLocal()
    try:
        batch_actions = {row[0] for row in db.query(AuditLog.action).all()}
        assert {"batch.import", "batch.process", "batch.retry", "batch.cancel", "batch.delete"}.issubset(batch_actions)
    finally:
        db.close()


@pytest.mark.real_auth
def test_f10_list_batches_sql_scoping_and_rbac(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    create_admin_user("adm_f10", "adm_f10@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f10", "AdminPass123")
    cid_a = _create_client_db(tmp_path, "42222333000181", with_cert=True)
    cid_b = _create_client_db(tmp_path, "43222333000181", with_cert=True)
    _create_operator(adm_headers, "op_f10", client_ids=[cid_a])
    op_headers = _login_headers("op_f10", "OpPass123")

    csv_min = (
        "documento_tomador;nome_tomador;c_trib_nac;descricao_servico;discriminacao;valor_servico;competencia\n"
        "11222333000181;Tomador;010101;Consultoria;Teste;100.00;2026-06-15\n"
    ).encode("utf-8")

    # Cria 2 lotes antigos para A e 6 lotes mais recentes para B
    batch_a_ids = []
    for _ in range(2):
        r = client.post(
            "/api/batch-emission/import",
            headers=adm_headers,
            data={"client_id": str(cid_a), "auto_validate": "false"},
            files={"file": ("a.csv", csv_min, "text/csv")},
        )
        batch_a_ids.append(r.json()["id"])

    batch_b_id = None
    for _ in range(6):
        r = client.post(
            "/api/batch-emission/import",
            headers=adm_headers,
            data={"client_id": str(cid_b), "auto_validate": "false"},
            files={"file": ("b.csv", csv_min, "text/csv")},
        )
        batch_b_id = r.json()["id"]

    # Sem filtro Python pós-LIMIT: limit=3 deve retornar os 2 lotes da empresa A
    r_list_op = client.get("/api/batch-emission?limit=3", headers=op_headers)
    assert r_list_op.status_code == 200
    returned_ids = {b["id"] for b in r_list_op.json()}
    assert returned_ids == set(batch_a_ids)

    # RBAC 401 e 403 nas rotas do lote B
    item_b_id = client.get(f"/api/batch-emission/{batch_b_id}/items", headers=adm_headers).json()[0]["id"]
    assert client.get("/api/batch-emission").status_code == 401
    assert client.post(f"/api/batch-emission/{batch_b_id}/validate", headers=op_headers).status_code == 403
    assert client.patch(
        f"/api/batch-emission/{batch_b_id}/items/{item_b_id}",
        headers=op_headers,
        json={"valor_servico": 200.0},
    ).status_code == 403
    assert client.post(f"/api/batch-emission/{batch_b_id}/process", headers=op_headers, json={"transmitir": False}).status_code == 403
    assert client.post(f"/api/batch-emission/{batch_b_id}/retry", headers=op_headers, json={"transmitir": False}).status_code == 403
    assert client.post(f"/api/batch-emission/{batch_b_id}/cancel", headers=op_headers).status_code == 403
    assert client.get(f"/api/batch-emission/{batch_b_id}/export", headers=op_headers).status_code == 403
    assert client.delete(f"/api/batch-emission/{batch_b_id}/items/{item_b_id}", headers=op_headers).status_code == 403
    assert client.post(
        f"/api/batch-emission/{batch_b_id}/items/delete",
        headers=op_headers,
        json={"item_ids": [item_b_id]},
    ).status_code == 403
    assert client.delete(f"/api/batch-emission/{batch_b_id}", headers=op_headers).status_code == 403


# ==============================================================================
# F11 — `_calcular_tributacao_se_necessario`, `emitir_dps` & `emitir_dps_lote`
# ==============================================================================


def test_f11_calcular_tributacao_preserves_zero_and_nt1101_fields():
    # 1. Preservação de 0.0 explícito em alíquotas/percentuais no regime normal
    calc_zero = AdnService._calcular_tributacao_se_necessario(
        prestador={"regime": "normal"},
        servico={
            "valor": 1000.0,
            "cTribNac": "010101",
            "cClassTrib": "000001",
            "cst": "000",
            "cIndOp": "100301",
            "aliquota_iss": 0.0,
            "p_ibs_uf": 0.0,
            "p_ibs_mun": 0.0,
            "p_cbs": 0.0,
            "pRedutorGov": 0.0,
            "pDifUF": 0.0,
        },
        tributacao_informada=None,
        data_competencia="2026-06-15",
    )
    assert calc_zero["iss"]["aliquota"] == 0.0
    assert calc_zero["iss"]["valor"] == 0.0
    assert calc_zero["reforma_tributaria"]["valor_ibs"] == 0.0
    assert calc_zero["reforma_tributaria"]["valor_cbs"] == 0.0

    # 2. Paridade completa de campos avançados NT 1.101 / retenções com calcular_tributos
    calc_adv = AdnService._calcular_tributacao_se_necessario(
        prestador={"regime": "simples"},
        servico={
            "valor": 2000.0,
            "cTribNac": "010101",
            "cNBS": "115021000",
            "cClassTrib": "000001",
            "cst": "000",
            "cIndOp": "100301",
            "desconto_incondicionado": 50.0,
            "deducao_reducao_iss": 100.0,
            "aliquota_iss": 3.0,
            "iss_retido": True,
            "tp_ret_issqn": 2,
            "reter_federais": True,
            "p_aliq_pis": 0.65,
            "p_aliq_cofins": 3.0,
            "v_inss_informado": 50.0,
            "p_red_aliq_uf": 10.0,
            "p_red_aliq_mun": 10.0,
            "p_red_aliq_cbs": 10.0,
            "cCredPres": "01",
            "pCredPresIBS": 1.5,
            "pCredPresCBS": 2.5,
            "indDoacao": 1,
            "vIBSEstCred": 10.0,
            "vCBSEstCred": 20.0,
            "apurar_ibscbs_simples": True,
        },
        tributacao_informada=None,
        data_competencia="2027-06-15",
    )
    ref_adv = AdnService.calcular_tributos(
        TaxCalculationRequest(
            valor_servicos=2000.0,
            regime_prestador="simples",
            cClassTrib="000001",
            cst="000",
            cIndOp="100301",
            cTribNac="010101",
            cNBS="115021000",
            data_competencia="2027-06-15",
            desconto_incondicionado=50.0,
            deducao_reducao_iss=100.0,
            aliquota_iss=3.0,
            iss_retido=True,
            tp_ret_issqn=2,
            reter_federais=True,
            p_aliq_pis=0.65,
            p_aliq_cofins=3.0,
            v_inss_informado=50.0,
            p_red_aliq_uf=10.0,
            p_red_aliq_mun=10.0,
            p_red_aliq_cbs=10.0,
            c_cred_pres="01",
            p_cred_pres_ibs=1.5,
            p_cred_pres_cbs=2.5,
            ind_doacao=1,
            v_ibs_est_cred=10.0,
            v_cbs_est_cred=20.0,
            apurar_ibscbs_simples=True,
        )
    )
    assert calc_adv["valor_liquido"] == ref_adv["valor_liquido"]
    assert calc_adv["valor_total_nf"] == ref_adv["valor_total_nf"]
    assert calc_adv["iss"] == ref_adv["iss"]
    assert calc_adv["retencoes_federais"] == ref_adv["retencoes_federais"]
    assert calc_adv["reforma_tributaria"]["valor_ibs"] == ref_adv["reforma_tributaria"]["valor_ibs"]
    assert calc_adv["reforma_tributaria"]["valor_cbs"] == ref_adv["reforma_tributaria"]["valor_cbs"]
    assert calc_adv["reforma_tributaria"]["credito_presumido"] == ref_adv["reforma_tributaria"]["credito_presumido"]


def test_f11_emitir_dps_nt1101_block_4xx_rejeitada_and_no_email(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    cid = _create_client_db(
        tmp_path,
        "51222333000181",
        regime="normal",
        with_cert=True,
        ultimo_numero_dps=10,
        smtp_host="smtp.local.example",
    )

    tomador = {"documento": "11222333000181", "razao_social": "TOMADOR F11", "email": "t@f11.example"}
    servico_base = {
        "cTribNac": "010101",
        "cNBS": "115021000",
        "descricao": "Consultoria F11",
        "valor": 1000.0,
        "cClassTrib": "000001",
        "cst": "000",
        "cIndOp": "100301",
    }

    # 1. Bloqueio NT 1.101 (422) NÃO pode queimar numero_dps
    r_nt = client.post(
        "/api/adn/dps/emitir",
        json={
            "client_id": cid,
            "transmitir": False,
            "tomador": tomador,
            "servico": {**servico_base, "cClassTrib": "200029", "cst": "000"},
        },
    )
    assert r_nt.status_code == 422

    # 2. Erro XSD/XML (400/422) também NÃO pode queimar numero_dps
    r_xsd = client.post(
        "/api/adn/dps/emitir",
        json={
            "client_id": cid,
            "transmitir": False,
            "tomador": tomador,
            "servico": {**servico_base, "descricao": ""},
        },
    )
    assert r_xsd.status_code in (400, 422)

    db = SessionLocal()
    try:
        assert db.query(Client).filter(Client.id == cid).first().ultimo_numero_dps == 10
        assert db.query(Invoice).filter(Invoice.client_id == cid).count() == 0
    finally:
        db.close()

    # 3. Rejeição 4xx da Sefin -> status_nota == "rejeitada" (fora da fila de contingência) + sem e-mail
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": False,
                "status_code": 422,
                "resposta": {
                    "erros": [
                        {"Codigo": "E0039", "Descricao": "Simples Nacional incorreto"},
                        {"Codigo": "E0999", "Descricao": "Detalhe adicional"},
                    ]
                },
            },
        ),
        patch("app.services.adn_service.EmailService.enviar_nfse_por_email") as mock_email,
    ):
        r_rej = client.post(
            "/api/adn/dps/emitir",
            json={
                "client_id": cid,
                "transmitir": True,
                "enviar_email": True,
                "tomador": tomador,
                "servico": servico_base,
            },
        )
    assert r_rej.status_code == 200, r_rej.text
    rej_json = r_rej.json()
    assert rej_json["status_nota"] == "rejeitada"
    assert len(rej_json["erros"]) == 2
    assert "E0039" in rej_json["ultimo_erro_envio"]
    assert "E0999" in rej_json["ultimo_erro_envio"]
    assert mock_email.call_count == 0
    # Nota rejeitada NÃO entra na fila de contingência
    assert all(x["id"] != rej_json["invoice_id"] for x in client.get("/api/adn/fila").json())

    # 4. Contingência e offline também NÃO enviam e-mail
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Timeout"),
        ),
        patch("app.services.adn_service.EmailService.enviar_nfse_por_email") as mock_email_cont,
    ):
        r_cont = client.post(
            "/api/adn/dps/emitir",
            json={"client_id": cid, "transmitir": True, "enviar_email": True, "tomador": tomador, "servico": servico_base},
        )
    assert r_cont.json()["status_nota"] == "fila_contingencia"
    assert mock_email_cont.call_count == 0

    with patch("app.services.adn_service.EmailService.enviar_nfse_por_email") as mock_email_off:
        r_off = client.post(
            "/api/adn/dps/emitir",
            json={"client_id": cid, "transmitir": False, "enviar_email": True, "tomador": tomador, "servico": servico_base},
        )
    assert r_off.json()["status_nota"] == "dps_gerada"
    assert mock_email_off.call_count == 0

    # 5. emitir_dps_lote distingue autorizadas vs rejeitadas (erros) e inclui tomador_documento/erro
    with patch(
        "app.services.adn_service.AdnNfseClient.emitir_dps",
        new_callable=AsyncMock,
        side_effect=[
            {"sucesso": True, "status_code": 201, "chave_acesso": "32013082251222333000181009000000000002026060000020"},
            {"sucesso": False, "status_code": 422, "resposta": {"erros": [{"Codigo": "E0100", "Descricao": "Erro lote"}]}},
        ],
    ):
        r_lote = client.post(
            "/api/adn/dps/emitir-lote",
            json={
                "client_id": cid,
                "transmitir": True,
                "itens": [
                    {"tomador": tomador, "servico": servico_base},
                    {"tomador": tomador, "servico": servico_base},
                ],
            },
        )
    assert r_lote.status_code == 200, r_lote.text
    lote_json = r_lote.json()
    assert lote_json["autorizadas"] == 1
    assert lote_json["erros"] == 1
    assert lote_json["geradas_offline"] == 0
    assert lote_json["resultados"][1]["sucesso"] is False
    assert lote_json["resultados"][1]["tomador_documento"] == "11222333000181"
    assert "E0100" in lote_json["resultados"][1]["erro"]


# ==============================================================================
# F12 — Cancelar, Substituir, Fila Contingência, Scheduler & AuditService
# ==============================================================================


@pytest.mark.real_auth
def test_f12_cancelar_substituir_mismatch_anti_idor_and_no_mutation_on_error(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    create_admin_user("adm_f12a", "adm_f12a@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f12a", "AdminPass123")
    cid_a = _create_client_db(tmp_path, "61222333000181", with_cert=True)
    cid_b = _create_client_db(tmp_path, "62222333000181", with_cert=True)
    cid_nocert = _create_client_db(tmp_path, "63222333000181", with_cert=False)
    _create_operator(adm_headers, "op_f12a", client_ids=[cid_a])
    op_headers = _login_headers("op_f12a", "OpPass123")

    chave_a = "32013082261222333000181009000000000000126060000001"
    chave_b = "32013082262223330001810090000000000000126060000001"
    chave_nc = "32013082263222333000181009000000000000126060000001"
    db = SessionLocal()
    try:
        inv_a = Invoice(client_id=cid_a, numero="1", chave=chave_a, status="gerada", tipo="emitidas", valor=500.0)
        inv_b = Invoice(client_id=cid_b, numero="1", chave=chave_b, status="gerada", tipo="emitidas", valor=800.0)
        inv_nc = Invoice(client_id=cid_nocert, numero="1", chave=chave_nc, status="gerada", tipo="emitidas", valor=300.0)
        db.add_all([inv_a, inv_b, inv_nc])
        db.commit()
        db.refresh(inv_a)
        db.refresh(inv_b)
        db.refresh(inv_nc)
        inv_a_id, inv_b_id, inv_nc_id = inv_a.id, inv_b.id, inv_nc.id
    finally:
        db.close()

    tomador = {"documento": "11222333000181", "razao_social": "TOMADOR F12"}
    servico = {
        "cTribNac": "010101",
        "cNBS": "115021000",
        "descricao": "Servico F12",
        "valor": 600.0,
        "cClassTrib": "000001",
        "cst": "000",
        "cIndOp": "100301",
    }

    # 1. Mismatch 400 & Missing 404
    assert client.post(
        "/api/adn/nfse/cancelar",
        headers=adm_headers,
        json={"client_id": cid_a, "invoice_id": 999999, "chave_nfse": chave_a, "transmitir": False},
    ).status_code == 404
    assert client.post(
        "/api/adn/nfse/cancelar",
        headers=adm_headers,
        json={"client_id": cid_a, "invoice_id": inv_b_id, "chave_nfse": chave_b, "transmitir": False},
    ).status_code == 400
    assert client.post(
        "/api/adn/nfse/cancelar",
        headers=adm_headers,
        json={"client_id": cid_a, "invoice_id": inv_a_id, "chave_nfse": chave_b, "transmitir": False},
    ).status_code == 400
    assert client.post(
        "/api/adn/nfse/substituir",
        headers=adm_headers,
        json={
            "client_id": cid_a,
            "invoice_id_substituida": inv_b_id,
            "chave_nfse_substituida": chave_b,
            "tomador": tomador,
            "servico": servico,
            "transmitir": False,
        },
    ).status_code == 400

    # 2. Anti-IDOR 403
    assert client.post(
        "/api/adn/nfse/cancelar",
        headers=op_headers,
        json={"invoice_id": inv_b_id, "chave_nfse": chave_b, "transmitir": False},
    ).status_code == 403
    assert client.post(
        "/api/adn/nfse/substituir",
        headers=op_headers,
        json={
            "invoice_id_substituida": inv_b_id,
            "chave_nfse_substituida": chave_b,
            "tomador": tomador,
            "servico": servico,
            "transmitir": False,
        },
    ).status_code == 403

    # 3. Falha ao transmitir cancelar_nfse (422 e exceção) NÃO muta invoice_db
    with patch(
        "app.services.adn_service.AdnNfseClient.enviar_evento",
        new_callable=AsyncMock,
        return_value={"sucesso": False, "status_code": 422, "resposta": {"erros": ["Erro evento"]}},
    ):
        r_c_err = client.post(
            "/api/adn/nfse/cancelar",
            headers=adm_headers,
            json={"client_id": cid_a, "invoice_id": inv_a_id, "chave_nfse": chave_a, "transmitir": True},
        )
    assert r_c_err.status_code == 200
    assert r_c_err.json()["retorno_adn"]["sucesso"] is False

    with patch(
        "app.services.adn_service.AdnNfseClient.enviar_evento",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Socket reset"),
    ):
        r_c_exc = client.post(
            "/api/adn/nfse/cancelar",
            headers=adm_headers,
            json={"client_id": cid_a, "invoice_id": inv_a_id, "chave_nfse": chave_a, "transmitir": True},
        )
    assert r_c_exc.status_code == 200
    assert r_c_exc.json()["retorno_adn"]["erro_transporte"] is True

    db = SessionLocal()
    try:
        inv_chk = db.query(Invoice).filter(Invoice.id == inv_a_id).first()
        assert inv_chk.status == "gerada"
        assert inv_chk.motivo_cancelamento is None
        assert inv_chk.data_cancelamento is None
        assert inv_chk.xml_evento_path is None
    finally:
        db.close()

    # 4. Falha ao transmitir substituir_nfse (422 e sem cert) NÃO marca original como "substituida"
    with patch(
        "app.services.adn_service.AdnNfseClient.emitir_dps",
        new_callable=AsyncMock,
        return_value={"sucesso": False, "status_code": 422, "resposta": {"erros": ["Rejeitada"]}},
    ):
        r_s_err = client.post(
            "/api/adn/nfse/substituir",
            headers=adm_headers,
            json={
                "client_id": cid_a,
                "invoice_id_substituida": inv_a_id,
                "chave_nfse_substituida": chave_a,
                "tomador": tomador,
                "servico": servico,
                "transmitir": True,
            },
        )
    assert r_s_err.status_code == 200
    assert r_s_err.json()["status_nota"] == "rejeitada"

    r_s_nc = client.post(
        "/api/adn/nfse/substituir",
        headers=adm_headers,
        json={
            "client_id": cid_nocert,
            "invoice_id_substituida": inv_nc_id,
            "chave_nfse_substituida": chave_nc,
            "tomador": tomador,
            "servico": servico,
            "transmitir": True,
        },
    )
    assert r_s_nc.status_code == 200
    assert r_s_nc.json()["status_nota"] == "fila_contingencia"

    db = SessionLocal()
    try:
        assert db.query(Invoice).filter(Invoice.id == inv_a_id).first().status == "gerada"
        assert db.query(Invoice).filter(Invoice.id == inv_a_id).first().chave_substituta is None
        assert db.query(Invoice).filter(Invoice.id == inv_nc_id).first().status == "gerada"
    finally:
        db.close()

    # 5. Happy path substituir_nfse persiste nfse_xml em xml_path e gera PDF
    chave_subst_ok = "32013082261222333000181009000000000009926060000099"
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": True,
                "status_code": 201,
                "chave_acesso": chave_subst_ok,
                "nfse_xml": f"<NFSe versao='1.01'><infNFSe Id='NFS{chave_subst_ok}'/></NFSe>",
            },
        ),
        patch(
            "app.services.adn_service.AdnService._gerar_pdf_danfse",
            return_value=f"adn/pdfs/{chave_subst_ok}.pdf",
        ),
    ):
        r_s_ok = client.post(
            "/api/adn/nfse/substituir",
            headers=adm_headers,
            json={
                "client_id": cid_a,
                "invoice_id_substituida": inv_a_id,
                "chave_nfse_substituida": chave_a,
                "tomador": tomador,
                "servico": servico,
                "transmitir": True,
            },
        )
    assert r_s_ok.status_code == 200, r_s_ok.text
    s_ok = r_s_ok.json()
    assert s_ok["status_nota"] == "gerada"
    assert s_ok["xml_path"].replace("\\", "/").startswith("adn/nfse/")
    assert s_ok["pdf_path"] == f"adn/pdfs/{chave_subst_ok}.pdf"

    db = SessionLocal()
    try:
        orig_final = db.query(Invoice).filter(Invoice.id == inv_a_id).first()
        subst_final = db.query(Invoice).filter(Invoice.id == s_ok["invoice_id_substituta"]).first()
        assert orig_final.status == "substituida"
        assert orig_final.chave_substituta == chave_subst_ok
        assert subst_final.status == "gerada"
        assert subst_final.tomador_documento == "11222333000181"
    finally:
        db.close()


@pytest.mark.real_auth
def test_f12_reenviar_fila_consultar_dps_4xx_sync_batch_and_audit(monkeypatch, tmp_path: Path):
    _reset_db()
    _isolate_storage(monkeypatch, tmp_path)

    create_admin_user("adm_f12b", "adm_f12b@empresa.com.br", "AdminPass123")
    adm_headers = _login_headers("adm_f12b", "AdminPass123")
    cid_a = _create_client_db(tmp_path, "71222333000181", with_cert=True)
    cid_b = _create_client_db(tmp_path, "72222333000181", with_cert=True)
    _create_operator(adm_headers, "op_f12b", client_ids=[cid_a])
    op_headers = _login_headers("op_f12b", "OpPass123")

    # Cria lote com 3 notas que entram em contingência (UNKNOWN / fila_contingencia)
    csv_3 = (
        "documento_tomador;nome_tomador;c_trib_nac;descricao_servico;discriminacao;valor_servico;competencia\n"
        "11222333000181;Fila Idempotente;010101;Consultoria;Nota 1;500.00;2026-06-15\n"
        "12ABC345000188;Fila 422 Rejeitada;010101;Consultoria;Nota 2;600.00;2026-06-15\n"
        "01234567890;Fila 503 Continua;010101;Consultoria;Nota 3;700.00;2026-06-15\n"
    ).encode("utf-8")
    b = client.post(
        "/api/batch-emission/import",
        headers=adm_headers,
        data={"client_id": str(cid_a)},
        files={"file": ("fila3.csv", csv_3, "text/csv")},
    ).json()

    with patch(
        "app.services.batch_emission.processor.AdnNfseClient.emitir_dps",
        new_callable=AsyncMock,
        side_effect=[TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")],
    ):
        client.post(f"/api/batch-emission/{b['id']}/process", headers=adm_headers, json={"transmitir": True})

    items = client.get(f"/api/batch-emission/{b['id']}/items", headers=adm_headers).json()
    inv1_id = items[0]["invoice_id"]
    inv2_id = items[1]["invoice_id"]
    inv3_id = items[2]["invoice_id"]

    # 1. Nota 1: consultar_dps == 200 -> autoriza SEM chamar emitir_dps e sincroniza BatchImportItem -> AUTHORIZED
    chave_rec1 = "32013082271222333000181009000000000000126060000001"
    nfse_b64_1 = AdnNfseClient.compactar_xml_gzip_b64(f"<NFSe versao='1.01'><infNFSe Id='NFS{chave_rec1}'/></NFSe>")
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.consultar_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": True,
                "status_code": 200,
                "conteudo": {"chaveAcesso": chave_rec1, "nfseXmlGZipB64": nfse_b64_1},
            },
        ),
        patch("app.services.adn_service.AdnNfseClient.emitir_dps", new_callable=AsyncMock) as mock_no_emit,
    ):
        r_r1 = client.post(
            "/api/adn/fila/reenviar",
            headers=adm_headers,
            json={"client_id": cid_a, "invoice_ids": [inv1_id]},
        )
    assert r_r1.status_code == 200
    assert r_r1.json()["autorizadas"] == 1
    assert mock_no_emit.call_count == 0

    # 2. Nota 2: consultar_dps == 404 -> emitir_dps == 422 -> status="rejeitada", ultimo_erro_envio com E0123, BatchImportItem == REJECTED
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.consultar_dps",
            new_callable=AsyncMock,
            return_value={"sucesso": False, "status_code": 404, "conteudo": None},
        ),
        patch(
            "app.services.adn_service.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            return_value={
                "sucesso": False,
                "status_code": 422,
                "resposta": {"erros": [{"Codigo": "E0123", "Descricao": "Erro fiscal permanente"}]},
            },
        ),
    ):
        r_r2 = client.post(
            "/api/adn/fila/reenviar",
            headers=adm_headers,
            json={"client_id": cid_a, "invoice_ids": [inv2_id]},
        )
    assert r_r2.status_code == 200
    assert r_r2.json()["falhas"] == 1
    assert r_r2.json()["resultados"][0]["status_nota"] == "rejeitada"

    # 3. Nota 3: consultar_dps == 404 -> emitir_dps == 503 -> permanece fila_contingencia
    with (
        patch(
            "app.services.adn_service.AdnNfseClient.consultar_dps",
            new_callable=AsyncMock,
            return_value={"sucesso": False, "status_code": 404, "conteudo": None},
        ),
        patch(
            "app.services.adn_service.AdnNfseClient.emitir_dps",
            new_callable=AsyncMock,
            return_value={"sucesso": False, "status_code": 503, "mensagem": "Sefin fora do ar"},
        ),
    ):
        r_r3 = client.post(
            "/api/adn/fila/reenviar",
            headers=adm_headers,
            json={"client_id": cid_a, "invoice_ids": [inv3_id]},
        )
    assert r_r3.status_code == 200
    assert r_r3.json()["falhas"] == 1

    db = SessionLocal()
    try:
        i1 = db.query(Invoice).filter(Invoice.id == inv1_id).first()
        i2 = db.query(Invoice).filter(Invoice.id == inv2_id).first()
        i3 = db.query(Invoice).filter(Invoice.id == inv3_id).first()
        assert i1.status == "gerada"
        assert i2.status == "rejeitada"
        assert "E0123" in (i2.ultimo_erro_envio or "")
        assert i3.status == "fila_contingencia"
        assert i3.tentativas_envio >= 1

        b_chk = db.query(BatchImport).filter(BatchImport.id == b["id"]).first()
        assert b_chk.authorized_items == 1
        assert b_chk.rejected_items == 1
        assert b_chk.unknown_items == 1
    finally:
        db.close()

    # 4. POST /api/adn/fila/{invoice_id}/consultar (401, 403, 404, 409, 404-ADN, 200-ADN)
    assert client.post(f"/api/adn/fila/{inv3_id}/consultar").status_code == 401
    assert client.post("/api/adn/fila/999999/consultar", headers=adm_headers).status_code == 404
    assert client.post(f"/api/adn/fila/{inv1_id}/consultar", headers=adm_headers).status_code == 409

    db = SessionLocal()
    try:
        inv_b_fila = Invoice(
            client_id=cid_b,
            numero="9",
            chave="32013082272222333000181009000000000000926060000009",
            status="fila_contingencia",
            tipo="emitidas",
            valor=100.0,
            id_dps="DPS320130827222233300018100900000000000000009",
        )
        db.add(inv_b_fila)
        db.commit()
        db.refresh(inv_b_fila)
        inv_b_fila_id = inv_b_fila.id
    finally:
        db.close()

    assert client.post(f"/api/adn/fila/{inv_b_fila_id}/consultar", headers=op_headers).status_code == 403

    with patch(
        "app.services.adn_service.AdnNfseClient.consultar_dps",
        new_callable=AsyncMock,
        return_value={"sucesso": False, "status_code": 404, "conteudo": None},
    ):
        r_cons_404 = client.post(f"/api/adn/fila/{inv3_id}/consultar", headers=op_headers)
    assert r_cons_404.status_code == 200
    assert r_cons_404.json()["status_anterior"] == "fila_contingencia"
    assert r_cons_404.json()["status_atual"] == "fila_contingencia"

    chave_rec3 = "32013082271222333000181009000000000000326060000003"
    nfse_b64_3 = AdnNfseClient.compactar_xml_gzip_b64(f"<NFSe versao='1.01'><infNFSe Id='NFS{chave_rec3}'/></NFSe>")
    with patch(
        "app.services.adn_service.AdnNfseClient.consultar_dps",
        new_callable=AsyncMock,
        return_value={
            "sucesso": True,
            "status_code": 200,
            "conteudo": {"chaveAcesso": chave_rec3, "nfseXmlGZipB64": nfse_b64_3},
        },
    ):
        r_cons_200 = client.post(f"/api/adn/fila/{inv3_id}/consultar", headers=op_headers)
    assert r_cons_200.status_code == 200
    assert r_cons_200.json()["status_atual"] == "gerada"
    assert r_cons_200.json()["chave_nfse"] == chave_rec3

    # 5. SchedulerService.run_fila_retry_cycle NÃO emite `FOR UPDATE` durante o ciclo
    sql_statements: list[str] = []

    def _capture_sql(conn, cursor, statement, parameters, context, executemany):
        sql_statements.append(str(statement).upper())

    event.listen(engine, "before_cursor_execute", _capture_sql)
    try:
        with (
            patch.object(
                SchedulerService,
                "get_config",
                return_value={
                    "enabled": True,
                    "scheduler_mode": "leader",
                    "interval_seconds": 300,
                    "max_tentativas": 5,
                },
            ),
            patch(
                "app.services.scheduler_service.AdnService.reenviar_fila_contingencia",
                new_callable=AsyncMock,
                return_value={"total_processadas": 1, "autorizadas": 0, "falhas": 1, "resultados": []},
            ),
        ):
            r_trig = client.post("/api/adn/worker/trigger", headers=adm_headers)
    finally:
        event.remove(engine, "before_cursor_execute", _capture_sql)

    assert r_trig.status_code == 200
    assert not any("FOR UPDATE" in stmt for stmt in sql_statements)

    # 6. AuditLog contém trilhas dos eventos críticos e zero segredos vazados
    r_logs = client.get("/api/audit-logs?page_size=50", headers=adm_headers)
    assert r_logs.status_code == 200
    actions = {item["action"] for item in r_logs.json()["items"]}
    assert {
        "batch.import",
        "batch.process",
        "emission.fila_retry",
        "emission.fila_consultar",
        "system.worker_trigger",
    }.issubset(actions)
    assert "senha_cert_m2" not in r_logs.text

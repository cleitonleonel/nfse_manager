"""Camada de Serviço ADN / Sefin Nacional do nfse_manager.

Consome o pacote `pynfse.adn` do projeto `pynfse`
para executar toda a regra fiscal, catálogos (CST, cClassTrib, cTribNac, LC 116, Anexo VIII, cIndOp),
cálculo tributário (NT 1.101 / LC 214/2025), construção de XML (DPS v1.01 e Eventos e101101/e105102),
validação XSD v1.01, assinatura XML-DSig A1 e comunicação mTLS com o ADN, mantendo neste módulo
apenas a orquestração com o banco de dados local (`Client` e `Invoice`) e persistência de arquivos.
"""

from __future__ import annotations

import base64
import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Client, Invoice
from app.schemas import (
    CancelarNfseRequest,
    EmitirDpsRequest,
    SubstituirNfseRequest,
    TaxCalculationRequest,
    TaxValidationRequest,
)
from pynfse.adn import (
    AdnNfseClient,
    DpsSigner,
    XsdValidator,
    buscar_correlacoes_anexo_viii,
    build_dps_xml,
    build_evento_cancelamento_xml,
    build_evento_substituicao_xml,
    calcular_tributacao,
    clean_digits,
    formatar_id_dps,
    listar_cclasstrib,
    listar_cst,
    listar_favoritos,
    listar_indop,
    listar_servicos_ctribnac,
    listar_subitens_lc116,
    obter_cclasstrib,
    obter_servico_ctribnac,
    validar_regras_ibscbs,
)


BACKEND_DIR = Path(__file__).resolve().parents[2]
DOWNLOADS_DIR = BACKEND_DIR / "downloads"


class AdnService:
    """Serviço unificado do nfse_manager que integra o banco local ao pacote `pynfse.adn`."""

    # ==========================================================================
    # 1. Catálogos Fiscais (delegados ao pynfse.adn)
    # ==========================================================================

    @staticmethod
    def listar_cst(apenas_nfse: bool = False):
        return listar_cst(apenas_nfse=apenas_nfse)

    @staticmethod
    def listar_cclasstrib(
        cst: Optional[str] = None,
        apenas_nfse: bool = False,
        apenas_anexo_viii: bool = False,
        q: Optional[str] = None,
    ):
        return listar_cclasstrib(
            cst=cst,
            apenas_nfse=apenas_nfse,
            apenas_anexo_viii=apenas_anexo_viii,
            q=q,
        )

    @staticmethod
    def obter_cclasstrib(codigo: str):
        return obter_cclasstrib(codigo)

    @staticmethod
    def listar_servicos(
        item_lc116: Optional[str] = None,
        q: Optional[str] = None,
        limite: int = 400,
    ):
        return listar_servicos_ctribnac(item_lc116=item_lc116, q=q, limite=limite)

    @staticmethod
    def obter_servico(c_trib_nac: str):
        return obter_servico_ctribnac(c_trib_nac)

    @staticmethod
    def listar_lc116():
        return listar_subitens_lc116()

    @staticmethod
    def buscar_correlacoes(
        q: Optional[str] = None,
        item_lc116: Optional[str] = None,
        c_trib_nac: Optional[str] = None,
        c_nbs: Optional[str] = None,
        c_class_trib: Optional[str] = None,
        indop: Optional[str] = None,
        limite: int = 100,
    ):
        return buscar_correlacoes_anexo_viii(
            q=q,
            item_lc116=item_lc116,
            c_trib_nac=c_trib_nac,
            c_nbs=c_nbs,
            c_class_trib=c_class_trib,
            indop=indop,
            limite=limite,
        )

    @staticmethod
    def listar_indop():
        return listar_indop()

    @staticmethod
    def listar_favoritos():
        return listar_favoritos()

    # ==========================================================================
    # 2. Motor Tributário IBS/CBS + ISSQN + Federais (delegado ao pynfse.adn)
    # ==========================================================================

    @staticmethod
    def calcular_tributos(req: TaxCalculationRequest) -> Dict[str, Any]:
        return calcular_tributacao(
            valor_servicos=req.valor_servicos,
            regime_prestador=req.regime_prestador,
            cClassTrib=req.cClassTrib,
            cst=req.cst,
            cIndOp=req.cIndOp,
            cTribNac=req.cTribNac,
            cNBS=req.cNBS,
            data_competencia=req.data_competencia,
            ano_competencia=req.ano_competencia,
            desconto_incondicionado=req.desconto_incondicionado,
            desconto_condicionado=req.desconto_condicionado,
            deducao_reducao_iss=req.deducao_reducao_iss,
            reembolso_repasse_ressarcimento=req.reembolso_repasse_ressarcimento,
            deducao_reducao_ibscbs=req.deducao_reducao_ibscbs,
            aliquota_iss_informada=req.aliquota_iss,
            iss_retido=req.iss_retido,
            tp_ret_issqn=req.tp_ret_issqn,
            trib_issqn=req.trib_issqn,
            reter_federais=req.reter_federais,
            cst_pis_cofins=req.cst_pis_cofins,
            p_aliq_pis=req.p_aliq_pis,
            p_aliq_cofins=req.p_aliq_cofins,
            v_pis_informado=req.v_pis_informado,
            v_cofins_informado=req.v_cofins_informado,
            tp_ret_pis_cofins=req.tp_ret_pis_cofins,
            v_irrf_informado=req.v_irrf_informado,
            v_csll_informado=req.v_csll_informado,
            v_inss_informado=req.v_inss_informado,
            p_ibs_uf=req.p_ibs_uf,
            p_ibs_mun=req.p_ibs_mun,
            p_cbs=req.p_cbs,
            p_red_aliq_uf=req.p_red_aliq_uf,
            p_red_aliq_mun=req.p_red_aliq_mun,
            p_red_aliq_cbs=req.p_red_aliq_cbs,
            tp_ente_gov=req.tp_ente_gov,
            p_redutor_gov=req.p_redutor_gov,
            p_dif_uf=req.p_dif_uf,
            p_dif_mun=req.p_dif_mun,
            p_dif_cbs=req.p_dif_cbs,
            c_cred_pres=req.c_cred_pres,
            p_cred_pres_ibs=req.p_cred_pres_ibs,
            p_cred_pres_cbs=req.p_cred_pres_cbs,
            cst_reg=req.cst_reg,
            c_class_trib_reg=req.c_class_trib_reg,
            p_aliq_reg_ibs_uf=req.p_aliq_reg_ibs_uf,
            p_aliq_reg_ibs_mun=req.p_aliq_reg_ibs_mun,
            p_aliq_reg_cbs=req.p_aliq_reg_cbs,
            ind_doacao=req.ind_doacao,
            v_ibs_est_cred=req.v_ibs_est_cred,
            v_cbs_est_cred=req.v_cbs_est_cred,
            apurar_ibscbs_simples=req.apurar_ibscbs_simples,
        )

    @staticmethod
    def validar_ibscbs(req: TaxValidationRequest) -> Dict[str, Any]:
        return validar_regras_ibscbs(
            c_class_trib=req.cClassTrib,
            cst=req.cst,
            c_ind_op=req.cIndOp,
            c_trib_nac=req.cTribNac,
            c_nbs=req.cNBS,
            tp_oper=req.tpOper,
            tp_ente_gov=req.tpEnteGov,
            p_redutor_gov=req.pRedutorGov,
            ind_dest=req.indDest,
            tem_destinatario=req.temDestinatario,
            tem_imovel=req.temImovel,
            tem_ref_nfse=req.temRefNFSe,
            cst_reg=req.cstReg,
            c_class_trib_reg=req.cClassTribReg,
            p_dif_uf=req.pDifUF,
            p_dif_mun=req.pDifMun,
            p_dif_cbs=req.pDifCBS,
            ind_doacao=req.indDoacao,
            v_ibs_est_cred=req.vIBSEstCred,
            v_cbs_est_cred=req.vCBSEstCred,
        )

    # ==========================================================================
    # 3. Helpers Internos de Banco / Certificado / Disco (nfse_manager)
    # ==========================================================================

    @staticmethod
    def _resolver_prestador_e_certificado(
        db: Session,
        client_id: Optional[int],
        prestador_payload: Optional[Dict[str, Any]],
        cert_b64: Optional[str],
        cert_password: Optional[str],
        ambiente_req: str,
    ) -> Tuple[Optional[Client], Dict[str, Any], Optional[DpsSigner], str]:
        client_db: Optional[Client] = None
        if client_id:
            client_db = db.query(Client).filter(Client.id == client_id).first()
            if not client_db:
                raise HTTPException(status_code=404, detail=f"Cliente ID {client_id} não encontrado.")

        prestador = dict(prestador_payload or {})
        if client_db:
            prestador.setdefault("cnpj", client_db.cnpj)
            prestador.setdefault("razao_social", client_db.razao_social)
            prestador.setdefault("inscricao_municipal", client_db.inscricao_municipal)
            prestador.setdefault("codigo_municipio", client_db.codigo_municipio or "3201308")
            prestador.setdefault("regime", client_db.regime_tributario or "normal")
            prestador.setdefault("reg_ap_trib_sn", client_db.regime_apuracao_sn or "1")
            prestador.setdefault("reg_esp_trib", client_db.regime_especial or "0")
            prestador.setdefault("fone", client_db.telefone)
            prestador.setdefault("email", client_db.email)

        ambiente = ambiente_req or (
            client_db.ambiente_padrao if client_db and client_db.ambiente_padrao else "homologacao"
        )
        prestador["ambiente"] = ambiente

        signer: Optional[DpsSigner] = None
        if cert_b64 and cert_password is not None:
            try:
                pfx_bytes = base64.b64decode(cert_b64)
                signer = DpsSigner(pfx_data=pfx_bytes, pfx_password=cert_password)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Erro ao carregar certificado PFX enviado: {exc}") from exc
        elif client_db and client_db.cert_path:
            cert_file = Path(client_db.cert_path)
            if not cert_file.exists() and not cert_file.is_absolute():
                alt_cert = BACKEND_DIR / cert_file
                if alt_cert.exists():
                    cert_file = alt_cert
            if cert_file.exists():
                try:
                    signer = DpsSigner(pfx_path=str(cert_file), pfx_password=client_db.cert_password or "")
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Erro ao carregar certificado PFX do cliente '{client_db.razao_social}': {exc}",
                    ) from exc

        return client_db, prestador, signer, ambiente

    @staticmethod
    def _calcular_tributacao_se_necessario(
        prestador: Dict[str, Any],
        servico: Dict[str, Any],
        tributacao_informada: Optional[Dict[str, Any]],
        data_competencia: Optional[str],
    ) -> Dict[str, Any]:
        if tributacao_informada and "reforma_tributaria" in tributacao_informada and "iss" in tributacao_informada:
            return tributacao_informada

        trib_in = tributacao_informada or {}
        iss_in = trib_in.get("iss") or {}
        valor_serv = float(
            servico.get("valor") or servico.get("valor_servicos") or trib_in.get("valor_servicos") or 0.0
        )
        regime = str(prestador.get("regime") or prestador.get("regime_tributario") or "normal").lower()
        c_class = str(servico.get("cClassTrib") or trib_in.get("cClassTrib") or "000001")
        c_ind_op = str(servico.get("indop") or servico.get("cIndOp") or "100301")

        return calcular_tributacao(
            valor_servicos=valor_serv,
            regime_prestador=regime,
            cClassTrib=c_class,
            cst=servico.get("cst") or trib_in.get("cst"),
            cIndOp=c_ind_op,
            cTribNac=servico.get("cTribNac"),
            cNBS=servico.get("cNBS") or servico.get("nbs"),
            data_competencia=data_competencia,
            desconto_incondicionado=float(servico.get("desconto_incondicionado") or 0.0),
            desconto_condicionado=float(servico.get("desconto_condicionado") or 0.0),
            reembolso_repasse_ressarcimento=float(servico.get("reembolso_repasse_ressarcimento") or 0.0),
            deducao_reducao_ibscbs=float(servico.get("deducao_reducao_ibscbs") or 0.0),
            aliquota_iss_informada=servico.get("aliquota_iss") or iss_in.get("aliquota"),
            iss_retido=bool(servico.get("iss_retido") or iss_in.get("retido")),
            reter_federais=bool(servico.get("reter_federais") or trib_in.get("reter_federais")),
            p_ibs_uf=servico.get("p_ibs_uf") or trib_in.get("p_ibs_uf"),
            p_ibs_mun=servico.get("p_ibs_mun") or trib_in.get("p_ibs_mun"),
            p_cbs=servico.get("p_cbs") or trib_in.get("p_cbs"),
            tp_ente_gov=servico.get("tpEnteGov") or trib_in.get("tp_ente_gov"),
            p_redutor_gov=servico.get("pRedutorGov") or trib_in.get("p_redutor_gov"),
            p_dif_uf=servico.get("pDifUF") or trib_in.get("p_dif_uf"),
            p_dif_mun=servico.get("pDifMun") or trib_in.get("p_dif_mun"),
            p_dif_cbs=servico.get("pDifCBS") or trib_in.get("p_dif_cbs"),
            c_cred_pres=servico.get("cCredPres") or trib_in.get("c_cred_pres"),
            cst_reg=(servico.get("tributacao_regular") or {}).get("CSTReg") or trib_in.get("cst_reg"),
            c_class_trib_reg=(servico.get("tributacao_regular") or {}).get("cClassTribReg")
            or trib_in.get("c_class_trib_reg"),
        )

    @staticmethod
    def _salvar_xml_disco(conteudo_xml: str, subpasta: str, nome_arquivo: str) -> str:
        destino_dir = DOWNLOADS_DIR / "adn" / subpasta
        destino_dir.mkdir(parents=True, exist_ok=True)
        caminho = destino_dir / nome_arquivo
        caminho.write_text(conteudo_xml, encoding="utf-8")
        return str(caminho)

    # ==========================================================================
    # 4. Operações de Emissão, Cancelamento e Substituição via pynfse.adn
    # ==========================================================================

    @classmethod
    def preview_dps(cls, db: Session, req: EmitirDpsRequest) -> Dict[str, Any]:
        client_db, prestador, _, ambiente = cls._resolver_prestador_e_certificado(
            db=db,
            client_id=req.client_id,
            prestador_payload=req.prestador,
            cert_b64=None,
            cert_password=None,
            ambiente_req=req.ambiente,
        )

        serie = req.serie_dps or (client_db.serie_dps_padrao if client_db and client_db.serie_dps_padrao else "900")
        numero = req.numero_dps or ((client_db.ultimo_numero_dps or 0) + 1 if client_db else 1)

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=req.servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        try:
            xml_dps = build_dps_xml(
                prestador=prestador,
                tomador=req.tomador,
                intermediario=req.intermediario,
                servico=req.servico,
                tributacao=tributacao_calc,
                serie_dps=serie,
                numero_dps=numero,
                data_competencia=req.data_competencia,
                ambiente=ambiente,
                substituicao=req.substituicao,
                incluir_ibscbs=req.incluir_ibscbs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        validacao_xsd = XsdValidator.validar_dps(xml_dps)
        id_dps = formatar_id_dps(
            prestador.get("codigo_municipio", "3201308"),
            prestador.get("cnpj") or prestador.get("cpf") or "",
            serie,
            numero,
        )

        return {
            "id_dps": id_dps,
            "serie_dps": serie,
            "numero_dps": numero,
            "tributacao_calculada": tributacao_calc,
            "validacao_xsd": validacao_xsd,
            "xml_dps": xml_dps,
        }

    @classmethod
    async def emitir_dps(cls, db: Session, req: EmitirDpsRequest) -> Dict[str, Any]:
        client_db, prestador, signer, ambiente = cls._resolver_prestador_e_certificado(
            db=db,
            client_id=req.client_id,
            prestador_payload=req.prestador,
            cert_b64=req.certificado_pfx_b64,
            cert_password=req.senha_certificado,
            ambiente_req=req.ambiente,
        )

        serie = req.serie_dps or (client_db.serie_dps_padrao if client_db and client_db.serie_dps_padrao else "900")
        numero = req.numero_dps or ((client_db.ultimo_numero_dps or 0) + 1 if client_db else 1)

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=req.servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        try:
            xml_bruto = build_dps_xml(
                prestador=prestador,
                tomador=req.tomador,
                intermediario=req.intermediario,
                servico=req.servico,
                tributacao=tributacao_calc,
                serie_dps=serie,
                numero_dps=numero,
                data_competencia=req.data_competencia,
                ambiente=ambiente,
                substituicao=req.substituicao,
                incluir_ibscbs=req.incluir_ibscbs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        validacao_pre = XsdValidator.validar_dps(xml_bruto)
        if not validacao_pre["valido"]:
            raise HTTPException(
                status_code=422,
                detail={"mensagem": "XML da DPS falhou na validação XSD v1.01.", "erros": validacao_pre["erros"]},
            )

        id_dps = formatar_id_dps(
            prestador.get("codigo_municipio", "3201308"),
            prestador.get("cnpj") or prestador.get("cpf") or "",
            serie,
            numero,
        )

        cert_pem = None
        key_pem = None
        xml_assinado = xml_bruto
        assinado_com_certificado = False

        if signer is not None:
            xml_assinado = signer.sign_xml(xml_bruto, tag_to_sign="infDPS")
            cert_pem = signer.get_pem_certificate()
            key_pem = signer.get_pem_private_key()
            assinado_com_certificado = True

        validacao_pos = XsdValidator.validar_dps(xml_assinado)
        xml_dps_path = cls._salvar_xml_disco(xml_assinado, "dps", f"{id_dps}.xml")

        resultado_adn: Dict[str, Any] = {
            "sucesso": False,
            "status_code": 0,
            "mensagem": "Modo simulação/offline (transmitir=False ou sem certificado mTLS).",
        }
        if req.transmitir and assinado_com_certificado:
            adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
            resultado_adn = await adn_client.emitir_dps(xml_assinado)

        chave_gerada = resultado_adn.get("chave_acesso") or id_dps.replace("DPS", "").ljust(50, "0")[:50]
        reforma = tributacao_calc.get("reforma_tributaria") or {}
        iss_info = tributacao_calc.get("iss") or {}

        if client_db and (client_db.ultimo_numero_dps or 0) < int(numero):
            client_db.ultimo_numero_dps = int(numero)
            db.add(client_db)

        xml_nfse_path = None
        if resultado_adn.get("nfse_xml"):
            xml_nfse_path = cls._salvar_xml_disco(resultado_adn["nfse_xml"], "nfse", f"{chave_gerada}.xml")

        existing_inv = db.query(Invoice).filter(Invoice.chave == chave_gerada).first()
        status_nota = "gerada" if resultado_adn.get("sucesso") else "dps_gerada"
        ch_substituida = clean_digits((req.substituicao or {}).get("chSubstda")) or None

        if not existing_inv:
            nova_nota = Invoice(
                client_id=client_db.id if client_db else None,
                numero=str(numero),
                chave=chave_gerada,
                status=status_nota,
                tipo="emitidas",
                valor=float(tributacao_calc.get("valor_servicos") or 0.0),
                data_emissao=datetime.datetime.now(datetime.UTC),
                id_dps=id_dps,
                serie_dps=str(serie),
                numero_dps=int(numero),
                chave_substituida=ch_substituida,
                xml_dps_path=xml_dps_path,
                xml_path=xml_nfse_path or xml_dps_path,
                valor_iss=float(iss_info.get("valor") or 0.0),
                valor_ibs=float(reforma.get("valor_ibs") or 0.0),
                valor_cbs=float(reforma.get("valor_cbs") or 0.0),
                valor_liquido=float(tributacao_calc.get("valor_liquido") or 0.0),
                c_trib_nac=clean_digits(req.servico.get("cTribNac") or "010101").zfill(6),
                c_nbs=clean_digits(req.servico.get("cNBS") or ""),
                c_class_trib=str(reforma.get("cClassTrib") or "000001"),
                cst_ibscbs=str(reforma.get("cst") or "000"),
            )
            db.add(nova_nota)
            db.commit()
            db.refresh(nova_nota)
            invoice_id = nova_nota.id
        else:
            invoice_id = existing_inv.id
            db.commit()

        return {
            "invoice_id": invoice_id,
            "id_dps": id_dps,
            "chave_acesso": chave_gerada,
            "assinado_com_certificado": assinado_com_certificado,
            "validacao_xsd": validacao_pos,
            "tributacao": tributacao_calc,
            "xml_dps_path": xml_dps_path,
            "xml_gerado": xml_bruto,
            "xml_assinado": xml_assinado,
            "envio_adn": resultado_adn,
        }

    @classmethod
    async def cancelar_nfse(cls, db: Session, req: CancelarNfseRequest) -> Dict[str, Any]:
        invoice_db: Optional[Invoice] = None
        if req.invoice_id:
            invoice_db = db.query(Invoice).filter(Invoice.id == req.invoice_id).first()
        if not invoice_db and req.chave_nfse:
            chave_busca = clean_digits(req.chave_nfse)
            invoice_db = db.query(Invoice).filter(Invoice.chave == chave_busca).first()

        effective_client_id = req.client_id or (invoice_db.client_id if invoice_db else None)
        client_db, prestador, signer, ambiente = cls._resolver_prestador_e_certificado(
            db=db,
            client_id=effective_client_id,
            prestador_payload=None,
            cert_b64=req.certificado_pfx_b64,
            cert_password=req.senha_certificado,
            ambiente_req=req.ambiente,
        )

        doc_autor = clean_digits(req.documento_autor or prestador.get("cnpj") or "")
        if not doc_autor:
            raise HTTPException(
                status_code=400,
                detail="Informe 'documento_autor' (CNPJ/CPF) ou 'client_id' para identificar o autor do cancelamento.",
            )

        try:
            xml_bruto = build_evento_cancelamento_xml(
                chave_nfse=req.chave_nfse,
                documento_autor=doc_autor,
                motivo_codigo=req.motivo_codigo,
                motivo_descricao=req.motivo_descricao,
                ambiente=1 if ambiente == "producao" else 2,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        validacao_pre = XsdValidator.validar_evento(xml_bruto)
        if not validacao_pre["valido"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "mensagem": "XML do evento de cancelamento falhou na validação XSD v1.01.",
                    "erros": validacao_pre["erros"],
                },
            )

        cert_pem = None
        key_pem = None
        xml_assinado = xml_bruto
        assinado_com_certificado = False

        if signer is not None:
            xml_assinado = signer.sign_xml(xml_bruto, tag_to_sign="infPedReg")
            cert_pem = signer.get_pem_certificate()
            key_pem = signer.get_pem_private_key()
            assinado_com_certificado = True

        validacao_pos = XsdValidator.validar_evento(xml_assinado)
        chave_limpa = clean_digits(req.chave_nfse)
        xml_evento_path = cls._salvar_xml_disco(xml_assinado, "eventos", f"PRE{chave_limpa}101101.xml")

        resultado_adn: Dict[str, Any] = {
            "sucesso": False,
            "status_code": 0,
            "mensagem": "Evento de cancelamento gerado e validado localmente (modo simulação ou transmitir=False).",
        }
        if req.transmitir and assinado_com_certificado:
            adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
            resultado_adn = await adn_client.enviar_evento(xml_assinado, chave_nfse=chave_limpa)

        if invoice_db:
            if resultado_adn.get("sucesso") or not req.transmitir:
                invoice_db.status = "cancelada"
            invoice_db.motivo_cancelamento = f"[{req.motivo_codigo}] {req.motivo_descricao}"
            invoice_db.data_cancelamento = datetime.datetime.now(datetime.UTC)
            invoice_db.xml_evento_path = xml_evento_path
            db.add(invoice_db)
            db.commit()

        return {
            "chave_nfse": chave_limpa,
            "invoice_id": invoice_db.id if invoice_db else None,
            "assinado_com_certificado": assinado_com_certificado,
            "validacao_xsd": validacao_pos,
            "xml_evento_path": xml_evento_path,
            "xml_evento": xml_bruto,
            "xml_assinado": xml_assinado,
            "retorno_adn": resultado_adn,
        }

    @classmethod
    async def substituir_nfse(cls, db: Session, req: SubstituirNfseRequest) -> Dict[str, Any]:
        invoice_orig: Optional[Invoice] = None
        if req.invoice_id_substituida:
            invoice_orig = db.query(Invoice).filter(Invoice.id == req.invoice_id_substituida).first()
        if not invoice_orig and req.chave_nfse_substituida:
            chave_orig_busca = clean_digits(req.chave_nfse_substituida)
            invoice_orig = db.query(Invoice).filter(Invoice.chave == chave_orig_busca).first()

        effective_client_id = req.client_id or (invoice_orig.client_id if invoice_orig else None)
        client_db, prestador, signer, ambiente = cls._resolver_prestador_e_certificado(
            db=db,
            client_id=effective_client_id,
            prestador_payload=req.prestador,
            cert_b64=req.certificado_pfx_b64,
            cert_password=req.senha_certificado,
            ambiente_req=req.ambiente,
        )

        chave_orig = clean_digits(req.chave_nfse_substituida)
        if len(chave_orig) != 50:
            raise HTTPException(
                status_code=400,
                detail=f"Chave da NFS-e a ser substituída deve conter 50 dígitos (informado: {len(chave_orig)}).",
            )

        substituicao_dict = {
            "chSubstda": chave_orig,
            "cMotivo": str(req.motivo_codigo).zfill(2),
            "xMotivo": req.motivo_descricao,
        }

        serie = req.serie_dps or (client_db.serie_dps_padrao if client_db and client_db.serie_dps_padrao else "900")
        numero = req.numero_dps or ((client_db.ultimo_numero_dps or 0) + 1 if client_db else 1)

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=req.servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        try:
            xml_dps_bruto = build_dps_xml(
                prestador=prestador,
                tomador=req.tomador,
                intermediario=req.intermediario,
                servico=req.servico,
                tributacao=tributacao_calc,
                serie_dps=serie,
                numero_dps=numero,
                data_competencia=req.data_competencia,
                ambiente=ambiente,
                substituicao=substituicao_dict,
                incluir_ibscbs=req.incluir_ibscbs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        validacao_dps_pre = XsdValidator.validar_dps(xml_dps_bruto)
        if not validacao_dps_pre["valido"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "mensagem": "XML da DPS substituta falhou na validação XSD v1.01.",
                    "erros": validacao_dps_pre["erros"],
                },
            )

        id_dps = formatar_id_dps(
            prestador.get("codigo_municipio", "3201308"),
            prestador.get("cnpj") or prestador.get("cpf") or "",
            serie,
            numero,
        )

        cert_pem = None
        key_pem = None
        xml_dps_assinado = xml_dps_bruto
        assinado_com_certificado = False

        if signer is not None:
            xml_dps_assinado = signer.sign_xml(xml_dps_bruto, tag_to_sign="infDPS")
            cert_pem = signer.get_pem_certificate()
            key_pem = signer.get_pem_private_key()
            assinado_com_certificado = True

        validacao_dps_pos = XsdValidator.validar_dps(xml_dps_assinado)
        xml_dps_path = cls._salvar_xml_disco(xml_dps_assinado, "dps", f"{id_dps}_subst.xml")

        resultado_adn: Dict[str, Any] = {
            "sucesso": False,
            "status_code": 0,
            "mensagem": "DPS de substituição gerada e validada localmente (modo simulação ou transmitir=False).",
        }
        if req.transmitir and assinado_com_certificado:
            adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
            resultado_adn = await adn_client.emitir_dps(xml_dps_assinado)

        chave_substituta = (
            resultado_adn.get("chave_acesso")
            or (clean_digits(req.chave_nfse_substituta_evento) if req.chave_nfse_substituta_evento else None)
            or id_dps.replace("DPS", "").ljust(50, "0")[:50]
        )

        doc_autor = clean_digits(prestador.get("cnpj") or prestador.get("cpf") or "")
        xml_evento_e105102 = None
        validacao_evento_e105102 = None
        xml_evento_path = None

        if len(doc_autor) in (11, 14) and len(chave_substituta) == 50:
            xml_evt_bruto = build_evento_substituicao_xml(
                chave_nfse_substituida=chave_orig,
                chave_nfse_substituta=chave_substituta,
                documento_autor=doc_autor,
                motivo_codigo=str(req.motivo_codigo).zfill(2),
                motivo_descricao=req.motivo_descricao,
                ambiente=1 if ambiente == "producao" else 2,
            )
            if signer is not None:
                xml_evento_e105102 = signer.sign_xml(xml_evt_bruto, tag_to_sign="infPedReg")
            else:
                xml_evento_e105102 = xml_evt_bruto
            validacao_evento_e105102 = XsdValidator.validar_evento(xml_evento_e105102)
            xml_evento_path = cls._salvar_xml_disco(xml_evento_e105102, "eventos", f"PRE{chave_orig}105102.xml")

        if invoice_orig:
            invoice_orig.status = "substituida"
            invoice_orig.chave_substituta = chave_substituta
            invoice_orig.motivo_cancelamento = f"[Substituição {req.motivo_codigo}] {req.motivo_descricao}"
            invoice_orig.xml_evento_path = xml_evento_path
            db.add(invoice_orig)

        if client_db and (client_db.ultimo_numero_dps or 0) < int(numero):
            client_db.ultimo_numero_dps = int(numero)
            db.add(client_db)

        reforma = tributacao_calc.get("reforma_tributaria") or {}
        iss_info = tributacao_calc.get("iss") or {}
        nova_nota = db.query(Invoice).filter(Invoice.chave == chave_substituta).first()
        if not nova_nota:
            nova_nota = Invoice(
                client_id=client_db.id if client_db else None,
                numero=str(numero),
                chave=chave_substituta,
                status="gerada" if resultado_adn.get("sucesso") else "dps_substituta",
                tipo="emitidas",
                valor=float(tributacao_calc.get("valor_servicos") or 0.0),
                data_emissao=datetime.datetime.now(datetime.UTC),
                id_dps=id_dps,
                serie_dps=str(serie),
                numero_dps=int(numero),
                chave_substituida=chave_orig,
                xml_dps_path=xml_dps_path,
                xml_path=xml_dps_path,
                valor_iss=float(iss_info.get("valor") or 0.0),
                valor_ibs=float(reforma.get("valor_ibs") or 0.0),
                valor_cbs=float(reforma.get("valor_cbs") or 0.0),
                valor_liquido=float(tributacao_calc.get("valor_liquido") or 0.0),
                c_trib_nac=clean_digits(req.servico.get("cTribNac") or "010101").zfill(6),
                c_nbs=clean_digits(req.servico.get("cNBS") or ""),
                c_class_trib=str(reforma.get("cClassTrib") or "000001"),
                cst_ibscbs=str(reforma.get("cst") or "000"),
            )
            db.add(nova_nota)

        db.commit()
        db.refresh(nova_nota)

        return {
            "invoice_id_substituida": invoice_orig.id if invoice_orig else None,
            "invoice_id_substituta": nova_nota.id,
            "chave_nfse_substituida": chave_orig,
            "chave_nfse_substituta": chave_substituta,
            "id_dps_substituta": id_dps,
            "assinado_com_certificado": assinado_com_certificado,
            "validacao_xsd_dps": validacao_dps_pos,
            "validacao_xsd_evento_e105102": validacao_evento_e105102,
            "tributacao": tributacao_calc,
            "xml_dps_substituta": xml_dps_assinado,
            "xml_evento_e105102": xml_evento_e105102,
            "envio_adn": resultado_adn,
        }

    @staticmethod
    async def consultar_parametros_municipais(cod_ibge: str, ambiente: str = "homologacao") -> Dict[str, Any]:
        client = AdnNfseClient(ambiente=ambiente)
        return await client.consultar_parametros_municipais(cod_ibge)

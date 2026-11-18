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
import json
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.core.config import get_downloads_dir, resolve_storage_path, to_storage_relative_path
from app.models import Client, Customer, Invoice, ServiceItem
from app.schemas import (
    CancelarNfseRequest,
    EmitirDpsLoteRequest,
    EmitirDpsRequest,
    EnviarEmailNfseRequest,
    ReenviarFilaRequest,
    SincronizarCofreAdnRequest,
    SubstituirNfseRequest,
    TaxCalculationRequest,
    TaxValidationRequest,
)
from app.services.email_service import EmailService
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


DOWNLOADS_DIR = get_downloads_dir()


class AdnService:
    """Serviço unificado do nfse_manager que integra o banco local ao pacote `pynfse.adn`."""

    _DPS_LOCKS: Dict[int, threading.Lock] = {}
    _DPS_LOCKS_GUARD = threading.Lock()

    @classmethod
    def _get_dps_lock(cls, client_id: int) -> threading.Lock:
        with cls._DPS_LOCKS_GUARD:
            if client_id not in cls._DPS_LOCKS:
                cls._DPS_LOCKS[client_id] = threading.Lock()
            return cls._DPS_LOCKS[client_id]

    @classmethod
    def reservar_proximo_numero_dps(
        cls,
        db: Session,
        client_id: Optional[int],
        serie_dps: Optional[str] = None,
        numero_informado: Optional[int] = None,
        codigo_municipio: Optional[str] = None,
        documento_prestador: Optional[str] = None,
    ) -> Tuple[str, int, str]:
        """Reserva atomicamente o próximo número da DPS para o prestador e retorna `(serie, numero, id_dps)`."""
        if not client_id:
            serie = (serie_dps or "900").strip() or "900"
            numero = int(numero_informado or 1)
            id_dps = (
                formatar_id_dps(codigo_municipio or "3201308", documento_prestador or "", serie, numero)
                if documento_prestador
                else ""
            )
            return serie, numero, id_dps

        dialect = db.bind.dialect.name if db.bind is not None else ""
        lock = cls._get_dps_lock(int(client_id))
        with lock:
            if dialect == "postgresql":
                client_row = db.query(Client).filter(Client.id == client_id).with_for_update().first()
            else:
                client_row = db.query(Client).filter(Client.id == client_id).first()

            if not client_row:
                raise HTTPException(status_code=404, detail=f"Cliente ID {client_id} não encontrado.")

            serie = (serie_dps or client_row.serie_dps_padrao or "900").strip() or "900"
            if numero_informado is not None:
                numero = int(numero_informado)
                if (client_row.ultimo_numero_dps or 0) < numero:
                    client_row.ultimo_numero_dps = numero
                    db.add(client_row)
                db.commit()
            elif dialect == "sqlite":
                db.execute(
                    update(Client)
                    .where(Client.id == client_id)
                    .values(ultimo_numero_dps=func.coalesce(Client.ultimo_numero_dps, 0) + 1)
                )
                db.commit()
                db.refresh(client_row)
                numero = int(client_row.ultimo_numero_dps or 1)
            else:
                numero = int(client_row.ultimo_numero_dps or 0) + 1
                client_row.ultimo_numero_dps = numero
                db.add(client_row)
                db.commit()
                db.refresh(client_row)

            cod_mun = codigo_municipio or client_row.codigo_municipio or "3201308"
            doc_prest = documento_prestador or client_row.cnpj or ""
            id_dps = formatar_id_dps(cod_mun, doc_prest, serie, numero)
            return serie, numero, id_dps

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
    def listar_combinacoes_por_nbs(c_nbs: str, c_trib_nac: Optional[str] = None) -> Dict[str, Any]:
        """Retorna as opções compatíveis de cClassTrib e cIndOp para um código NBS (9 dígitos)."""
        nbs_clean = clean_digits(c_nbs or "").zfill(9) if clean_digits(c_nbs or "") else ""
        ctrib_clean = clean_digits(c_trib_nac or "").zfill(6) if clean_digits(c_trib_nac or "") else None

        correlacoes = (
            buscar_correlacoes_anexo_viii(c_nbs=nbs_clean, c_trib_nac=ctrib_clean, limite=500)
            if nbs_clean
            else []
        )
        if not correlacoes and nbs_clean and ctrib_clean:
            correlacoes = buscar_correlacoes_anexo_viii(c_nbs=nbs_clean, limite=500)

        indop_lookup = {
            str(i.get("cIndOp") or "").zfill(6): i.get("local_incidencia") or ""
            for i in listar_indop()
        }

        cclasstrib_map: Dict[str, Dict[str, Any]] = {}
        cindop_map: Dict[str, Dict[str, Any]] = {}
        combinacoes: List[Dict[str, Any]] = []

        for corr in correlacoes:
            ct = str(corr.get("cClassTrib") or "").strip().zfill(6)
            indop = str(corr.get("indop") or corr.get("cIndOp") or "").strip().zfill(6)
            cst = str(corr.get("cst") or "").strip().zfill(3) if corr.get("cst") else ""
            if ct and ct not in cclasstrib_map:
                meta = obter_cclasstrib(ct) or {}
                cclasstrib_map[ct] = {
                    "codigo": ct,
                    "cst": cst or str(meta.get("cst") or ct[:3]).zfill(3),
                    "nome": corr.get("nome_cClassTrib") or meta.get("nome") or f"Classificação {ct}",
                    "nome_reduzido": meta.get("nome_reduzido") or corr.get("nome_cClassTrib") or "",
                    "perc_red_ibs": corr.get("perc_red_ibs", meta.get("perc_red_ibs", 0.0)),
                    "perc_red_cbs": corr.get("perc_red_cbs", meta.get("perc_red_cbs", 0.0)),
                }
            if indop and indop not in cindop_map:
                cindop_map[indop] = {
                    "cIndOp": indop,
                    "local_incidencia": corr.get("local_incidencia_ibs")
                    or indop_lookup.get(indop)
                    or "Local de incidência padrão",
                }
            combinacoes.append(
                {
                    "cTribNac": corr.get("cTribNac"),
                    "cNBS": corr.get("cNBS") or nbs_clean,
                    "cClassTrib": ct,
                    "cst": cst,
                    "indop": indop,
                    "nome_cClassTrib": corr.get("nome_cClassTrib") or "",
                    "local_incidencia_ibs": corr.get("local_incidencia_ibs") or indop_lookup.get(indop) or "",
                }
            )

        return {
            "c_nbs": nbs_clean,
            "c_trib_nac": ctrib_clean,
            "possui_correlacoes": len(combinacoes) > 0,
            "cclasstrib_compativeis": list(cclasstrib_map.values()),
            "cindop_compativeis": list(cindop_map.values()),
            "combinacoes": combinacoes,
        }

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
        res = validar_regras_ibscbs(
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

        # Cruzamento próprio NBS × cClassTrib × cIndOp via Anexo VIII (aviso preventivo não bloqueante)
        if req.cNBS:
            comb = AdnService.listar_combinacoes_por_nbs(req.cNBS, req.cTribNac)
            if comb["possui_correlacoes"]:
                ct_limpo = clean_digits(req.cClassTrib or "").zfill(6)
                indop_limpo = clean_digits(req.cIndOp or "").zfill(6)
                cts_validos = [c["codigo"] for c in comb["cclasstrib_compativeis"]]
                indops_validos = [i["cIndOp"] for i in comb["cindop_compativeis"]]
                pares_validos = {(c["cClassTrib"], c["indop"]) for c in comb["combinacoes"]}

                avisos = list(res.get("avisos") or [])
                if cts_validos and ct_limpo not in cts_validos:
                    avisos.append(
                        {
                            "codigo": "ANEXO_VIII_CCLASSTRIB",
                            "mensagem": (
                                f"cClassTrib '{ct_limpo}' não consta no Anexo VIII para a NBS '{comb['c_nbs']}'. "
                                f"Compatíveis previstos: {', '.join(cts_validos)}."
                            ),
                        }
                    )
                if indops_validos and indop_limpo not in indops_validos:
                    avisos.append(
                        {
                            "codigo": "ANEXO_VIII_INDOP",
                            "mensagem": (
                                f"cIndOp '{indop_limpo}' não consta no Anexo VIII para a NBS '{comb['c_nbs']}'. "
                                f"Compatíveis previstos: {', '.join(indops_validos)}."
                            ),
                        }
                    )
                if ct_limpo in cts_validos and indop_limpo in indops_validos and (ct_limpo, indop_limpo) not in pares_validos:
                    avisos.append(
                        {
                            "codigo": "ANEXO_VIII_PAR",
                            "mensagem": (
                                f"A combinação NBS '{comb['c_nbs']}' × cClassTrib '{ct_limpo}' × cIndOp '{indop_limpo}' "
                                "não aparece junta na mesma linha do Anexo VIII (verifique se houve alteração por NT)."
                            ),
                        }
                    )
                res["avisos"] = avisos

        return res

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
            cert_file = resolve_storage_path(client_db.cert_path, kind="certs")
            if cert_file and cert_file.exists():
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
        destino_dir = get_downloads_dir() / "adn" / subpasta
        destino_dir.mkdir(parents=True, exist_ok=True)
        caminho = destino_dir / nome_arquivo
        caminho.write_text(conteudo_xml, encoding="utf-8")
        return to_storage_relative_path(caminho, "downloads")

    @staticmethod
    def _gerar_pdf_danfse(xml_path: Optional[str], nome_base: str, status: str = "NORMAL") -> Optional[str]:
        resolved_xml = resolve_storage_path(xml_path, kind="downloads") if xml_path else None
        if not resolved_xml or not resolved_xml.exists():
            return None
        try:
            from pynfse.danfse_generator import DanfseGenerator

            pdf_dir = get_downloads_dir() / "adn" / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / f"{nome_base}.pdf"
            gen = DanfseGenerator(str(resolved_xml), status=status)
            gen.gerar_pdf(str(pdf_path))
            if pdf_path.exists():
                return to_storage_relative_path(pdf_path, "downloads")
        except Exception:
            pass
        return None

    @staticmethod
    def _resolver_tomador_e_servico(
        db: Session,
        customer_id: Optional[int],
        service_item_id: Optional[int],
        tomador_payload: Optional[Dict[str, Any]],
        servico_payload: Optional[Dict[str, Any]],
        prestador: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        tomador = dict(tomador_payload or {})
        if customer_id:
            cust = db.query(Customer).filter(Customer.id == customer_id).first()
            if not cust:
                raise HTTPException(status_code=404, detail=f"Tomador recorrente ID {customer_id} não encontrado.")
            tomador.setdefault("documento", cust.documento)
            tomador.setdefault("razao_social", cust.razao_social)
            if cust.inscricao_municipal:
                tomador.setdefault("inscricao_municipal", cust.inscricao_municipal)
            if cust.email:
                tomador.setdefault("email", cust.email)
            if cust.telefone:
                tomador.setdefault("fone", cust.telefone)
            end = dict(tomador.get("endereco") or {})
            end.setdefault("codigo_municipio", cust.codigo_municipio or "3201308")
            end.setdefault("cep", cust.cep or "")
            end.setdefault("logradouro", cust.logradouro or "")
            end.setdefault("numero", cust.numero or "S/N")
            if cust.complemento:
                end.setdefault("complemento", cust.complemento)
            end.setdefault("bairro", cust.bairro or "CENTRO")
            tomador["endereco"] = end

        servico = dict(servico_payload or {})
        if service_item_id:
            s_item = db.query(ServiceItem).filter(ServiceItem.id == service_item_id).first()
            if not s_item:
                raise HTTPException(status_code=404, detail=f"Serviço recorrente ID {service_item_id} não encontrado.")
            servico.setdefault("cTribNac", s_item.c_trib_nac or "010101")
            if s_item.c_nbs:
                servico.setdefault("cNBS", s_item.c_nbs)
            servico.setdefault("cClassTrib", s_item.c_class_trib or "000001")
            servico.setdefault("cst", s_item.cst_ibscbs or "000")
            servico.setdefault("indop", s_item.c_ind_op or "100301")
            servico.setdefault("descricao", s_item.descricao or s_item.titulo)
            if not servico.get("valor") and not servico.get("valor_servicos"):
                servico["valor"] = float(s_item.valor_unitario or 0.0)
            if s_item.aliquota_iss is not None:
                servico.setdefault("aliquota_iss", float(s_item.aliquota_iss))
            servico.setdefault("iss_retido", bool(s_item.iss_retido))
            servico.setdefault("reter_federais", bool(s_item.reter_federais))

        servico.setdefault("codigo_municipio_prestacao", prestador.get("codigo_municipio") or "3201308")
        return tomador, servico

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
        tomador, servico = cls._resolver_tomador_e_servico(
            db=db,
            customer_id=req.customer_id,
            service_item_id=req.service_item_id,
            tomador_payload=req.tomador,
            servico_payload=req.servico,
            prestador=prestador,
        )

        serie = req.serie_dps or (client_db.serie_dps_padrao if client_db and client_db.serie_dps_padrao else "900")
        numero = req.numero_dps or ((client_db.ultimo_numero_dps or 0) + 1 if client_db else 1)

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        try:
            xml_dps = build_dps_xml(
                prestador=prestador,
                tomador=tomador,
                intermediario=req.intermediario,
                servico=servico,
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
            "prestador_resolvido": prestador,
            "tomador_resolvido": tomador,
            "servico_resolvido": servico,
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
        tomador, servico = cls._resolver_tomador_e_servico(
            db=db,
            customer_id=req.customer_id,
            service_item_id=req.service_item_id,
            tomador_payload=req.tomador,
            servico_payload=req.servico,
            prestador=prestador,
        )

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        if client_db:
            serie, numero, id_dps = cls.reservar_proximo_numero_dps(
                db=db,
                client_id=client_db.id,
                serie_dps=req.serie_dps or client_db.serie_dps_padrao,
                numero_informado=req.numero_dps,
                codigo_municipio=prestador.get("codigo_municipio"),
                documento_prestador=prestador.get("cnpj") or prestador.get("cpf"),
            )
            db.refresh(client_db)
        else:
            serie = req.serie_dps or "900"
            numero = req.numero_dps or 1
            id_dps = formatar_id_dps(
                prestador.get("codigo_municipio", "3201308"),
                prestador.get("cnpj") or prestador.get("cpf") or "",
                serie,
                numero,
            )

        try:
            xml_bruto = build_dps_xml(
                prestador=prestador,
                tomador=tomador,
                intermediario=req.intermediario,
                servico=servico,
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
        tentativas_envio = 0
        ultimo_erro_envio: Optional[str] = None
        foi_para_contingencia = False

        if req.transmitir and assinado_com_certificado:
            tentativas_envio = 1
            try:
                adn_client = AdnNfseClient(ambiente=ambiente, cert_pem=cert_pem, key_pem=key_pem)
                resultado_adn = await adn_client.emitir_dps(xml_assinado)
                if not resultado_adn.get("sucesso"):
                    sc = int(resultado_adn.get("status_code") or 0)
                    ultimo_erro_envio = str(resultado_adn.get("mensagem") or resultado_adn.get("erro") or f"HTTP {sc}")
                    if sc == 0 or sc >= 500:
                        foi_para_contingencia = True
            except Exception as exc:
                ultimo_erro_envio = f"Falha de rede/conexão: {exc}"
                foi_para_contingencia = True
                resultado_adn = {
                    "sucesso": False,
                    "status_code": 0,
                    "mensagem": f"Sem conexão com a Sefin/ADN. Nota salva na Fila de Contingência ({exc}).",
                }
        elif req.transmitir and not assinado_com_certificado:
            foi_para_contingencia = True
            ultimo_erro_envio = "Aguardando certificado A1 para assinatura e transmissão."

        chave_gerada = resultado_adn.get("chave_acesso") or id_dps.replace("DPS", "").ljust(50, "0")[:50]
        reforma = tributacao_calc.get("reforma_tributaria") or {}
        iss_info = tributacao_calc.get("iss") or {}

        if client_db and (client_db.ultimo_numero_dps or 0) < int(numero):
            client_db.ultimo_numero_dps = int(numero)
            db.add(client_db)

        xml_nfse_path = None
        if resultado_adn.get("nfse_xml"):
            xml_nfse_path = cls._salvar_xml_disco(resultado_adn["nfse_xml"], "nfse", f"{chave_gerada}.xml")

        xml_principal_path = xml_nfse_path or xml_dps_path
        pdf_gerado_path = cls._gerar_pdf_danfse(xml_principal_path, chave_gerada, status="NORMAL")

        existing_inv = db.query(Invoice).filter(Invoice.chave == chave_gerada).first()
        if resultado_adn.get("sucesso"):
            status_nota = "gerada"
        elif foi_para_contingencia:
            status_nota = "fila_contingencia"
        else:
            status_nota = "dps_gerada"

        ch_substituida = clean_digits((req.substituicao or {}).get("chSubstda")) or None
        tomador_doc = clean_digits(tomador.get("documento") or tomador.get("cnpj") or tomador.get("cpf") or "")
        tomador_nome = tomador.get("razao_social") or tomador.get("nome") or ""
        tomador_email = req.email_destinatario or tomador.get("email") or ""

        payload_resumo = json.dumps(
            {
                "prestador": prestador,
                "tomador": tomador,
                "servico": servico,
                "ambiente": ambiente,
                "data_competencia": req.data_competencia,
            },
            ensure_ascii=False,
        )

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
                xml_path=xml_principal_path,
                pdf_path=pdf_gerado_path,
                valor_iss=float(iss_info.get("valor") or 0.0),
                valor_ibs=float(reforma.get("valor_ibs") or 0.0),
                valor_cbs=float(reforma.get("valor_cbs") or 0.0),
                valor_liquido=float(tributacao_calc.get("valor_liquido") or 0.0),
                c_trib_nac=clean_digits(servico.get("cTribNac") or "010101").zfill(6),
                c_nbs=clean_digits(servico.get("cNBS") or ""),
                c_class_trib=str(reforma.get("cClassTrib") or "000001"),
                cst_ibscbs=str(reforma.get("cst") or "000"),
                tomador_documento=tomador_doc or None,
                tomador_nome=tomador_nome or None,
                tomador_email=tomador_email or None,
                tentativas_envio=tentativas_envio,
                ultimo_erro_envio=ultimo_erro_envio,
                payload_dps_json=payload_resumo,
            )
            db.add(nova_nota)
            db.commit()
            db.refresh(nova_nota)
            invoice_obj = nova_nota
        else:
            existing_inv.status = status_nota
            existing_inv.xml_dps_path = xml_dps_path
            existing_inv.xml_path = xml_principal_path
            if pdf_gerado_path:
                existing_inv.pdf_path = pdf_gerado_path
            existing_inv.tentativas_envio = (existing_inv.tentativas_envio or 0) + tentativas_envio
            existing_inv.ultimo_erro_envio = ultimo_erro_envio
            db.commit()
            db.refresh(existing_inv)
            invoice_obj = existing_inv

        email_resultado = None
        deve_enviar_email = req.enviar_email or bool(client_db and client_db.enviar_email_automatico)
        if deve_enviar_email and client_db and tomador_email and EmailService.obter_config_smtp(client_db):
            try:
                email_resultado = EmailService.enviar_nfse_por_email(
                    client_db=client_db,
                    invoice=invoice_obj,
                    destinatario=tomador_email,
                )
            except Exception as exc:
                email_resultado = {"sucesso": False, "erro": str(exc)}

        return {
            "invoice_id": invoice_obj.id,
            "id_dps": id_dps,
            "chave_acesso": chave_gerada,
            "status_nota": status_nota,
            "assinado_com_certificado": assinado_com_certificado,
            "validacao_xsd": validacao_pos,
            "tributacao": tributacao_calc,
            "xml_dps_path": xml_dps_path,
            "pdf_path": invoice_obj.pdf_path,
            "xml_gerado": xml_bruto,
            "xml_assinado": xml_assinado,
            "envio_adn": resultado_adn,
            "email_enviado": email_resultado,
        }

    @classmethod
    async def emitir_dps_lote(cls, db: Session, req: EmitirDpsLoteRequest) -> Dict[str, Any]:
        """Emite múltiplas DPS sequencialmente para o mesmo prestador, consolidando o resultado."""
        resultados: List[Dict[str, Any]] = []
        autorizadas = 0
        fila_contingencia = 0
        geradas_offline = 0
        erros = 0

        for idx, item in enumerate(req.itens, start=1):
            item_req = EmitirDpsRequest(
                client_id=req.client_id,
                customer_id=item.customer_id,
                service_item_id=item.service_item_id,
                ambiente=req.ambiente,
                tomador=dict(item.tomador or {}),
                servico=dict(item.servico or {}),
                tributacao=item.tributacao,
                serie_dps=item.serie_dps or req.serie_dps or "900",
                numero_dps=item.numero_dps,
                data_competencia=item.data_competencia or req.data_competencia,
                incluir_ibscbs=item.incluir_ibscbs if item.incluir_ibscbs is not None else req.incluir_ibscbs,
                transmitir=req.transmitir,
                enviar_email=item.enviar_email if item.enviar_email is not None else req.enviar_email,
                email_destinatario=item.email_destinatario,
            )
            try:
                res = await cls.emitir_dps(db=db, req=item_req)
                status_nota = res.get("status_nota", "dps_gerada")
                if status_nota == "gerada":
                    autorizadas += 1
                elif status_nota == "fila_contingencia":
                    fila_contingencia += 1
                else:
                    geradas_offline += 1
                resultados.append(
                    {
                        "indice": idx,
                        "sucesso": True,
                        "customer_id": item.customer_id,
                        "service_item_id": item.service_item_id,
                        "invoice_id": res.get("invoice_id"),
                        "id_dps": res.get("id_dps"),
                        "chave_acesso": res.get("chave_acesso"),
                        "status_nota": status_nota,
                        "valor_servicos": (res.get("tributacao") or {}).get("valor_servicos"),
                        "valor_liquido": (res.get("tributacao") or {}).get("valor_liquido"),
                    }
                )
            except HTTPException as exc:
                db.rollback()
                erros += 1
                resultados.append(
                    {
                        "indice": idx,
                        "sucesso": False,
                        "status_nota": "erro",
                        "customer_id": item.customer_id,
                        "service_item_id": item.service_item_id,
                        "erro": exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False),
                    }
                )
            except Exception as exc:
                db.rollback()
                erros += 1
                resultados.append(
                    {
                        "indice": idx,
                        "sucesso": False,
                        "status_nota": "erro",
                        "customer_id": item.customer_id,
                        "service_item_id": item.service_item_id,
                        "erro": str(exc),
                    }
                )

        return {
            "total": len(req.itens),
            "autorizadas": autorizadas,
            "fila_contingencia": fila_contingencia,
            "geradas_offline": geradas_offline,
            "erros": erros,
            "resultados": resultados,
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

        tributacao_calc = cls._calcular_tributacao_se_necessario(
            prestador=prestador,
            servico=req.servico,
            tributacao_informada=req.tributacao,
            data_competencia=req.data_competencia,
        )

        if client_db:
            serie, numero, id_dps = cls.reservar_proximo_numero_dps(
                db=db,
                client_id=client_db.id,
                serie_dps=req.serie_dps or client_db.serie_dps_padrao,
                numero_informado=req.numero_dps,
                codigo_municipio=prestador.get("codigo_municipio"),
                documento_prestador=prestador.get("cnpj") or prestador.get("cpf"),
            )
            db.refresh(client_db)
        else:
            serie = req.serie_dps or "900"
            numero = req.numero_dps or 1
            id_dps = formatar_id_dps(
                prestador.get("codigo_municipio", "3201308"),
                prestador.get("cnpj") or prestador.get("cpf") or "",
                serie,
                numero,
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

    # ==========================================================================
    # 5. Fila de Contingência Offline, Envio de E-mail e Cofre ADN (DistDFe/NSU)
    # ==========================================================================

    @staticmethod
    def listar_fila_contingencia(db: Session, client_id: Optional[int] = None) -> List[Invoice]:
        query = db.query(Invoice).filter(Invoice.status.in_(["dps_gerada", "fila_contingencia"]))
        if client_id is not None:
            query = query.filter(Invoice.client_id == client_id)
        return query.order_by(Invoice.data_emissao.desc()).all()

    @staticmethod
    def cancelar_item_fila_contingencia(db: Session, invoice_id: int) -> Dict[str, Any]:
        """Cancela e remove uma DPS ainda pendente da fila de contingência, sincronizando itens de lote."""
        from app.models import BatchImport, BatchImportItem
        from app.services.batch_emission.validator import recompute_batch_counters

        inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Nota pendente não encontrada na fila.")
        if (inv.status or "") not in {"dps_gerada", "fila_contingencia", "rejeitada"}:
            raise HTTPException(
                status_code=409,
                detail="Esta nota já foi autorizada/processada; utilize o cancelamento fiscal (e101101).",
            )

        linked_items = db.query(BatchImportItem).filter(BatchImportItem.invoice_id == invoice_id).all()
        affected_batch_ids = set()
        for item in linked_items:
            affected_batch_ids.add(item.batch_id)
            item.invoice_id = None
            item.status = "CANCELLED"
            item.last_error = "Cancelada e removida da fila de contingência."
            db.add(item)

        db.flush()
        for b_id in affected_batch_ids:
            b_obj = db.query(BatchImport).filter(BatchImport.id == b_id).first()
            if b_obj:
                recompute_batch_counters(db, b_obj)

        db.delete(inv)
        db.commit()
        return {
            "deleted_invoice_id": invoice_id,
            "updated_batches": sorted(affected_batch_ids),
        }

    @classmethod
    async def reenviar_fila_contingencia(cls, db: Session, req: ReenviarFilaRequest) -> Dict[str, Any]:
        query = db.query(Invoice).filter(Invoice.status.in_(["dps_gerada", "fila_contingencia"]))
        if req.client_id is not None:
            query = query.filter(Invoice.client_id == req.client_id)
        if req.invoice_ids:
            query = query.filter(Invoice.id.in_(req.invoice_ids))

        pendentes = query.order_by(Invoice.id.asc()).all()
        processadas = []
        autorizadas = 0
        falhas = 0

        for inv in pendentes:
            resolved_dps = resolve_storage_path(inv.xml_dps_path, kind="downloads") if inv.xml_dps_path else None
            if not resolved_dps or not resolved_dps.exists():
                inv.ultimo_erro_envio = "Arquivo XML da DPS não encontrado no disco."
                falhas += 1
                processadas.append({"invoice_id": inv.id, "sucesso": False, "erro": inv.ultimo_erro_envio})
                continue

            client_db, _, signer, ambiente = cls._resolver_prestador_e_certificado(
                db=db,
                client_id=inv.client_id,
                prestador_payload=None,
                cert_b64=None,
                cert_password=None,
                ambiente_req="",
            )
            if signer is None:
                inv.ultimo_erro_envio = "Prestador não possui Certificado A1 configurado para reenvio."
                falhas += 1
                processadas.append({"invoice_id": inv.id, "sucesso": False, "erro": inv.ultimo_erro_envio})
                continue

            xml_content = resolved_dps.read_text(encoding="utf-8")
            if "<Signature" not in xml_content:
                xml_content = signer.sign_xml(xml_content, tag_to_sign="infDPS")
                resolved_dps.write_text(xml_content, encoding="utf-8")

            inv.tentativas_envio = (inv.tentativas_envio or 0) + 1
            try:
                adn_client = AdnNfseClient(
                    ambiente=ambiente,
                    cert_pem=signer.get_pem_certificate(),
                    key_pem=signer.get_pem_private_key(),
                )
                res = await adn_client.emitir_dps(xml_content)
                if res.get("sucesso"):
                    nova_chave = res.get("chave_acesso") or inv.chave
                    inv.chave = nova_chave
                    inv.status = "gerada"
                    inv.ultimo_erro_envio = None
                    if res.get("nfse_xml"):
                        inv.xml_path = cls._salvar_xml_disco(res["nfse_xml"], "nfse", f"{nova_chave}.xml")
                    pdf_path = cls._gerar_pdf_danfse(inv.xml_path or inv.xml_dps_path, nova_chave, status="NORMAL")
                    if pdf_path:
                        inv.pdf_path = pdf_path
                    autorizadas += 1
                    processadas.append({"invoice_id": inv.id, "sucesso": True, "chave_acesso": nova_chave})
                else:
                    inv.status = "fila_contingencia"
                    inv.ultimo_erro_envio = str(res.get("mensagem") or res.get("erro") or "Falha no reenvio ADN")
                    falhas += 1
                    processadas.append({"invoice_id": inv.id, "sucesso": False, "erro": inv.ultimo_erro_envio})
            except Exception as exc:
                inv.status = "fila_contingencia"
                inv.ultimo_erro_envio = f"Erro de conexão no reenvio: {exc}"
                falhas += 1
                processadas.append({"invoice_id": inv.id, "sucesso": False, "erro": inv.ultimo_erro_envio})

            db.add(inv)

        db.commit()
        return {
            "total_processadas": len(pendentes),
            "autorizadas": autorizadas,
            "falhas": falhas,
            "resultados": processadas,
        }

    @classmethod
    def enviar_email_nfse(cls, db: Session, invoice_id: int, req: EnviarEmailNfseRequest) -> Dict[str, Any]:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Nota fiscal não encontrada.")
        if not invoice.client_id:
            raise HTTPException(status_code=400, detail="Nota fiscal não está vinculada a um Prestador cadastrado.")

        client_db = db.query(Client).filter(Client.id == invoice.client_id).first()
        if not client_db:
            raise HTTPException(status_code=404, detail="Prestador não encontrado.")

        from app.api.routers.downloads import ensure_invoice_files

        ensure_invoice_files(db, invoice, client_db)

        resolved_pdf = resolve_storage_path(invoice.pdf_path, kind="downloads") if invoice.pdf_path else None
        if not resolved_pdf or not resolved_pdf.exists():
            xml_cand = invoice.xml_path or invoice.xml_dps_path
            resolved_xml = resolve_storage_path(xml_cand, kind="downloads") if xml_cand else None
            if resolved_xml and resolved_xml.exists():
                pdf_gerado = cls._gerar_pdf_danfse(
                    str(resolved_xml), invoice.chave or str(invoice.id), status=invoice.status or "NORMAL"
                )
                if pdf_gerado:
                    invoice.pdf_path = pdf_gerado
                    db.add(invoice)
                    db.commit()

        return EmailService.enviar_nfse_por_email(
            client_db=client_db,
            invoice=invoice,
            destinatario=req.destinatario,
            assunto=req.assunto,
            mensagem=req.mensagem,
        )

    @classmethod
    async def sincronizar_cofre_adn(cls, db: Session, req: SincronizarCofreAdnRequest) -> Dict[str, Any]:
        client_db, _, signer, ambiente = cls._resolver_prestador_e_certificado(
            db=db,
            client_id=req.client_id,
            prestador_payload=None,
            cert_b64=None,
            cert_password=None,
            ambiente_req="",
        )
        if not client_db:
            raise HTTPException(status_code=404, detail="Cliente não encontrado.")
        if signer is None:
            raise HTTPException(
                status_code=400,
                detail=f"O cliente '{client_db.razao_social}' precisa ter um Certificado A1 (.pfx) configurado para sincronizar o Cofre ADN.",
            )

        adn_client = AdnNfseClient(
            ambiente=ambiente,
            cert_pem=signer.get_pem_certificate(),
            key_pem=signer.get_pem_private_key(),
        )

        nsu_atual = req.ultimo_nsu if req.ultimo_nsu is not None else int(client_db.ultimo_nsu_adn or 0)
        maior_nsu = nsu_atual
        novas_notas = 0
        atualizadas = 0
        documentos_lidos = 0
        cnpj_cliente_limpo = clean_digits(client_db.cnpj)

        from pynfse.xml_parser import extrair_dados_nfse

        for _ in range(req.max_paginas):
            res = await adn_client.listar_dfe_adn(ultimo_nsu=maior_nsu)
            if not res.get("sucesso"):
                break

            dados = res.get("dados") or {}
            lote = dados.get("LoteDFe") or dados.get("loteDFe") or dados.get("documentos") or []
            if not lote:
                break

            for item in lote:
                documentos_lidos += 1
                nsu_item = int(item.get("NSU") or item.get("nsu") or maior_nsu)
                if nsu_item > maior_nsu:
                    maior_nsu = nsu_item

                xml_descompactado = item.get("xml_descompactado")
                chave = clean_digits(item.get("ChaveAcesso") or item.get("chaveAcesso") or "")
                if not xml_descompactado:
                    continue

                if not chave:
                    m_ch = re.search(r'Id="NFS(\d{50})"', xml_descompactado)
                    if m_ch:
                        chave = m_ch.group(1)
                    else:
                        chave = f"ADN{client_db.id}{nsu_item}".ljust(50, "0")[:50]

                xml_saved_path = cls._salvar_xml_disco(xml_descompactado, "cofre", f"{chave}.xml")
                resolved_saved_xml = resolve_storage_path(xml_saved_path, kind="downloads")
                try:
                    info_xml = extrair_dados_nfse(str(resolved_saved_xml or xml_saved_path))
                except Exception:
                    info_xml = {}

                # Identifica se a nota é emitida ou recebida pelo CNPJ do prestador no XML
                m_prest = re.search(r"<emit>.*?<CNPJ>(\d{14})</CNPJ>.*?</emit>", xml_descompactado, re.DOTALL)
                if not m_prest:
                    m_prest = re.search(r"<prest>.*?<CNPJ>(\d{14})</CNPJ>.*?</prest>", xml_descompactado, re.DOTALL)
                cnpj_emitente = m_prest.group(1) if m_prest else cnpj_cliente_limpo
                tipo_nota = "emitidas" if cnpj_emitente == cnpj_cliente_limpo else "recebidas"

                valor_nota = float(info_xml.get("valor") or 0.0)
                if valor_nota == 0.0:
                    m_val = re.search(r"<vServ>([0-9.]+)</vServ>", xml_descompactado)
                    if m_val:
                        valor_nota = float(m_val.group(1))

                numero_nota = str(info_xml.get("numero") or nsu_item)
                pdf_saved = cls._gerar_pdf_danfse(xml_saved_path, chave, status="NORMAL")

                existing = db.query(Invoice).filter(Invoice.chave == chave).first()
                if not existing:
                    nova = Invoice(
                        client_id=client_db.id,
                        numero=numero_nota,
                        chave=chave,
                        status="gerada",
                        tipo=tipo_nota,
                        valor=valor_nota,
                        data_emissao=info_xml.get("data_emissao") or datetime.datetime.now(datetime.UTC),
                        xml_path=xml_saved_path,
                        pdf_path=pdf_saved,
                    )
                    db.add(nova)
                    novas_notas += 1
                else:
                    existing.xml_path = xml_saved_path
                    if pdf_saved:
                        existing.pdf_path = pdf_saved
                    if valor_nota > 0:
                        existing.valor = valor_nota
                    db.add(existing)
                    atualizadas += 1

            if len(lote) < 50:
                break

        if maior_nsu > 0:
            dialect = db.bind.dialect.name if db.bind is not None else ""
            if dialect == "postgresql":
                locked_client = db.query(Client).filter(Client.id == client_db.id).with_for_update().first()
                if locked_client and maior_nsu > (locked_client.ultimo_nsu_adn or 0):
                    locked_client.ultimo_nsu_adn = maior_nsu
                    db.add(locked_client)
            else:
                db.execute(
                    update(Client)
                    .where(
                        Client.id == client_db.id,
                        or_(Client.ultimo_nsu_adn.is_(None), Client.ultimo_nsu_adn < maior_nsu),
                    )
                    .values(ultimo_nsu_adn=maior_nsu)
                )

        db.commit()
        return {
            "sucesso": True,
            "client_id": client_db.id,
            "nsu_anterior": nsu_atual,
            "ultimo_nsu": maior_nsu,
            "documentos_lidos": documentos_lidos,
            "novas_notas": novas_notas,
            "notas_atualizadas": atualizadas,
        }

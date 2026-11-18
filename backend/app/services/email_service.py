"""Serviço de envio de NFS-e (XML + DANFSe em PDF) por e-mail via SMTP configurado por Prestador."""

from __future__ import annotations

from email.message import EmailMessage
import html
import os
from pathlib import Path
import smtplib
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.core.config import load_dotenv_if_present
from app.models import Client, Invoice


class EmailService:
    """Envia o XML e o DANFSe (PDF) da NFS-e para o tomador utilizando o SMTP do Prestador ou o fallback global."""

    @staticmethod
    def obter_defaults_env() -> Dict[str, Any]:
        """Lê as variáveis DEFAULT_SMTP_* / SMTP_* do ambiente sem expor a senha em texto claro."""
        load_dotenv_if_present()
        env_host = (os.getenv("DEFAULT_SMTP_HOST") or os.getenv("SMTP_HOST") or "").strip()
        env_user = (os.getenv("DEFAULT_SMTP_USER") or os.getenv("SMTP_USER") or "").strip()
        env_pass = os.getenv("DEFAULT_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD") or ""
        port_raw = (os.getenv("DEFAULT_SMTP_PORT") or os.getenv("SMTP_PORT") or "587").strip()
        try:
            env_port = int(port_raw) if port_raw else 587
        except ValueError:
            env_port = 587
        env_from = (os.getenv("DEFAULT_SMTP_FROM") or os.getenv("SMTP_FROM") or env_user).strip()
        env_tls_raw = (os.getenv("DEFAULT_SMTP_TLS") or os.getenv("SMTP_TLS") or "1").strip().lower()
        env_tls = env_tls_raw not in ("0", "false", "no")
        has_any = bool(env_host or env_user or env_from)
        return {
            "configured": bool(env_host and env_user and env_pass),
            "has_env_values": has_any,
            "smtp_host": env_host,
            "smtp_port": env_port,
            "smtp_user": env_user,
            "smtp_from": env_from,
            "smtp_tls": 1 if env_tls else 0,
            "has_password": bool(env_pass),
        }

    @staticmethod
    def obter_env_smtp_password() -> str:
        """Retorna a senha SMTP padrão configurada no ambiente (uso exclusivo interno no backend)."""
        load_dotenv_if_present()
        return os.getenv("DEFAULT_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD") or ""

    @staticmethod
    def obter_config_smtp(client_db: Optional[Client]) -> Optional[Dict[str, Any]]:
        """Resolve as credenciais SMTP priorizando as do Prestador e usando variáveis de ambiente como fallback."""
        if client_db and client_db.smtp_host and client_db.smtp_user and client_db.smtp_password:
            return {
                "origem": "cliente",
                "host": client_db.smtp_host.strip(),
                "port": int(client_db.smtp_port or 587),
                "user": client_db.smtp_user.strip(),
                "password": client_db.smtp_password,
                "from_addr": (client_db.smtp_from or client_db.smtp_user).strip(),
                "tls": bool(client_db.smtp_tls if client_db.smtp_tls is not None else 1),
            }

        defaults = EmailService.obter_defaults_env()
        env_pass = EmailService.obter_env_smtp_password()
        if defaults["smtp_host"] and defaults["smtp_user"] and env_pass:
            return {
                "origem": "sistema",
                "host": defaults["smtp_host"],
                "port": defaults["smtp_port"],
                "user": defaults["smtp_user"],
                "password": env_pass,
                "from_addr": defaults["smtp_from"] or defaults["smtp_user"],
                "tls": bool(defaults["smtp_tls"]),
            }

        return None

    @staticmethod
    def montar_html_resumo(client_db: Client, invoice: Invoice, mensagem_extra: Optional[str] = None) -> str:
        valor_bruto = f"R$ {(invoice.valor or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        valor_liq = (
            f"R$ {(invoice.valor_liquido or invoice.valor or 0.0):,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
        iss = f"R$ {(invoice.valor_iss or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        ibs = f"R$ {(invoice.valor_ibs or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        cbs = f"R$ {(invoice.valor_cbs or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        bloco_msg = f"<p style='margin: 12px 0; color: #334155;'>{mensagem_extra}</p>" if mensagem_extra else ""

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
            <div style="background: #0f172a; color: #ffffff; padding: 20px 24px;">
                <h2 style="margin: 0; font-size: 18px;">Nota Fiscal de Serviço Eletrônica (NFS-e Nacional)</h2>
                <p style="margin: 4px 0 0; font-size: 13px; color: #94a3b8;">{client_db.razao_social} — CNPJ: {client_db.cnpj}</p>
            </div>
            <div style="padding: 24px; background: #ffffff; color: #1e293b;">
                <p style="margin-top: 0;">Olá, <strong>{invoice.tomador_nome or "Cliente"}</strong>,</p>
                <p>Seguem em anexo o arquivo <strong>XML</strong> e o <strong>DANFSe (PDF)</strong> referentes à Nota Fiscal de Serviço Eletrônica emitida.</p>
                {bloco_msg}
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px;">
                    <tr style="background: #f8fafc;">
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>Número / DPS</strong></td>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">{invoice.numero or "-"} (Série {invoice.serie_dps or "900"})</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>Chave de Acesso</strong></td>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0; font-family: monospace; word-break: break-all;">{invoice.chave or "-"}</td>
                    </tr>
                    <tr style="background: #f8fafc;">
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>Valor dos Serviços</strong></td>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">{valor_bruto}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>Tributos (ISS / IBS / CBS)</strong></td>
                        <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">ISS: {iss} | IBS: {ibs} | CBS: {cbs}</td>
                    </tr>
                    <tr style="background: #f0fdf4;">
                        <td style="padding: 8px 12px; border: 1px solid #bbf7d0;"><strong>Valor Líquido</strong></td>
                        <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold; color: #166534;">{valor_liq}</td>
                    </tr>
                </table>
                <p style="font-size: 12px; color: #64748b; margin-bottom: 0;">Este é um e-mail automático gerado pelo NFSe Manager Pro.</p>
            </div>
        </div>
        """

    @classmethod
    def enviar_nfse_por_email(
        cls,
        client_db: Client,
        invoice: Invoice,
        destinatario: Optional[str] = None,
        assunto: Optional[str] = None,
        mensagem: Optional[str] = None,
    ) -> Dict[str, Any]:
        email_to = (destinatario or invoice.tomador_email or "").strip()
        if not email_to:
            raise HTTPException(
                status_code=400,
                detail="Nenhum e-mail de destinatário informado e a nota não possui e-mail do tomador salvo.",
            )

        smtp_cfg = cls.obter_config_smtp(client_db)
        if not smtp_cfg:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"O prestador '{client_db.razao_social}' não possui servidor SMTP configurado "
                    "e nenhum SMTP padrão do sistema (DEFAULT_SMTP_HOST) foi definido."
                ),
            )

        msg = EmailMessage()
        msg["Subject"] = assunto or f"NFS-e #{invoice.numero} - {client_db.razao_social}"
        nome_remetente = (client_db.razao_social or "NFSe Manager").replace('"', "")
        msg["From"] = f'"{nome_remetente}" <{smtp_cfg["from_addr"]}>'
        msg["To"] = email_to
        if client_db.email:
            msg["Reply-To"] = client_db.email.strip()

        corpo_html = cls.montar_html_resumo(client_db, invoice, mensagem_extra=mensagem)
        msg.set_content(
            f"Segue em anexo a NFS-e #{invoice.numero} (Chave: {invoice.chave}) emitida por {client_db.razao_social}."
        )
        msg.add_alternative(corpo_html, subtype="html")

        from app.api.routers.downloads import _resolve_existing_path

        anexos_incluidos = []
        xml_candidate = invoice.xml_path or invoice.xml_dps_path
        xml_resolved = _resolve_existing_path(xml_candidate) if xml_candidate else None
        if not xml_resolved and xml_candidate and Path(xml_candidate).exists():
            xml_resolved = xml_candidate
        if xml_resolved and Path(xml_resolved).exists():
            xml_bytes = Path(xml_resolved).read_bytes()
            msg.add_attachment(
                xml_bytes,
                maintype="application",
                subtype="xml",
                filename=f"NFSe_{invoice.numero or invoice.chave}.xml",
            )
            anexos_incluidos.append("xml")

        pdf_resolved = _resolve_existing_path(invoice.pdf_path) if invoice.pdf_path else None
        if not pdf_resolved and invoice.pdf_path and Path(invoice.pdf_path).exists():
            pdf_resolved = invoice.pdf_path
        if pdf_resolved and pdf_resolved.lower().endswith(".pdf") and Path(pdf_resolved).exists():
            pdf_bytes = Path(pdf_resolved).read_bytes()
            msg.add_attachment(
                pdf_bytes,
                maintype="application",
                subtype="pdf",
                filename=f"DANFSe_{invoice.numero or invoice.chave}.pdf",
            )
            anexos_incluidos.append("pdf")

        if not anexos_incluidos:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Não foi possível localizar ou baixar o XML e o DANFSe (PDF) desta nota fiscal para anexar ao e-mail. "
                    "Tente baixar os arquivos na tela de Notas Fiscais antes de reenviar."
                ),
            )

        cls._dispatch_smtp(smtp_cfg, msg)

        return {
            "sucesso": True,
            "origem_smtp": smtp_cfg["origem"],
            "remetente": msg["From"],
            "reply_to": msg.get("Reply-To"),
            "destinatario": email_to,
            "assunto": msg["Subject"],
            "anexos": anexos_incluidos,
            "invoice_id": invoice.id,
        }

    @staticmethod
    def _dispatch_smtp(smtp_cfg: Dict[str, Any], msg: EmailMessage) -> None:
        """Executa o envio SMTP com suporte a SSL (porta 465) ou STARTTLS."""
        port = int(smtp_cfg["port"])
        use_tls = bool(smtp_cfg["tls"])

        try:
            if port == 465:
                with smtplib.SMTP_SSL(smtp_cfg["host"], port, timeout=15) as server:
                    server.login(smtp_cfg["user"], smtp_cfg["password"])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(smtp_cfg["host"], port, timeout=15) as server:
                    if use_tls:
                        server.starttls()
                    server.login(smtp_cfg["user"], smtp_cfg["password"])
                    server.send_message(msg)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao enviar e-mail via SMTP: {exc}") from exc

    @classmethod
    def enviar_mensagem_suporte(
        cls,
        destinatario: str,
        remetente_email: str,
        whatsapp: Optional[str],
        mensagem: str,
        operador: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Envia mensagem de suporte/feedback via SMTP padrão do sistema."""
        smtp_cfg = cls.obter_config_smtp(None)
        if not smtp_cfg:
            raise RuntimeError("SMTP padrão do sistema não configurado (DEFAULT_SMTP_HOST/USER/PASSWORD).")

        msg = EmailMessage()
        msg["Subject"] = f"[NFSe Manager Pro] Suporte / Feedback - {remetente_email}"
        msg["From"] = f'"NFSe Manager Pro Suporte" <{smtp_cfg["from_addr"]}>'
        msg["To"] = destinatario
        if remetente_email:
            msg["Reply-To"] = remetente_email.strip()

        wpp_txt = whatsapp or "-"
        op_txt = operador or "-"
        msg.set_content(
            "Nova mensagem de suporte/feedback recebida no NFSe Manager Pro:\n\n"
            f"Operador: {op_txt}\n"
            f"E-mail: {remetente_email}\n"
            f"WhatsApp: {wpp_txt}\n\n"
            f"Mensagem:\n{mensagem}\n"
        )
        msg.add_alternative(
            f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
              <div style="background: #0f172a; color: #fff; padding: 16px 20px;">
                <h2 style="margin: 0; font-size: 17px;">Suporte &amp; Feedback — NFSe Manager Pro</h2>
              </div>
              <div style="padding: 20px; background: #fff; color: #1e293b; font-size: 14px;">
                <p><strong>Operador:</strong> {html.escape(op_txt)}</p>
                <p><strong>E-mail:</strong> {html.escape(remetente_email)}</p>
                <p><strong>WhatsApp:</strong> {html.escape(wpp_txt)}</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 16px 0;" />
                <p style="margin-bottom: 6px;"><strong>Mensagem:</strong></p>
                <div style="background: #f8fafc; padding: 12px 14px; border-radius: 8px; white-space: pre-wrap;">{html.escape(mensagem)}</div>
              </div>
            </div>
            """,
            subtype="html",
        )

        cls._dispatch_smtp(smtp_cfg, msg)
        return {"destinatario": destinatario, "origem_smtp": smtp_cfg["origem"]}

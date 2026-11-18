"""
Módulo de injeções de dependência (Dependencies) e utilitários da API.
Contém funções auxiliares utilizadas nas rotas, como a obtenção da sessão do banco de dados
e a instância do cliente NFSe (robô).
"""

from typing import Optional
from app.core.config import get_downloads_dir, resolve_storage_path
from app.models import Client
from pynfse.cliente_nfse import ClienteNfseNacional

DOWNLOADS_DIR = get_downloads_dir()


class ClienteNfsePortalWrapper(ClienteNfseNacional):
    """
    Extensão do ClienteNfseNacional que evita requisições diretas de download
    de XML/PDF (que retornam 403 Forbidden no portal) quando autenticado via
    usuário e senha sem certificado digital, indo direto ao HTML de impressão.
    """

    def usa_apenas_credenciais(self) -> bool:
        """Retorna True se o cliente usa usuário/senha e não possui certificado digital ativo."""
        tem_certificado = bool(self.caminho_pfx and self.senha_pfx and getattr(self, "_usando_certificado", True))
        return not tem_certificado and bool(self.usuario and self.senha)

    def autenticar(self, usar_certificado: bool = True) -> bool:
        self._usando_certificado = bool(usar_certificado and self.caminho_pfx and self.senha_pfx)
        return super().autenticar(usar_certificado=usar_certificado)

    def baixar_via_impressao_html(self, url_ou_chave: str, status: str = "gerada", data_emissao=None):
        from app.services.html_xml_service import obter_html_e_gerar_xml_pdf

        return obter_html_e_gerar_xml_pdf(self, url_ou_chave, status, data_emissao)

    def baixar_xml(self, url: str, status: str, data_emissao=None) -> str:
        if self.usa_apenas_credenciais():
            res = self.baixar_via_impressao_html(url, status, data_emissao)
            return res.get("xml_path") or ""
        return super().baixar_xml(url, status, data_emissao)

    def baixar_pdf(self, url: str, status: str, data_emissao=None) -> str:
        if self.usa_apenas_credenciais():
            res = self.baixar_via_impressao_html(url, status, data_emissao)
            return res.get("pdf_path") or res.get("html_path") or ""
        return super().baixar_pdf(url, status, data_emissao)


def has_valid_certificate(client_db: Optional[Client]) -> bool:
    """Verifica se o cliente possui certificado digital configurado e existente no disco."""
    if not client_db:
        return False
    cert_path = (client_db.cert_path or "").strip()
    cert_password = (client_db.cert_password or "").strip()
    if not cert_path or not cert_password:
        return False
    resolved = resolve_storage_path(cert_path, kind="certs")
    return bool(resolved and resolved.exists() and resolved.is_file())


def get_nfse_client(client_db: Client) -> ClienteNfseNacional:
    """
    Constrói e retorna uma instância do ClienteNfseNacional (Robô)
    com base nas credenciais e configurações salvas no banco de dados.
    """
    raw_cert_path = (client_db.cert_path or "").strip() or None
    cert_password = (client_db.cert_password or "").strip() or None
    resolved_cert = resolve_storage_path(raw_cert_path, kind="certs") if raw_cert_path else None
    cert_path = str(resolved_cert) if (resolved_cert and cert_password and resolved_cert.exists()) else None
    if not cert_path:
        cert_password = None

    resolved_save = resolve_storage_path(client_db.save_path, kind="downloads") if client_db.save_path else None
    save_path_str = str(resolved_save) if resolved_save else str(get_downloads_dir())

    return ClienteNfsePortalWrapper(
        usuario=client_db.username or client_db.cnpj,
        senha=client_db.password,
        caminho_pfx=cert_path,
        senha_pfx=cert_password,
        save_path=save_path_str,
        path_structure=client_db.path_structure,
        razao_social=client_db.razao_social,
    )

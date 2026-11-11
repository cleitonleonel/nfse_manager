"""
Módulo de injeções de dependência (Dependencies) e utilitários da API.
Contém funções auxiliares utilizadas nas rotas, como a obtenção da sessão do banco de dados
e a instância do cliente NFSe (robô).
"""

from pathlib import Path
from typing import Optional
from app.models import Client
from pynfse.cliente_nfse import ClienteNfseNacional

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOWNLOADS_DIR = BACKEND_DIR / "downloads"


class ClienteNfsePortalWrapper(ClienteNfseNacional):
    """
    Extensão do ClienteNfseNacional que evita requisições diretas de download
    de XML/PDF (que retornam 403 Forbidden no portal) quando autenticado via
    usuário e senha sem certificado digital, indo direto ao HTML de impressão.
    """

    def usa_apenas_credenciais(self) -> bool:
        """Retorna True se o cliente usa usuário/senha e não possui certificado digital ativo."""
        tem_certificado = bool(
            self.caminho_pfx
            and self.senha_pfx
            and getattr(self, "_usando_certificado", True)
        )
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
    p = Path(cert_path)
    if p.exists() and p.is_file():
        return True
    alt_cert = BACKEND_DIR / cert_path
    if not p.is_absolute() and alt_cert.exists() and alt_cert.is_file():
        return True
    return False


def get_nfse_client(client_db: Client) -> ClienteNfseNacional:
    """
    Constrói e retorna uma instância do ClienteNfseNacional (Robô)
    com base nas credenciais e configurações salvas no banco de dados.
    """
    cert_path = (client_db.cert_path or "").strip() or None
    cert_password = (client_db.cert_password or "").strip() or None
    if cert_path and not Path(cert_path).exists() and not Path(cert_path).is_absolute():
        alt_cert = BACKEND_DIR / cert_path
        if alt_cert.exists():
            cert_path = str(alt_cert)

    if not cert_path or not cert_password or not Path(cert_path).exists():
        cert_path = None
        cert_password = None

    return ClienteNfsePortalWrapper(
        usuario=client_db.username or client_db.cnpj,
        senha=client_db.password,
        caminho_pfx=cert_path,
        senha_pfx=cert_password,
        save_path=client_db.save_path or str(DOWNLOADS_DIR),
        path_structure=client_db.path_structure,
        razao_social=client_db.razao_social,
    )

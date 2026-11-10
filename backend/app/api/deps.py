"""
Módulo de injeções de dependência (Dependencies) e utilitários da API.
Contém funções auxiliares utilizadas nas rotas, como a obtenção da sessão do banco de dados
e a instância do cliente NFSe (robô).
"""

from pathlib import Path
from app.models import Client
from pynfse.cliente_nfse import ClienteNfseNacional

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOWNLOADS_DIR = BACKEND_DIR / "downloads"


def get_nfse_client(client_db: Client) -> ClienteNfseNacional:
    """
    Constrói e retorna uma instância do ClienteNfseNacional (Robô)
    com base nas credenciais e configurações salvas no banco de dados.
    """
    cert_path = client_db.cert_path
    if cert_path and not Path(cert_path).exists() and not Path(cert_path).is_absolute():
        alt_cert = BACKEND_DIR / cert_path
        if alt_cert.exists():
            cert_path = str(alt_cert)

    return ClienteNfseNacional(
        usuario=client_db.username or client_db.cnpj,
        senha=client_db.password,
        caminho_pfx=cert_path,
        senha_pfx=client_db.cert_password,
        save_path=client_db.save_path or str(DOWNLOADS_DIR),
        path_structure=client_db.path_structure,
        razao_social=client_db.razao_social,
    )

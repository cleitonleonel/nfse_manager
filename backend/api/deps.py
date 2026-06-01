"""
Módulo de injeções de dependência (Dependencies) e utilitários da API.
Contém funções auxiliares utilizadas nas rotas, como a obtenção da sessão do banco de dados
e a instância do cliente NFSe (robô).
"""

from backend.models import Client
from core.cliente_nfse import ClienteNfseNacional


def get_nfse_client(client_db: Client) -> ClienteNfseNacional:
    """
    Constrói e retorna uma instância do ClienteNfseNacional (Robô)
    com base nas credenciais e configurações salvas no banco de dados.
    """
    return ClienteNfseNacional(
        usuario=client_db.username,
        senha=client_db.password,
        caminho_pfx=client_db.cert_path,
        senha_pfx=client_db.cert_password,
        save_path=client_db.save_path,
        path_structure=client_db.path_structure,
        razao_social=client_db.razao_social,
    )

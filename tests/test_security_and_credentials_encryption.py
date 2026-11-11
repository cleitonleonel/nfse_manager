"""Testes de segurança: criptografia em repouso de senhas e credenciais dos clientes."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import decrypt_secret, encrypt_secret, is_encrypted
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Client, init_db


def setup_function():
    Base.metadata.create_all(bind=engine)


def test_funcoes_encrypt_e_decrypt_secret():
    senha_original = "Senha@Forte#2026!"

    # 1. Criptografia
    cifrado = encrypt_secret(senha_original)
    assert cifrado is not None
    assert is_encrypted(cifrado)
    assert cifrado.startswith("enc:")
    assert senha_original not in cifrado  # A senha não pode estar em texto puro

    # 2. Decifragem
    decifrado = decrypt_secret(cifrado)
    assert decifrado == senha_original

    # 3. Idempotência (não criptografar duas vezes)
    assert encrypt_secret(cifrado) == cifrado

    # 4. Compatibilidade com dados legados em texto plano
    assert decrypt_secret("senha_legada_sem_criptografia") == "senha_legada_sem_criptografia"
    assert decrypt_secret("") == ""
    assert decrypt_secret(None) is None


def test_senhas_sao_gravadas_criptografadas_no_banco_de_dados():
    client = TestClient(app)
    cnpj = "33.444.555/0001-66"
    senha_portal = "SegredoPortalNfse999"
    senha_cert = "SegredoCertPfx888"

    # Criar cliente via endpoint
    res = client.post(
        "/api/clients",
        data={
            "cnpj": cnpj,
            "razao_social": "Empresa Segura Criptografia",
            "username": "usuario_portal",
            "password": senha_portal,
            "cert_password": senha_cert,
        },
    )
    assert res.status_code == 200, res.text
    client_id = res.json()["id"]

    db = SessionLocal()
    try:
        # 1. Leitura via SQL Bruto (como um invasor que acessa o banco veria):
        row = db.execute(
            text("SELECT password, cert_password FROM clients WHERE id = :id"),
            {"id": client_id},
        ).fetchone()

        db_raw_password = row[0]
        db_raw_cert_password = row[1]

        # Garantir que no banco de dados está salvo o ciphertext e NÃO a senha em texto puro!
        assert is_encrypted(db_raw_password), "A senha do portal deve estar salva criptografada no banco."
        assert is_encrypted(db_raw_cert_password), "A senha do certificado deve estar salva criptografada no banco."
        assert senha_portal not in db_raw_password
        assert senha_cert not in db_raw_cert_password

        # 2. Leitura transparente pelo ORM (como a aplicação consome em memória):
        cli_orm = db.query(Client).filter(Client.id == client_id).first()
        assert cli_orm is not None
        assert cli_orm.password == senha_portal
        assert cli_orm.cert_password == senha_cert

    finally:
        db.query(Client).filter(Client.id == client_id).delete()
        db.commit()
        db.close()


def test_migracao_automatica_de_senhas_legadas_em_init_db():
    db = SessionLocal()
    cnpj_legado = "77.888.999/0001-00"
    senha_legada = "senha_em_texto_puro_antiga"

    try:
        # Inserir propositalmente registro legado direto no SQL em texto plano (simulando banco antigo)
        db.execute(
            text(
                "INSERT INTO clients (cnpj, razao_social, username, password, cert_password) "
                "VALUES (:cnpj, :razao, :user, :pwd, :cpwd)"
            ),
            {
                "cnpj": cnpj_legado,
                "razao": "Cliente Legado Para Migracao",
                "user": "user_legado",
                "pwd": senha_legada,
                "cpwd": senha_legada,
            },
        )
        db.commit()

        # Executar a rotina de inicialização e migração
        init_db()

        # Verificar se agora está criptografado no banco
        row = db.execute(
            text("SELECT password, cert_password FROM clients WHERE cnpj = :cnpj"),
            {"cnpj": cnpj_legado},
        ).fetchone()

        assert is_encrypted(row[0]), "A senha legada deveria ter sido criptografada após init_db()"
        assert is_encrypted(row[1]), "A senha de certificado legada deveria ter sido criptografada após init_db()"

        # E o ORM deve decifrar corretamente
        cli = db.query(Client).filter(Client.cnpj == cnpj_legado).first()
        assert cli.password == senha_legada
        assert cli.cert_password == senha_legada

    finally:
        db.execute(text("DELETE FROM clients WHERE cnpj = :cnpj"), {"cnpj": cnpj_legado})
        db.commit()
        db.close()

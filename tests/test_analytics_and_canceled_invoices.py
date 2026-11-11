"""Testes para garantir que notas canceladas e substituídas não sejam somadas nos totais financeiros e saldo."""

import datetime
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Client, Invoice


def setup_function():
    Base.metadata.create_all(bind=engine)


def test_notas_canceladas_e_substituidas_nao_entram_no_faturamento_e_saldo():
    client = TestClient(app)
    db = SessionLocal()

    try:
        # 1. Criar um cliente específico para o teste
        cli = Client(
            cnpj="11.222.333/0001-44",
            razao_social="Empresa Teste Canceladas e Substituidas",
        )
        db.add(cli)
        db.commit()
        db.refresh(cli)
        client_id = cli.id

        now = datetime.datetime.now(datetime.UTC)

        # 2. Inserir notas:
        # - Nota 1: Válida emitida (R$ 1.000,00) -> deve somar
        # - Nota 2: Cancelada emitida (R$ 500,00) -> NÃO deve somar
        # - Nota 3: Substituída emitida (R$ 800,00) -> NÃO deve somar
        # - Nota 4: Válida recebida (R$ 200,00) -> deve somar nas despesas
        # - Nota 5: Cancelada recebida (R$ 300,00) -> NÃO deve somar nas despesas
        inv1 = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000001",
            numero="1",
            status="gerada",
            tipo="emitidas",
            valor=1000.0,
            data_emissao=now,
        )
        inv2 = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000002",
            numero="2",
            status="cancelada",
            tipo="emitidas",
            valor=500.0,
            data_emissao=now,
        )
        inv3 = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000003",
            numero="3",
            status="substituida",
            tipo="emitidas",
            valor=800.0,
            data_emissao=now,
        )
        inv4 = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000004",
            numero="4",
            status="gerada",
            tipo="recebidas",
            valor=200.0,
            data_emissao=now,
        )
        inv5 = Invoice(
            client_id=client_id,
            chave="32000000000000000000000000000000000000000005",
            numero="5",
            status="CANCELADA",
            tipo="recebidas",
            valor=300.0,
            data_emissao=now,
        )
        db.add_all([inv1, inv2, inv3, inv4, inv5])
        db.commit()

        # 3. Testar endpoint /api/analytics/stats
        res_stats = client.get(f"/api/analytics/stats?client_id={client_id}")
        assert res_stats.status_code == 200
        stats = res_stats.json()

        # Deve somar apenas a Nota 1 (R$ 1.000,00) em emitidas
        assert stats["valor_emitidas"] == 1000.0
        # Deve somar apenas a Nota 4 (R$ 200,00) em recebidas
        assert stats["valor_recebidas"] == 200.0
        # Saldo líquido implícito: 1000 - 200 = 800 (sem os 500 cancelados, 800 substituídos, 300 recebidas canceladas)
        saldo_liquido = stats["valor_emitidas"] - stats["valor_recebidas"]
        assert saldo_liquido == 800.0

        # Contagem de notas ativas/válidas
        assert stats["total_emitidas"] == 1
        assert stats["total_recebidas"] == 1

        # 4. Testar endpoint /api/analytics/chart
        res_chart = client.get(f"/api/analytics/chart?period=7d&client_id={client_id}")
        assert res_chart.status_code == 200
        chart_data = res_chart.json()
        assert len(chart_data["points"]) >= 1
        total_chart_valor = sum(p["valor"] for p in chart_data["points"])
        # O valor no gráfico para esse cliente deve ser 1000.0 (e não 1000 + 500 + 800)
        assert total_chart_valor == 1000.0

        # 5. Testar endpoint /api/reports/export (formato json)
        res_rep = client.get(f"/api/reports/export?format=json&period=7d&client_id={client_id}")
        assert res_rep.status_code == 200
        rep = res_rep.json()
        assert rep["total_emitidas"] == 1000.0
        assert rep["total_recebidas"] == 200.0
        assert rep["saldo_liquido"] == 800.0

        # 6. Testar endpoint /api/analytics/ranking
        res_rank = client.get("/api/analytics/ranking?period=7d")
        assert res_rank.status_code == 200
        rank = res_rank.json()
        cli_rank = next((item for item in rank["top_emitidas"] if item["client_id"] == client_id), None)
        assert cli_rank is not None
        assert cli_rank["valor"] == 1000.0

    finally:
        # Limpar o cliente de teste e notas geradas
        db.query(Invoice).filter(Invoice.client_id == client_id).delete()
        db.query(Client).filter(Client.id == client_id).delete()
        db.commit()
        db.close()

"""Router de Relatórios - Exportação de dados em múltiplos formatos."""

import io
import csv
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import openpyxl
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Note

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/export")
def export_report(
        format: str,
        period: str = "30d",
        client_id: Optional[int] = None,
        db: Session = Depends(get_db)
):
    """Exportar relatório em JSON, CSV ou XLSX."""
    days = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    query = db.query(Note).filter(Note.data_emissao >= date_limit)
    if client_id:
        query = query.filter(Note.client_id == client_id)

    notes = query.order_by(Note.data_emissao.desc()).all()

    total_emitidas = sum(n.valor or 0 for n in notes if n.tipo == "emitidas")
    total_recebidas = sum(n.valor or 0 for n in notes if n.tipo == "recebidas")
    saldo = total_emitidas - total_recebidas

    if format == "json":
        return {
            "period": period,
            "client_id": client_id,
            "total_emitidas": total_emitidas,
            "total_recebidas": total_recebidas,
            "saldo_liquido": saldo,
            "notas": [
                {
                    "id": n.id,
                    "numero": n.numero,
                    "data": n.data_emissao.isoformat() if n.data_emissao else None,
                    "tipo": n.tipo,
                    "valor": n.valor,
                    "status": n.status
                }
                for n in notes
            ]
        }

    elif format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["RESUMO FINANCEIRO"])
        writer.writerow(["Total Receitas (Emitidas)", f"R$ {total_emitidas:.2f}"])
        writer.writerow(["Total Despesas (Recebidas)", f"R$ {total_recebidas:.2f}"])
        writer.writerow(["Saldo Líquido", f"R$ {saldo:.2f}"])
        writer.writerow([])
        writer.writerow(["DETALHAMENTO DE NOTAS"])
        writer.writerow(["ID", "Data", "Número", "Tipo", "Status", "Valor (R$)"])
        for n in notes:
            dt_str = n.data_emissao.strftime("%d/%m/%Y %H:%M") if n.data_emissao else ""
            writer.writerow([n.id, dt_str, n.numero or "", n.tipo, n.status, f"{n.valor or 0:.2f}"])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=relatorio_nfse.csv"}
        )

    elif format == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Relatório NFSe"

        ws.append(["RESUMO FINANCEIRO"])
        ws.append(["Total Receitas (Emitidas)", total_emitidas])
        ws.append(["Total Despesas (Recebidas)", total_recebidas])
        ws.append(["Saldo Líquido", saldo])
        ws.append([])

        ws.append(["DETALHAMENTO DE NOTAS"])
        ws.append(["ID", "Data", "Número", "Tipo", "Status", "Valor"])

        for n in notes:
            dt_str = n.data_emissao.strftime("%d/%m/%Y %H:%M") if n.data_emissao else ""
            ws.append([n.id, dt_str, n.numero or "", n.tipo, n.status, n.valor or 0])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=relatorio_nfse.xlsx"}
        )
    else:
        raise HTTPException(status_code=400, detail="Formato não suportado")

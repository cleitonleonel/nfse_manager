"""Router de Relatórios - Exportação de dados em múltiplos formatos."""

import csv
import datetime
import io
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import openpyxl
from sqlalchemy.orm import Session

from app.constants import DEFAULT_PERIOD, PERIOD_DAYS_MAP
from app.database import get_db
from app.models import Client, Invoice

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/export")
def export_report(
    format: str,
    period: str = DEFAULT_PERIOD,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Exportar relatório em JSON, CSV ou XLSX."""
    days = PERIOD_DAYS_MAP.get(period, 30)
    date_limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    query = db.query(Invoice).filter(Invoice.data_emissao >= date_limit)
    if client_id:
        query = query.filter(Invoice.client_id == client_id)

    invoices = query.order_by(Invoice.data_emissao.desc()).all()

    def nota_valida_para_calculo(n: Invoice) -> bool:
        st = (n.status or "").lower()
        return "cancelad" not in st and "substitu" not in st

    total_emitidas = sum(n.valor or 0 for n in invoices if n.tipo == "emitidas" and nota_valida_para_calculo(n))
    total_recebidas = sum(n.valor or 0 for n in invoices if n.tipo == "recebidas" and nota_valida_para_calculo(n))
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
                    "status": n.status,
                }
                for n in invoices
            ],
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
        for n in invoices:
            dt_str = n.data_emissao.strftime("%d/%m/%Y %H:%M") if n.data_emissao else ""
            writer.writerow([n.id, dt_str, n.numero or "", n.tipo, n.status, f"{n.valor or 0:.2f}"])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=relatorio_nfse.csv"},
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

        for n in invoices:
            dt_str = n.data_emissao.strftime("%d/%m/%Y %H:%M") if n.data_emissao else ""
            ws.append([n.id, dt_str, n.numero or "", n.tipo, n.status, n.valor or 0])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=relatorio_nfse.xlsx"},
        )
    else:
        raise HTTPException(status_code=400, detail="Formato não suportado")


def _nota_competencia(n: Invoice) -> str:
    if n.payload_dps_json:
        try:
            payload = json.loads(n.payload_dps_json)
            dc = str(payload.get("data_competencia") or "").strip()
            if re.match(r"^\d{4}-\d{2}", dc):
                return dc[:7]
            if re.match(r"^\d{2}/\d{2}/\d{4}", dc):
                return f"{dc[6:10]}-{dc[3:5]}"
        except Exception:
            pass
    if n.data_emissao:
        return n.data_emissao.strftime("%Y-%m")
    return ""


@router.get("/competencia")
def export_competencia_report(
    competencia: Optional[str] = Query(None, description="Competência mensal YYYY-MM (padrão: mês atual)"),
    client_id: Optional[int] = Query(None, description="Filtrar por ID do Prestador"),
    format: str = Query("json", description="json, csv ou xlsx"),
    db: Session = Depends(get_db),
):
    """Gera relatório contábil de conferência por competência mensal (emitidas, recebidas, tributos e canceladas)."""
    comp_alvo = (competencia or datetime.datetime.now(datetime.UTC).strftime("%Y-%m")).strip()
    if not re.match(r"^\d{4}-\d{2}$", comp_alvo):
        raise HTTPException(status_code=400, detail="Competência inválida. Informe no formato YYYY-MM (ex: 2026-11).")

    query = db.query(Invoice)
    if client_id is not None:
        query = query.filter(Invoice.client_id == client_id)

    todas = query.order_by(Invoice.data_emissao.asc()).all()
    notas = [n for n in todas if _nota_competencia(n) == comp_alvo]

    clients_map: Dict[int, str] = {
        c.id: c.razao_social or c.cnpj
        for c in db.query(Client).all()
    }

    def is_ativa(n: Invoice) -> bool:
        st = (n.status or "").lower()
        return "cancelad" not in st and "substitu" not in st

    emitidas_ativas = [n for n in notas if n.tipo == "emitidas" and is_ativa(n)]
    recebidas_ativas = [n for n in notas if n.tipo == "recebidas" and is_ativa(n)]
    canceladas = [n for n in notas if not is_ativa(n)]
    pendentes_fila = [n for n in emitidas_ativas if n.status in {"dps_gerada", "fila_contingencia"}]

    total_emitidas_bruto = round(sum(float(n.valor or 0.0) for n in emitidas_ativas), 2)
    total_emitidas_liquido = round(
        sum(float(n.valor_liquido if n.valor_liquido is not None else (n.valor or 0.0)) for n in emitidas_ativas),
        2,
    )
    total_recebidas = round(sum(float(n.valor or 0.0) for n in recebidas_ativas), 2)
    total_iss = round(sum(float(n.valor_iss or 0.0) for n in emitidas_ativas), 2)
    total_ibs = round(sum(float(n.valor_ibs or 0.0) for n in emitidas_ativas), 2)
    total_cbs = round(sum(float(n.valor_cbs or 0.0) for n in emitidas_ativas), 2)

    resumo = {
        "competencia": comp_alvo,
        "client_id": client_id,
        "qtd_total": len(notas),
        "qtd_emitidas_ativas": len(emitidas_ativas),
        "qtd_recebidas_ativas": len(recebidas_ativas),
        "qtd_canceladas_substituidas": len(canceladas),
        "qtd_pendentes_fila": len(pendentes_fila),
        "total_emitidas_bruto": total_emitidas_bruto,
        "total_emitidas_liquido": total_emitidas_liquido,
        "total_recebidas": total_recebidas,
        "saldo_operacional": round(total_emitidas_bruto - total_recebidas, 2),
        "total_iss": total_iss,
        "total_ibs": total_ibs,
        "total_cbs": total_cbs,
    }

    detalhes: List[Dict[str, Any]] = [
        {
            "id": n.id,
            "data_emissao": n.data_emissao.isoformat() if n.data_emissao else None,
            "competencia": comp_alvo,
            "prestador": clients_map.get(n.client_id, "-"),
            "numero": n.numero or "",
            "chave": n.chave or "",
            "tipo": n.tipo,
            "status": n.status,
            "tomador_documento": n.tomador_documento or "",
            "tomador_nome": n.tomador_nome or "",
            "c_trib_nac": n.c_trib_nac or "",
            "c_class_trib": n.c_class_trib or "",
            "valor": round(float(n.valor or 0.0), 2),
            "valor_iss": round(float(n.valor_iss or 0.0), 2),
            "valor_ibs": round(float(n.valor_ibs or 0.0), 2),
            "valor_cbs": round(float(n.valor_cbs or 0.0), 2),
            "valor_liquido": round(float(n.valor_liquido if n.valor_liquido is not None else (n.valor or 0.0)), 2),
        }
        for n in notas
    ]

    fmt = (format or "json").strip().lower()
    if fmt == "json":
        return {"resumo": resumo, "notas": detalhes}

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow([f"RELATÓRIO DE CONFERÊNCIA POR COMPETÊNCIA — {comp_alvo}"])
        writer.writerow(["Emitidas Ativas", resumo["qtd_emitidas_ativas"], f"{total_emitidas_bruto:.2f}"])
        writer.writerow(["Recebidas Ativas", resumo["qtd_recebidas_ativas"], f"{total_recebidas:.2f}"])
        writer.writerow(["Canceladas / Substituídas", resumo["qtd_canceladas_substituidas"], "0.00"])
        writer.writerow(["Total ISSQN (R$)", "", f"{total_iss:.2f}"])
        writer.writerow(["Total IBS (R$)", "", f"{total_ibs:.2f}"])
        writer.writerow(["Total CBS (R$)", "", f"{total_cbs:.2f}"])
        writer.writerow([])
        writer.writerow([
            "ID", "Data", "Prestador", "Número", "Chave", "Tipo", "Status",
            "Tomador CNPJ", "Tomador Nome", "cTribNac", "cClassTrib",
            "Valor Bruto", "ISSQN", "IBS", "CBS", "Valor Líquido",
        ])
        for d in detalhes:
            writer.writerow([
                d["id"], d["data_emissao"] or "", d["prestador"], d["numero"], d["chave"],
                d["tipo"], d["status"], d["tomador_documento"], d["tomador_nome"],
                d["c_trib_nac"], d["c_class_trib"],
                f"{d['valor']:.2f}", f"{d['valor_iss']:.2f}", f"{d['valor_ibs']:.2f}",
                f"{d['valor_cbs']:.2f}", f"{d['valor_liquido']:.2f}",
            ])
        payload = ("\ufeff" + out.getvalue()).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=competencia_{comp_alvo}.csv"},
        )

    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws_res = wb.active
        ws_res.title = "Resumo Competência"
        ws_res.append(["Indicador", "Valor"])
        ws_res.append(["Competência", comp_alvo])
        ws_res.append(["Notas Emitidas Ativas", resumo["qtd_emitidas_ativas"]])
        ws_res.append(["Notas Recebidas Ativas", resumo["qtd_recebidas_ativas"]])
        ws_res.append(["Canceladas / Substituídas", resumo["qtd_canceladas_substituidas"]])
        ws_res.append(["Pendentes na Fila", resumo["qtd_pendentes_fila"]])
        ws_res.append(["Total Bruto Emitidas (R$)", total_emitidas_bruto])
        ws_res.append(["Total Líquido Emitidas (R$)", total_emitidas_liquido])
        ws_res.append(["Total Despesas Recebidas (R$)", total_recebidas])
        ws_res.append(["Total ISSQN (R$)", total_iss])
        ws_res.append(["Total IBS (R$)", total_ibs])
        ws_res.append(["Total CBS (R$)", total_cbs])

        ws_det = wb.create_sheet("Notas da Competência")
        ws_det.append([
            "ID", "Data", "Prestador", "Número", "Chave", "Tipo", "Status",
            "Tomador CNPJ", "Tomador Nome", "cTribNac", "cClassTrib",
            "Valor Bruto", "ISSQN", "IBS", "CBS", "Valor Líquido",
        ])
        for d in detalhes:
            ws_det.append([
                d["id"], d["data_emissao"] or "", d["prestador"], d["numero"], d["chave"],
                d["tipo"], d["status"], d["tomador_documento"], d["tomador_nome"],
                d["c_trib_nac"], d["c_class_trib"],
                d["valor"], d["valor_iss"], d["valor_ibs"], d["valor_cbs"], d["valor_liquido"],
            ])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=competencia_{comp_alvo}.xlsx"},
        )

    raise HTTPException(status_code=400, detail="Formato não suportado. Utilize 'json', 'csv' ou 'xlsx'.")

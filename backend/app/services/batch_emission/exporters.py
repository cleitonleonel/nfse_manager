"""Exportador CSV e XLSX dos resultados de processamento do lote NFS-e."""

from __future__ import annotations

import csv
import io
import json
from typing import List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import openpyxl

from app.models import BatchImport, BatchImportItem


def export_batch_results(batch: BatchImport, items: List[BatchImportItem], fmt: str = "xlsx") -> StreamingResponse:
    """Exporta resumo e detalhamento item a item do lote em CSV ou XLSX."""
    fmt_clean = (fmt or "xlsx").strip().lower()
    if fmt_clean not in {"csv", "xlsx"}:
        raise HTTPException(status_code=400, detail="Formato inválido. Utilize 'csv' ou 'xlsx'.")

    summary_rows = [
        ["Lote ID", batch.id],
        ["Arquivo", batch.filename],
        ["Status", batch.status],
        ["Total de Itens", batch.total_items],
        ["Válidas", batch.valid_items],
        ["Inválidas", batch.invalid_items],
        ["Autorizadas", batch.authorized_items],
        ["Rejeitadas", batch.rejected_items],
        ["Resultado Desconhecido (UNKNOWN)", batch.unknown_items],
        [
            "Pendentes / Retry",
            sum(1 for it in items if it.status in {"PENDING", "VALID", "RETRY"}),
        ],
    ]

    headers = [
        "Linha",
        "Tomador",
        "Documento Tomador",
        "Valor Serviço",
        "Situação",
        "Chave / ID DPS",
        "Erros",
        "Tentativas",
        "Processado Em",
    ]

    data_rows = []
    for it in items:
        payload = json.loads(it.payload_json or "{}")
        val_errors = json.loads(it.validation_errors_json or "[]")
        err_texts = [f"{e.get('field', '')}: {e.get('message', '')}" for e in val_errors]
        if it.last_error:
            err_texts.append(it.last_error)

        ident = it.chave_acesso or it.id_dps or ""
        proc_str = it.processed_at.isoformat() if it.processed_at else ""
        data_rows.append(
            [
                it.row_number,
                payload.get("nome_tomador") or "",
                payload.get("documento_tomador") or "",
                float(payload.get("valor_servico") or 0.0),
                it.status,
                ident,
                " | ".join(err_texts),
                it.attempts,
                proc_str,
            ]
        )

    filename = f"resultado_lote_{batch.id[:8]}.{fmt_clean}"

    if fmt_clean == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(headers)
        for row in data_rows:
            writer.writerow(row)
        payload_bytes = ("\ufeff" + out.getvalue()).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload_bytes),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    wb = openpyxl.Workbook()
    ws_resumo = wb.active
    ws_resumo.title = "Resumo Lote"
    ws_resumo.append(["Indicador", "Valor"])
    for sr in summary_rows:
        ws_resumo.append(sr)

    ws_itens = wb.create_sheet(title="Itens do Lote")
    ws_itens.append(headers)
    for row in data_rows:
        ws_itens.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

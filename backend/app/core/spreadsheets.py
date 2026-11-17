"""Utilitários compartilhados para leitura, normalização e geração de planilhas CSV/XLSX."""

from __future__ import annotations

import csv
import datetime
import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import openpyxl

ALLOWED_SPREADSHEET_EXTENSIONS = {"csv", "xlsx", "xlsm"}


def clean_doc(val: Optional[str]) -> str:
    """Mantém dígitos e letras maiúsculas para suportar CPF e CNPJ numérico/alfanumérico."""
    return re.sub(r"[^0-9A-Za-z]", "", str(val or "")).upper()


def is_valid_cpf(cpf: str) -> bool:
    """Valida CPF numérico de 11 dígitos e seus dígitos verificadores."""
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(cpf[idx]) * ((size + 1) - idx) for idx in range(size))
        digit = (total * 10) % 11
        if digit == 10:
            digit = 0
        if int(cpf[size]) != digit:
            return False
    return True


def is_valid_cnpj(cnpj: str) -> bool:
    """Valida CNPJ de 14 caracteres (numérico ou alfanumérico NT 2026 via ASCII - 48)."""
    doc = clean_doc(cnpj)
    if len(doc) != 14:
        return False
    if not doc[:12].isalnum() or not doc[12:].isdigit():
        return False
    if doc == doc[0] * 14:
        return False

    def _calc_dv(base: str) -> int:
        weights = list(range(len(base) - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum((ord(ch) - 48) * w for ch, w in zip(base, weights))
        rem = total % 11
        return 0 if rem < 2 else 11 - rem

    dv1 = _calc_dv(doc[:12])
    dv2 = _calc_dv(doc[:12] + str(dv1))
    return doc[12:] == f"{dv1}{dv2}"


def validate_cpf_cnpj(doc: Optional[str]) -> Tuple[bool, str, Optional[str]]:
    """Normaliza e valida CPF (11) ou CNPJ numérico/alfanumérico (14)."""
    cleaned = clean_doc(doc)
    if len(cleaned) == 11:
        if is_valid_cpf(cleaned):
            return True, cleaned, None
        return False, cleaned, "CPF inválido (dígitos verificadores não conferem)."
    if len(cleaned) == 14:
        if is_valid_cnpj(cleaned):
            return True, cleaned, None
        return False, cleaned, "CNPJ inválido (dígitos verificadores não conferem)."
    return False, cleaned, "Documento do tomador deve ter 11 (CPF) ou 14 caracteres (CNPJ)."


def normalize_col(col: Any) -> str:
    """Normaliza nome de coluna para snake_case ASCII sem acentos."""
    s = unicodedata.normalize("NFKD", str(col or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in {"1", "true", "sim", "s", "yes", "y", "verdadeiro"}


def parse_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    raw = str(val).strip().replace("R$", "").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    return float(raw)


def parse_date_iso(val: Any) -> Optional[str]:
    """Normaliza datas BR/ISO ou competências (MM/YYYY, YYYY-MM) para YYYY-MM-DD."""
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date().isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()

    raw = str(val).strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        datetime.date.fromisoformat(raw)
        return raw
    if re.match(r"^\d{4}-\d{2}$", raw):
        normalized = f"{raw}-01"
        datetime.date.fromisoformat(normalized)
        return normalized
    m_br = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw)
    if m_br:
        day, month, year = int(m_br.group(1)), int(m_br.group(2)), int(m_br.group(3))
        return datetime.date(year, month, day).isoformat()
    m_comp = re.match(r"^(\d{2})/(\d{4})$", raw)
    if m_comp:
        month, year = int(m_comp.group(1)), int(m_comp.group(2))
        return datetime.date(year, month, 1).isoformat()
    raise ValueError(f"Data inválida: '{raw}'. Utilize DD/MM/AAAA, AAAA-MM-DD ou MM/AAAA.")


def format_cell_text(val: Any) -> str:
    """Preserva valores textuais sem perder zeros à esquerda caso venham como float/int do Excel."""
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def parse_spreadsheet_with_meta(
    content: bytes,
    filename: str,
    delimiter: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    max_rows: int = 2000,
) -> Dict[str, Any]:
    """Lê CSV ou XLSX preservando textos, detectando cabeçalhos duplicados e aplicando limites."""
    if not content:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite máximo permitido ({max_bytes // (1024 * 1024)} MB).",
        )

    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext not in ALLOWED_SPREADSHEET_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Extensão de arquivo não suportada. Envie um arquivo .csv, .xlsx ou .xlsm.",
        )

    rows: List[Dict[str, Any]] = []
    headers: List[str] = []
    duplicate_headers: List[str] = []

    if ext in {"xlsx", "xlsm"}:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Planilha XLSX inválida ou corrompida: {exc}") from exc
        ws = wb.active
        iter_rows = ws.iter_rows(values_only=True)
        try:
            raw_headers = next(iter_rows)
        except StopIteration:
            return {"headers": [], "duplicate_headers": [], "rows": []}

        seen = set()
        for h in raw_headers:
            norm = normalize_col(h)
            if norm:
                if norm in seen and norm not in duplicate_headers:
                    duplicate_headers.append(norm)
                seen.add(norm)
            headers.append(norm)

        for line_idx, values in enumerate(iter_rows, start=2):
            if not any(v is not None and str(v).strip() != "" for v in values):
                continue
            item = {headers[i]: values[i] for i in range(min(len(headers), len(values))) if headers[i]}
            item["_linha"] = line_idx
            rows.append(item)
            if len(rows) > max_rows:
                raise HTTPException(
                    status_code=400,
                    detail=f"A planilha excede o limite máximo de {max_rows} linhas por lote.",
                )
        return {"headers": [h for h in headers if h], "duplicate_headers": duplicate_headers, "rows": rows}

    # CSV
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Não foi possível decodificar o arquivo CSV.") from exc

    lines = text.splitlines()
    if not lines:
        return {"headers": [], "duplicate_headers": [], "rows": []}

    first_line = lines[0]
    sep = delimiter if delimiter in {",", ";"} else (";" if first_line.count(";") > first_line.count(",") else ",")

    raw_header_cells = next(csv.reader([first_line], delimiter=sep))
    seen = set()
    for h in raw_header_cells:
        norm = normalize_col(h)
        if norm:
            if norm in seen and norm not in duplicate_headers:
                duplicate_headers.append(norm)
            seen.add(norm)
        headers.append(norm)

    reader = csv.reader(io.StringIO("\n".join(lines[1:])), delimiter=sep)
    for line_idx, values in enumerate(reader, start=2):
        if not any(v is not None and str(v).strip() != "" for v in values):
            continue
        item = {headers[i]: values[i] for i in range(min(len(headers), len(values))) if headers[i]}
        item["_linha"] = line_idx
        rows.append(item)
        if len(rows) > max_rows:
            raise HTTPException(
                status_code=400,
                detail=f"O arquivo CSV excede o limite máximo de {max_rows} linhas por lote.",
            )

    return {"headers": [h for h in headers if h], "duplicate_headers": duplicate_headers, "rows": rows}


def parse_spreadsheet_rows(content: bytes, filename: str) -> List[Dict[str, Any]]:
    """Wrapper compatível para leitura direta das linhas normalizadas."""
    return parse_spreadsheet_with_meta(content=content, filename=filename)["rows"]


def build_template_response(
    headers: List[str],
    sample_row: List[Any],
    filename_base: str,
    fmt: str,
    sheet_title: str = "Modelo Importação",
    instructions_rows: Optional[List[List[Any]]] = None,
    text_columns: Optional[List[int]] = None,
) -> StreamingResponse:
    """Gera resposta de download para modelos CSV (`;`) ou XLSX com aba opcional de instruções."""
    fmt_clean = (fmt or "xlsx").strip().lower()
    if fmt_clean == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(headers)
        writer.writerow(sample_row)
        payload = ("\ufeff" + out.getvalue()).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.csv"},
        )
    if fmt_clean == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title
        ws.append(headers)
        ws.append(sample_row)
        if text_columns:
            for col_idx in text_columns:
                for row_idx in range(2, 20):
                    ws.cell(row=row_idx, column=col_idx).number_format = "@"
        if instructions_rows:
            ws_inst = wb.create_sheet(title="Instrucoes")
            for row in instructions_rows:
                ws_inst.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.xlsx"},
        )
    raise HTTPException(status_code=400, detail="Formato inválido. Utilize 'csv' ou 'xlsx'.")

"""Importador e normalizador de planilhas CSV/XLSX para emissão de NFS-e em lote."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.spreadsheets import (
    build_template_response,
    clean_doc,
    format_cell_text,
    parse_bool,
    parse_date_iso,
    parse_float,
    parse_spreadsheet_with_meta,
)

BATCH_SPREADSHEET_HEADERS = [
    "documento_tomador",
    "nome_tomador",
    "email_tomador",
    "cep_tomador",
    "logradouro_tomador",
    "numero_tomador",
    "bairro_tomador",
    "municipio_tomador",
    "codigo_servico",
    "c_trib_nac",
    "c_nbs",
    "descricao_servico",
    "discriminacao",
    "valor_servico",
    "valor_deducao",
    "valor_desconto",
    "aliquota_iss",
    "iss_retido",
    "reter_federais",
    "municipio_prestacao",
    "competencia",
    "cst_ibs_cbs",
    "cclasstrib",
    "indop",
]

REQUIRED_BATCH_HEADERS = {
    "documento_tomador",
    "nome_tomador",
    "valor_servico",
    "competencia",
}

BATCH_SAMPLE_ROW = [
    "11222333000181",
    "EMPRESA TOMADORA EXEMPLO LTDA",
    "financeiro@tomadora.example",
    "29160000",
    "Av. Central",
    "100",
    "Centro",
    "3201308",
    "CONS-TI",
    "010101",
    "115021000",
    "Consultoria em Tecnologia da Informação",
    "Prestação de serviços de desenvolvimento e consultoria técnica mensal",
    "2500.00",
    "0.00",
    "0.00",
    "2.0",
    "nao",
    "nao",
    "3201308",
    "2026-06-15",
    "000",
    "000001",
    "100301",
]

BATCH_INSTRUCTIONS_ROWS = [
    ["Coluna", "Obrigatoriedade", "Formato / Regra", "Exemplo"],
    ["documento_tomador", "Obrigatória", "CPF (11) ou CNPJ (14 numéricos ou alfanuméricos) como texto", "11222333000181"],
    ["nome_tomador", "Obrigatória", "Nome completo ou Razão Social do tomador", "EMPRESA EXEMPLO LTDA"],
    ["email_tomador", "Opcional", "E-mail para envio automático do XML/DANFSe", "fiscal@empresa.com"],
    ["cep_tomador", "Condicional", "8 dígitos (obrigatório se tomador não estiver cadastrado)", "29160000"],
    ["logradouro_tomador", "Condicional", "Endereço do tomador (ou preenchido pelo cadastro)", "Av. Central"],
    ["numero_tomador", "Condicional", "Número do endereço (padrão S/N)", "100"],
    ["bairro_tomador", "Condicional", "Bairro do tomador", "Centro"],
    ["municipio_tomador", "Condicional", "Código IBGE de 7 dígitos (padrão do prestador se cadastrado)", "3201308"],
    ["codigo_servico", "Obrigatória*", "Código interno/título de serviço cadastrado (ou informe c_trib_nac)", "CONS-TI"],
    ["c_trib_nac", "Condicional", "Código 6 dígitos da LC 116/ADN (obrigatório se codigo_servico não existir)", "010101"],
    ["c_nbs", "Opcional", "Código NBS 9 dígitos (preenchido pelo Anexo VIII se vazio)", "115021000"],
    ["descricao_servico", "Obrigatória*", "Nome/título curto do serviço", "Consultoria TI"],
    ["discriminacao", "Obrigatória*", "Descrição detalhada da nota (vai na tag xDescServ)", "Consultoria mensal"],
    ["valor_servico", "Obrigatória", "Valor bruto (> 0). Aceita 1.250,50 ou 1250.50", "2500.00"],
    ["valor_deducao", "Opcional", "Valor de deduções legais (>= 0)", "0.00"],
    ["valor_desconto", "Opcional", "Desconto incondicionado (>= 0)", "0.00"],
    ["aliquota_iss", "Conforme regra", "Alíquota ISS em % (ex.: 2.0 ou 5.0)", "2.0"],
    ["iss_retido", "Opcional", "sim ou nao", "nao"],
    ["reter_federais", "Opcional", "sim ou nao", "nao"],
    ["municipio_prestacao", "Conforme regra", "Código IBGE 7 dígitos do local da prestação", "3201308"],
    ["competencia", "Obrigatória", "DD/MM/AAAA, AAAA-MM-DD ou MM/AAAA", "2026-06-15"],
    ["cst_ibs_cbs", "Conforme regra", "3 dígitos (ex.: 000, 200) — Anexo VIII completa se omitido", "000"],
    ["cclasstrib", "Conforme regra", "6 dígitos (ex.: 000001) — Anexo VIII completa se omitido", "000001"],
    ["indop", "Conforme regra", "6 dígitos (ex.: 100301)", "100301"],
]


def build_batch_template(fmt: str = "xlsx"):
    """Retorna o modelo oficial de planilha de emissão em lote (CSV ou XLSX com aba de instruções)."""
    return build_template_response(
        headers=BATCH_SPREADSHEET_HEADERS,
        sample_row=BATCH_SAMPLE_ROW,
        filename_base="modelo_emissao_nfse_lote",
        fmt=fmt,
        sheet_title="Notas Lote",
        instructions_rows=BATCH_INSTRUCTIONS_ROWS,
        text_columns=[1, 4, 8, 9, 10, 11, 20, 22, 23, 24],
    )


def _safe_float_field(
    raw_row: Dict[str, Any],
    field: str,
    default: Optional[float],
    parse_errors: List[Dict[str, str]],
) -> Optional[float]:
    val = raw_row.get(field)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    try:
        return parse_float(val, default=default)
    except (TypeError, ValueError):
        parse_errors.append(
            {
                "field": field,
                "level": "estrutural",
                "message": f"Valor numérico inválido em '{field}': '{val}'.",
            }
        )
        return None


TAX_CODE_PAD_WIDTHS: Dict[str, int] = {
    "c_trib_nac": 6,
    "cst_ibs_cbs": 3,
    "cclasstrib": 6,
    "indop": 6,
    "c_nbs": 9,
}


def _parse_optional_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    txt = str(val).strip()
    if not txt:
        return None
    return parse_bool(txt)


def _pad_numeric_code(val: Any, width: int) -> str:
    txt = format_cell_text(val)
    if not txt:
        return ""
    return txt.zfill(width) if txt.isdigit() else txt


def normalize_tax_code_field(field: str, val: Any) -> str:
    width = TAX_CODE_PAD_WIDTHS.get(field)
    return _pad_numeric_code(val, width) if width else format_cell_text(val)


def _first_present(raw_row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        val = raw_row.get(k)
        if val is not None and str(val).strip() != "":
            return val
    return None


def _normalize_ibge_digits(val: Any) -> str:
    txt = format_cell_text(val)
    digits = "".join(ch for ch in txt if ch.isdigit())
    return digits or txt


def normalize_batch_row(raw_row: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza uma linha bruta CSV/XLSX preservando textos e capturando erros de parsing por campo."""
    parse_errors: List[Dict[str, str]] = []

    doc_raw = format_cell_text(_first_present(raw_row, "documento_tomador", "cnpj_tomador", "cpf_tomador"))
    doc_clean = clean_doc(doc_raw)

    comp_raw = raw_row.get("competencia")
    competencia_iso: Optional[str] = None
    if comp_raw is not None and str(comp_raw).strip() != "":
        try:
            competencia_iso = parse_date_iso(comp_raw)
        except ValueError as exc:
            parse_errors.append({"field": "competencia", "level": "estrutural", "message": str(exc)})
    else:
        parse_errors.append(
            {"field": "competencia", "level": "estrutural", "message": "Coluna 'competencia' é obrigatória."}
        )

    valor_servico = _safe_float_field(raw_row, "valor_servico", None, parse_errors)
    valor_deducao = _safe_float_field(raw_row, "valor_deducao", 0.0, parse_errors)
    valor_desconto = _safe_float_field(raw_row, "valor_desconto", 0.0, parse_errors)
    aliquota_iss = _safe_float_field(raw_row, "aliquota_iss", None, parse_errors)

    payload = {
        "documento_tomador": doc_clean or doc_raw,
        "nome_tomador": format_cell_text(raw_row.get("nome_tomador")),
        "email_tomador": format_cell_text(raw_row.get("email_tomador")),
        "cep_tomador": "".join(ch for ch in format_cell_text(raw_row.get("cep_tomador")) if ch.isdigit()),
        "logradouro_tomador": format_cell_text(raw_row.get("logradouro_tomador")),
        "numero_tomador": format_cell_text(raw_row.get("numero_tomador")),
        "bairro_tomador": format_cell_text(raw_row.get("bairro_tomador")),
        "municipio_tomador": _normalize_ibge_digits(raw_row.get("municipio_tomador")),
        "codigo_servico": format_cell_text(raw_row.get("codigo_servico")),
        "c_trib_nac": _pad_numeric_code(_first_present(raw_row, "c_trib_nac", "ctribnac"), 6),
        "c_nbs": _pad_numeric_code(_first_present(raw_row, "c_nbs", "cnbs"), 9),
        "descricao_servico": format_cell_text(raw_row.get("descricao_servico")),
        "discriminacao": format_cell_text(raw_row.get("discriminacao")),
        "valor_servico": valor_servico,
        "valor_deducao": valor_deducao if valor_deducao is not None else 0.0,
        "valor_desconto": valor_desconto if valor_desconto is not None else 0.0,
        "aliquota_iss": aliquota_iss,
        "iss_retido": _parse_optional_bool(raw_row.get("iss_retido")),
        "reter_federais": _parse_optional_bool(raw_row.get("reter_federais")),
        "municipio_prestacao": _normalize_ibge_digits(raw_row.get("municipio_prestacao")),
        "competencia": competencia_iso or format_cell_text(comp_raw),
        "cst_ibs_cbs": _pad_numeric_code(_first_present(raw_row, "cst_ibs_cbs", "cst"), 3),
        "cclasstrib": _pad_numeric_code(_first_present(raw_row, "cclasstrib", "c_class_trib"), 6),
        "indop": _pad_numeric_code(_first_present(raw_row, "indop", "c_ind_op"), 6),
        "_parse_errors": parse_errors,
    }
    return payload


def parse_batch_file(
    content: bytes,
    filename: str,
    delimiter: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    max_rows: int = 2000,
) -> Dict[str, Any]:
    """Lê, valida cabeçalhos e normaliza todas as linhas da planilha de notas."""
    parsed = parse_spreadsheet_with_meta(
        content=content,
        filename=filename,
        delimiter=delimiter,
        max_bytes=max_bytes,
        max_rows=max_rows,
    )
    headers = set(parsed["headers"])
    if parsed["duplicate_headers"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cabeçalhos duplicados encontrados na planilha: {', '.join(parsed['duplicate_headers'])}",
        )
    missing = sorted(REQUIRED_BATCH_HEADERS - headers)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colunas obrigatórias ausentes na planilha: {', '.join(missing)}",
        )
    if "codigo_servico" not in headers and "c_trib_nac" not in headers:
        raise HTTPException(
            status_code=400,
            detail="A planilha deve conter a coluna 'codigo_servico' ou 'c_trib_nac'.",
        )
    rows = parsed["rows"]
    if not rows:
        raise HTTPException(status_code=400, detail="A planilha não possui linhas de notas preenchidas.")

    file_hash = hashlib.sha256(content).hexdigest()
    normalized_items = []
    for raw_row in rows:
        row_num = int(raw_row.get("_linha") or 0)
        serializable_raw = {k: format_cell_text(v) for k, v in raw_row.items() if k != "_linha"}
        normalized_items.append(
            {
                "row_number": row_num,
                "raw_data": serializable_raw,
                "payload": normalize_batch_row(raw_row),
            }
        )

    return {
        "file_hash": file_hash,
        "headers": parsed["headers"],
        "items": normalized_items,
    }

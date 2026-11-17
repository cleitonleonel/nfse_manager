"""Serviço de consulta automática de CNPJ e CEP com fallback multi-provedor e cache em memória.

Retorna dados já normalizados para o padrão da NFS-e Nacional (código IBGE de 7 dígitos,
sugestão de regime tributário Simples/MEI/Normal, endereço e contatos).
"""

from __future__ import annotations

import re
from typing import Any, Dict

import httpx2 as httpx
from fastapi import HTTPException

_CNPJ_CACHE: Dict[str, Dict[str, Any]] = {}
_CEP_CACHE: Dict[str, Dict[str, Any]] = {}


def _only_digits(val: str | None) -> str:
    return re.sub(r"\D", "", str(val or ""))


def _clean_cnpj(val: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(val or "")).upper()


class LookupService:
    """Consulta inteligente de CNPJ e CEP para preenchimento rápido de Prestadores e Tomadores."""

    @staticmethod
    async def consultar_cep(cep: str) -> Dict[str, Any]:
        cep_limpo = _only_digits(cep)
        if len(cep_limpo) != 8:
            raise HTTPException(status_code=400, detail="CEP inválido. Informe 8 dígitos numéricos.")

        if cep_limpo in _CEP_CACHE:
            return _CEP_CACHE[cep_limpo]

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # 1. Tentativa Primária: ViaCEP (retorna código IBGE de 7 dígitos nativamente)
            try:
                resp = await client.get(f"https://viacep.com.br/ws/{cep_limpo}/json/")
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get("erro"):
                        result = {
                            "cep": cep_limpo,
                            "logradouro": data.get("logradouro") or "",
                            "complemento": data.get("complemento") or "",
                            "bairro": data.get("bairro") or "",
                            "municipio": data.get("localidade") or "",
                            "uf": data.get("uf") or "",
                            "codigo_municipio": _only_digits(data.get("ibge")) or "",
                        }
                        _CEP_CACHE[cep_limpo] = result
                        return result
            except Exception:
                pass

            # 2. Fallback: BrasilAPI CEP v2
            try:
                resp2 = await client.get(f"https://brasilapi.com.br/api/cep/v2/{cep_limpo}")
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    result = {
                        "cep": cep_limpo,
                        "logradouro": data2.get("street") or "",
                        "complemento": "",
                        "bairro": data2.get("neighborhood") or "",
                        "municipio": data2.get("city") or "",
                        "uf": data2.get("state") or "",
                        "codigo_municipio": "",
                    }
                    _CEP_CACHE[cep_limpo] = result
                    return result
            except Exception:
                pass

        raise HTTPException(status_code=404, detail=f"CEP {cep_limpo} não encontrado.")

    @staticmethod
    async def consultar_cnpj(cnpj: str) -> Dict[str, Any]:
        cnpj_limpo = _clean_cnpj(cnpj)
        if len(cnpj_limpo) != 14:
            raise HTTPException(status_code=400, detail="CNPJ inválido. Informe 14 caracteres.")

        if cnpj_limpo in _CNPJ_CACHE:
            return _CNPJ_CACHE[cnpj_limpo]

        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            # 1. Tentativa Primária: BrasilAPI CNPJ v1 (retorna codigo_municipio_ibge e Simples/MEI)
            try:
                resp = await client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}")
                if resp.status_code == 200:
                    data = resp.json()
                    regime = "normal"
                    if data.get("opcao_pelo_mei"):
                        regime = "mei"
                    elif data.get("opcao_pelo_simples"):
                        regime = "simples"

                    cep_empresa = _only_digits(data.get("cep")).zfill(8) if data.get("cep") else ""
                    cod_ibge = _only_digits(str(data.get("codigo_municipio_ibge") or ""))
                    if len(cod_ibge) != 7 and len(cep_empresa) == 8:
                        try:
                            cep_info = await LookupService.consultar_cep(cep_empresa)
                            cod_ibge = cep_info.get("codigo_municipio") or cod_ibge
                        except Exception:
                            pass

                    result = {
                        "cnpj": cnpj_limpo,
                        "razao_social": data.get("razao_social") or "",
                        "nome_fantasia": data.get("nome_fantasia") or "",
                        "email": (data.get("email") or "").lower(),
                        "telefone": _only_digits(data.get("ddd_telefone_1") or data.get("telefone")),
                        "cep": cep_empresa,
                        "logradouro": data.get("logradouro") or "",
                        "numero": str(data.get("numero") or ""),
                        "complemento": data.get("complemento") or "",
                        "bairro": data.get("bairro") or "",
                        "municipio": data.get("municipio") or "",
                        "uf": data.get("uf") or "",
                        "codigo_municipio": cod_ibge,
                        "regime_tributario": regime,
                        "cnae_fiscal": str(data.get("cnae_fiscal") or ""),
                        "cnae_fiscal_descricao": data.get("cnae_fiscal_descricao") or "",
                    }
                    _CNPJ_CACHE[cnpj_limpo] = result
                    return result
            except Exception:
                pass

            # 2. Fallback: ReceitaWS
            try:
                resp2 = await client.get(f"https://receitaws.com.br/v1/cnpj/{cnpj_limpo}")
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    if data2.get("status") != "ERROR":
                        simples = (data2.get("simples") or {}).get("optante", False)
                        simei = (data2.get("simei") or {}).get("optante", False)
                        regime = "mei" if simei else ("simples" if simples else "normal")
                        cep_empresa = _only_digits(data2.get("cep"))
                        cod_ibge = ""
                        if len(cep_empresa) == 8:
                            try:
                                cep_info = await LookupService.consultar_cep(cep_empresa)
                                cod_ibge = cep_info.get("codigo_municipio") or ""
                            except Exception:
                                pass

                        result = {
                            "cnpj": cnpj_limpo,
                            "razao_social": data2.get("nome") or "",
                            "nome_fantasia": data2.get("fantasia") or "",
                            "email": (data2.get("email") or "").lower(),
                            "telefone": _only_digits(data2.get("telefone")),
                            "cep": cep_empresa,
                            "logradouro": data2.get("logradouro") or "",
                            "numero": str(data2.get("numero") or ""),
                            "complemento": data2.get("complemento") or "",
                            "bairro": data2.get("bairro") or "",
                            "municipio": data2.get("municipio") or "",
                            "uf": data2.get("uf") or "",
                            "codigo_municipio": cod_ibge,
                            "regime_tributario": regime,
                            "cnae_fiscal": "",
                            "cnae_fiscal_descricao": "",
                        }
                        _CNPJ_CACHE[cnpj_limpo] = result
                        return result
            except Exception:
                pass

        raise HTTPException(status_code=404, detail=f"CNPJ {cnpj_limpo} não encontrado nas bases públicas.")

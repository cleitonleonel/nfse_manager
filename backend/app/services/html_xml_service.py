"""
Serviço de conversão de HTML de impressão da NFS-e para XML padrão SPED
e geração de DANFSe em PDF via `pynfse`.
"""

import logging
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Union

from pynfse.danfse_generator import DanfseGenerator
from pynfse.html_to_xml import (
    NS_NFSE,
    converter_arquivo_html_para_xml as _pynfse_converter_arquivo_html_para_xml,
    converter_html_para_xml as _pynfse_converter_html_para_xml,
)
from pynfse.xml_parser import extrair_dados_nfse

logger = logging.getLogger(__name__)


def converter_html_para_xml(html_content: str) -> str:
    """Converte o HTML da página de impressão do Emissor Nacional em string XML padrão SPED."""
    return _pynfse_converter_html_para_xml(html_content)


def converter_arquivo_html_para_xml(
    html_path: Union[str, Path],
    xml_output_path: Optional[Union[str, Path]] = None,
) -> str:
    """Lê um arquivo `.html` baixado, converte para `.xml` e retorna o caminho do XML salvo."""
    return _pynfse_converter_arquivo_html_para_xml(html_path, xml_output_path)


def extrair_chave_do_xml(xml_content: str) -> Optional[str]:
    """Extrai a chave de 50 dígitos a partir de uma string XML da NFS-e."""
    try:
        root = ET.fromstring(xml_content.lstrip())
        ns = {"n": NS_NFSE}
        inf = root.find("n:infNFSe", ns)
        if inf is None:
            inf = root
        inf_id = inf.get("Id", "")
        if inf_id:
            return inf_id.replace("NFS", "").strip()
    except Exception:
        pass
    return None


def enriquecer_nota_com_xml(
    invoice: Any,
    xml_path: Optional[Union[str, Path]] = None,
    dados: Optional[Dict[str, Any]] = None,
    atualizar_data: bool = False,
    apenas_se_vazio: bool = False,
) -> Dict[str, Any]:
    """
    Extrai metadados do XML da NFS-e (se `dados` não for informado) e atualiza
    os campos `xml_path`, `valor`, `numero` (e opcionalmente `data_emissao`) da nota.
    """
    if dados is None and xml_path:
        try:
            dados = extrair_dados_nfse(str(xml_path))
        except Exception:
            dados = {}
    dados = dados or {}

    if not invoice:
        return dados

    if xml_path and (not apenas_se_vazio or not getattr(invoice, "xml_path", None)):
        invoice.xml_path = str(xml_path)

    valor_xml = dados.get("valor", 0)
    valor_atual = getattr(invoice, "valor", None)
    if valor_xml and valor_xml > 0 and (not apenas_se_vazio or not valor_atual or valor_atual == 0):
        invoice.valor = valor_xml

    numero_xml = dados.get("numero")
    numero_atual = getattr(invoice, "numero", None)
    chave_atual = getattr(invoice, "chave", None)
    if numero_xml and (not apenas_se_vazio or not numero_atual or numero_atual == chave_atual):
        invoice.numero = numero_xml

    if atualizar_data and dados.get("data_emissao"):
        invoice.data_emissao = dados["data_emissao"]

    return dados


def converter_xml_para_pdf_pynfse(
    xml_content: Optional[str] = None,
    xml_path: Optional[Union[str, Path]] = None,
    pdf_output_path: Optional[Union[str, Path]] = None,
    status: str = "NORMAL",
    default_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Recebe o XML gerado (em string `xml_content` ou caminho `xml_path`) e utiliza
    `pynfse.danfse_generator.DanfseGenerator` para convertê-lo em PDF (DANFSe).

    Returns:
        dict com `pdf_path`, `xml_path`, `chave` e `dados`.
    """
    if not xml_content and not xml_path:
        raise ValueError("Informe `xml_content` ou `xml_path` para converter em PDF.")

    resolved_xml_path: Optional[Path] = Path(xml_path) if xml_path else None
    temp_xml_file: Optional[Path] = None

    try:
        if resolved_xml_path and resolved_xml_path.exists():
            if not xml_content:
                xml_content = resolved_xml_path.read_text(encoding="utf-8", errors="replace")
        elif xml_content:
            chave = extrair_chave_do_xml(xml_content) or "nfse_convertida"
            if resolved_xml_path:
                resolved_xml_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_xml_path.write_text(xml_content, encoding="utf-8")
            elif default_dir:
                xml_dir = Path(default_dir) / "xmls"
                xml_dir.mkdir(parents=True, exist_ok=True)
                resolved_xml_path = xml_dir / f"{chave}.xml"
                resolved_xml_path.write_text(xml_content, encoding="utf-8")
            else:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8")
                tmp.write(xml_content)
                tmp.close()
                temp_xml_file = Path(tmp.name)
                resolved_xml_path = temp_xml_file
        else:
            raise FileNotFoundError(f"Arquivo XML não encontrado: {xml_path}")

        xml_source_for_pdf = str(resolved_xml_path)
        chave = extrair_chave_do_xml(xml_content or "") or resolved_xml_path.stem

        if pdf_output_path:
            target_pdf = Path(pdf_output_path)
        elif not temp_xml_file:
            pdf_str = (
                str(resolved_xml_path.with_suffix(".pdf"))
                .replace("/xmls/", "/pdfs/")
                .replace("\\xmls\\", "\\pdfs\\")
            )
            target_pdf = Path(pdf_str)
        else:
            base_dir = Path(default_dir) if default_dir else Path(tempfile.gettempdir())
            pdf_dir = base_dir / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            target_pdf = pdf_dir / f"{chave}.pdf"

        target_pdf.parent.mkdir(parents=True, exist_ok=True)

        status_norm = (status or "NORMAL").upper()
        if status_norm in ("GERADA", "EMITIDA", "UNKNOWN", ""):
            status_norm = "NORMAL"

        generator = DanfseGenerator(xml_source_for_pdf, status=status_norm)
        generator.gerar_pdf(str(target_pdf))

        dados = extrair_dados_nfse(xml_source_for_pdf)
        logger.info(f"PDF gerado pelo pynfse com sucesso em: {target_pdf}")

        return {
            "pdf_path": str(target_pdf),
            "xml_path": None if temp_xml_file else str(resolved_xml_path),
            "chave": dados.get("chave") or chave,
            "dados": dados,
        }
    finally:
        if temp_xml_file and temp_xml_file.exists():
            try:
                temp_xml_file.unlink()
            except Exception:
                pass


def montar_caminho_destino_nfse(
    nfse: Any,
    chave: str,
    extensao: str,
    status: str = "gerada",
    data_emissao: Any = None,
) -> Path:
    """
    Reproduz a montagem de diretório do `ClienteNfseNacional` para salvar
    arquivos `.html`, `.xml` e `.pdf` na estrutura configurada do cliente.
    """
    ext_norm = extensao.lower().lstrip(".")
    pasta_ext = "pdfs" if ext_norm in ("pdf", "html") else f"{ext_norm}s"
    nome_arquivo = f"{chave}.{ext_norm}"

    ano, mes, dia = "0000", "00", "00"
    if data_emissao:
        try:
            if isinstance(data_emissao, str):
                from datetime import datetime

                if "T" in data_emissao:
                    dt = datetime.fromisoformat(data_emissao.replace("Z", "+00:00"))
                elif "/" in data_emissao:
                    dt = datetime.strptime(data_emissao, "%d/%m/%Y")
                else:
                    dt = datetime.strptime(data_emissao, "%Y-%m-%d %H:%M:%S")
                ano, mes, dia = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
            elif hasattr(data_emissao, "strftime"):
                ano = data_emissao.strftime("%Y")
                mes = data_emissao.strftime("%m")
                dia = data_emissao.strftime("%d")
        except Exception:
            pass

    cnpj_usuario = getattr(nfse, "_cnpj_usuario", None) or (
        nfse.obter_cnpj() if hasattr(nfse, "obter_cnpj") else None
    )
    razao_social = getattr(nfse, "razao_social", None)
    tipo_consulta = getattr(nfse, "_tipo_consulta", None) or "outros"
    save_path = getattr(nfse, "save_path", None) or "downloads"
    estrutura = getattr(nfse, "path_structure", None) or "{CLIENTE}/{TIPO}/{ANO}/{MES}"

    tags = {
        "{ANO}": ano,
        "{MES}": mes,
        "{DIA}": dia,
        "{CLIENTE}": razao_social or cnpj_usuario or "CLIENTE_DESCONHECIDO",
        "{CNPJ}": cnpj_usuario or "00000000000000",
        "{TIPO}": tipo_consulta,
        "{STATUS}": (status or "gerada").lower(),
        "{EXT}": pasta_ext,
    }

    if "{TIPO}" not in estrutura:
        estrutura += "/{TIPO}"
    if "{STATUS}" not in estrutura:
        estrutura += "/{STATUS}"
    if "{EXT}" not in estrutura:
        estrutura += "/{EXT}"

    caminho_relativo = estrutura
    for tag, val in tags.items():
        caminho_relativo = caminho_relativo.replace(tag, val)

    caminho_final = Path(save_path)
    for part in [p for p in caminho_relativo.replace("\\", "/").split("/") if p.strip()]:
        caminho_final = caminho_final / part

    caminho_final.mkdir(parents=True, exist_ok=True)
    return caminho_final / nome_arquivo


def obter_html_e_gerar_xml_pdf(
    nfse: Any,
    url_ou_chave: str,
    status: str = "gerada",
    data_emissao: Any = None,
) -> Dict[str, Any]:
    """
    Obtém diretamente o HTML de impressão da nota no portal (sem tentar baixar XML ou PDF
    diretamente) e a partir dele gera o XML padrão SPED e o PDF (DANFSe) via `pynfse`.
    """
    chave = (url_ou_chave or "").rstrip("/").split("/")[-1].strip()
    if not chave:
        return {"html_path": None, "xml_path": None, "pdf_path": None, "dados": {}}

    caminho_xml = montar_caminho_destino_nfse(nfse, chave, "xml", status, data_emissao)
    caminho_pdf = montar_caminho_destino_nfse(nfse, chave, "pdf", status, data_emissao)
    caminho_html = caminho_pdf.with_suffix(".html")

    if not caminho_xml.exists() and not caminho_html.exists():
        logger.info(
            f"Cliente autenticado via usuário e senha (sem certificado). "
            f"Obtendo HTML de impressão diretamente para a chave: {chave}"
        )
        html_content = nfse.obter_impressao_html(chave)
        if html_content:
            caminho_html.parent.mkdir(parents=True, exist_ok=True)
            caminho_html.write_text(html_content, encoding="utf-8")
            logger.info(f"HTML de impressão salvo em: {caminho_html}")
        else:
            logger.warning(f"Não foi possível obter o HTML de impressão para a chave: {chave}")
            return {"html_path": None, "xml_path": None, "pdf_path": None, "dados": {}}

    if not caminho_xml.exists() and caminho_html.exists():
        try:
            converter_arquivo_html_para_xml(caminho_html, caminho_xml)
        except Exception as exc:
            logger.error(f"Erro ao converter HTML de impressão em XML ({chave}): {exc}")

    dados: Dict[str, Any] = {}
    if caminho_xml.exists():
        if not caminho_pdf.exists():
            try:
                res_pdf = converter_xml_para_pdf_pynfse(
                    xml_path=caminho_xml,
                    pdf_output_path=caminho_pdf,
                    status=status or "NORMAL",
                )
                dados = res_pdf.get("dados") or {}
            except Exception as exc:
                logger.error(f"Erro ao gerar PDF a partir do XML ({chave}): {exc}")
        if not dados:
            try:
                dados = extrair_dados_nfse(str(caminho_xml))
            except Exception:
                dados = {}

    return {
        "html_path": str(caminho_html) if caminho_html.exists() else None,
        "xml_path": str(caminho_xml) if caminho_xml.exists() else None,
        "pdf_path": str(caminho_pdf) if caminho_pdf.exists() else None,
        "dados": dados,
    }

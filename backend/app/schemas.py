from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ClientBase(BaseModel):
    cnpj: str
    razao_social: str
    username: str
    description: Optional[str] = None
    cert_path: Optional[str] = None
    save_path: Optional[str] = None
    path_structure: Optional[str] = None
    inscricao_municipal: Optional[str] = None
    codigo_municipio: Optional[str] = "3201308"
    uf: Optional[str] = "ES"
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    regime_tributario: Optional[str] = "normal"
    regime_apuracao_sn: Optional[str] = "1"
    regime_especial: Optional[str] = "0"
    serie_dps_padrao: Optional[str] = "900"
    ultimo_numero_dps: Optional[int] = 0
    ambiente_padrao: Optional[str] = "homologacao"


class ClientCreate(ClientBase):
    password: str
    cert_password: Optional[str] = None


class ClientUpdate(BaseModel):
    razao_social: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None
    cert_path: Optional[str] = None
    cert_password: Optional[str] = None
    save_path: Optional[str] = None
    path_structure: Optional[str] = None
    inscricao_municipal: Optional[str] = None
    codigo_municipio: Optional[str] = None
    uf: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    regime_tributario: Optional[str] = None
    regime_apuracao_sn: Optional[str] = None
    regime_especial: Optional[str] = None
    serie_dps_padrao: Optional[str] = None
    ultimo_numero_dps: Optional[int] = None
    ambiente_padrao: Optional[str] = None


class ClientResponse(ClientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class InvoiceBase(BaseModel):
    numero: str
    chave: str
    status: str
    tipo: str
    valor: Optional[float] = None
    data_emissao: datetime
    download_url_xml: Optional[str] = None
    download_url_pdf: Optional[str] = None
    id_dps: Optional[str] = None
    serie_dps: Optional[str] = None
    numero_dps: Optional[int] = None
    chave_substituida: Optional[str] = None
    chave_substituta: Optional[str] = None
    motivo_cancelamento: Optional[str] = None
    data_cancelamento: Optional[datetime] = None
    xml_dps_path: Optional[str] = None
    xml_evento_path: Optional[str] = None
    valor_iss: Optional[float] = None
    valor_ibs: Optional[float] = None
    valor_cbs: Optional[float] = None
    valor_liquido: Optional[float] = None
    c_trib_nac: Optional[str] = None
    c_nbs: Optional[str] = None
    c_class_trib: Optional[str] = None
    cst_ibscbs: Optional[str] = None


class InvoiceResponse(InvoiceBase):
    id: int
    client_id: int | None = None
    xml_path: Optional[str] = None
    pdf_path: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class SyncRequest(BaseModel):
    client_id: Optional[int] = None
    data_inicio: str  # DD/MM/AAAA
    data_fim: str  # DD/MM/AAAA
    tipo: str  # emitidas or recebidas


class DownloadRequest(BaseModel):
    client_id: int
    invoice_ids: List[int]
    action_type: str


class DashboardStats(BaseModel):
    total_notas: int
    total_emitidas: int
    total_recebidas: int
    total_clientes: int
    downloads_pendentes: int
    valor_total: float
    valor_emitidas: float
    valor_recebidas: float


class ChartPoint(BaseModel):
    label: str  # Ex: "2026-05-01"
    emitidas: int
    recebidas: int
    valor: float


class ChartData(BaseModel):
    points: List[ChartPoint]


class SupportMessage(BaseModel):
    email: str
    whatsapp: str
    message: str


class UpdateDownloadRequest(BaseModel):
    version: Optional[str] = None


class UpdateApplyRequest(BaseModel):
    task_id: str


# =====================================================================
# Schemas de Cálculo Tributário (ISSQN + Retenções + IBS/CBS - NT 1.101)
# =====================================================================


class TaxCalculationRequest(BaseModel):
    valor_servicos: float = Field(..., gt=0, description="Valor bruto do serviço prestado (vServ)")
    regime_prestador: str = Field("normal", description="normal | simples | mei")
    cClassTrib: str = Field("000001", description="Código de Classificação Tributária IBS/CBS (6 dígitos)")
    cst: Optional[str] = Field(None, description="Código de Situação Tributária IBS/CBS (3 dígitos)")
    cIndOp: str = Field("100301", description="Código Indicador de Operação (6 dígitos)")
    cTribNac: Optional[str] = Field(None, description="Código de Tributação Nacional LC 116 (6 dígitos)")
    cNBS: Optional[str] = Field(None, description="Código NBS (9 dígitos)")
    data_competencia: Optional[str] = Field(None, description="Data de competência AAAA-MM-DD ou DD/MM/AAAA")
    ano_competencia: Optional[int] = Field(None, description="Ano de competência (ex: 2026, 2027)")

    desconto_incondicionado: float = 0.0
    desconto_condicionado: float = 0.0
    deducao_reducao_iss: float = 0.0
    reembolso_repasse_ressarcimento: float = 0.0
    deducao_reducao_ibscbs: float = 0.0

    aliquota_iss: Optional[float] = None
    iss_retido: bool = False
    tp_ret_issqn: Optional[int] = None
    trib_issqn: int = 1

    reter_federais: bool = False
    cst_pis_cofins: str = "01"
    p_aliq_pis: Optional[float] = None
    p_aliq_cofins: Optional[float] = None
    v_pis_informado: Optional[float] = None
    v_cofins_informado: Optional[float] = None
    tp_ret_pis_cofins: str = "2"
    v_irrf_informado: Optional[float] = None
    v_csll_informado: Optional[float] = None
    v_inss_informado: Optional[float] = None

    p_ibs_uf: Optional[float] = None
    p_ibs_mun: Optional[float] = None
    p_cbs: Optional[float] = None
    p_red_aliq_uf: Optional[float] = None
    p_red_aliq_mun: Optional[float] = None
    p_red_aliq_cbs: Optional[float] = None

    tp_ente_gov: Optional[int] = None
    p_redutor_gov: Optional[float] = None

    p_dif_uf: Optional[float] = None
    p_dif_mun: Optional[float] = None
    p_dif_cbs: Optional[float] = None

    c_cred_pres: Optional[str] = None
    p_cred_pres_ibs: Optional[float] = None
    p_cred_pres_cbs: Optional[float] = None

    cst_reg: Optional[str] = None
    c_class_trib_reg: Optional[str] = None
    p_aliq_reg_ibs_uf: Optional[float] = None
    p_aliq_reg_ibs_mun: Optional[float] = None
    p_aliq_reg_cbs: Optional[float] = None

    ind_doacao: Optional[int] = None
    v_ibs_est_cred: Optional[float] = None
    v_cbs_est_cred: Optional[float] = None
    apurar_ibscbs_simples: bool = False


class TaxValidationRequest(BaseModel):
    cClassTrib: str
    cst: Optional[str] = None
    cIndOp: str = "100301"
    cTribNac: Optional[str] = None
    cNBS: Optional[str] = None
    tpOper: Optional[int] = None
    tpEnteGov: Optional[int] = None
    pRedutorGov: Optional[float] = None
    indDest: int = 0
    temDestinatario: bool = False
    temImovel: bool = False
    temRefNFSe: bool = False
    cstReg: Optional[str] = None
    cClassTribReg: Optional[str] = None
    pDifUF: Optional[float] = None
    pDifMun: Optional[float] = None
    pDifCBS: Optional[float] = None
    indDoacao: Optional[int] = None
    vIBSEstCred: Optional[float] = None
    vCBSEstCred: Optional[float] = None


# =====================================================================
# Schemas de Emissão, Cancelamento e Substituição via ADN (v1.01)
# =====================================================================


class EmitirDpsRequest(BaseModel):
    client_id: Optional[int] = Field(
        None, description="ID do cliente cadastrado no banco (usa o certificado .pfx salvo)"
    )
    ambiente: str = Field("homologacao", description="homologacao | producao")
    prestador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    tomador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    intermediario: Optional[Dict[str, Any]] = None
    servico: Dict[str, Any]
    tributacao: Optional[Dict[str, Any]] = None
    substituicao: Optional[Dict[str, Any]] = None
    serie_dps: str = "900"
    numero_dps: Optional[int] = None
    data_competencia: Optional[str] = None
    incluir_ibscbs: bool = True
    certificado_pfx_b64: Optional[str] = None
    senha_certificado: Optional[str] = None
    transmitir: bool = True


class CancelarNfseRequest(BaseModel):
    client_id: Optional[int] = Field(None, description="ID do cliente cadastrado no banco")
    invoice_id: Optional[int] = Field(None, description="ID da fatura no banco local")
    ambiente: str = "homologacao"
    chave_nfse: str = Field(..., description="Chave de acesso de 50 dígitos da NFS-e a cancelar")
    documento_autor: Optional[str] = Field(None, description="CNPJ/CPF do autor (opcional se client_id informado)")
    motivo_codigo: int = Field(1, description="1 - Erro na Emissão; 2 - Serviço não Prestado; 9 - Outros")
    motivo_descricao: str = Field(
        "Cancelamento efetuado devido a erro cadastral na emissão do documento.",
        min_length=15,
        max_length=255,
    )
    certificado_pfx_b64: Optional[str] = None
    senha_certificado: Optional[str] = None
    transmitir: bool = True


class SubstituirNfseRequest(BaseModel):
    client_id: Optional[int] = Field(None, description="ID do cliente cadastrado no banco")
    invoice_id_substituida: Optional[int] = Field(None, description="ID da fatura original no banco local")
    ambiente: str = "homologacao"
    chave_nfse_substituida: str = Field(..., description="Chave de 50 dígitos da NFS-e que será substituída")
    motivo_codigo: str = Field(
        "99",
        description="01-Desenquadramento SN; 02-Enquadramento SN; 03-Inclusão Imun/Isen; 04-Exclusão Imun/Isen; 05-Rejeição; 99-Outros",
    )
    motivo_descricao: str = Field(
        "Substituição de NFS-e para retificação de dados operacionais.",
        min_length=15,
        max_length=255,
    )
    prestador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    tomador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    intermediario: Optional[Dict[str, Any]] = None
    servico: Dict[str, Any]
    tributacao: Optional[Dict[str, Any]] = None
    serie_dps: str = "900"
    numero_dps: Optional[int] = None
    data_competencia: Optional[str] = None
    incluir_ibscbs: bool = True
    chave_nfse_substituta_evento: Optional[str] = Field(
        None,
        description="Se informado, gera também o XML do evento e105102 (Cancelamento por Substituição)",
    )
    certificado_pfx_b64: Optional[str] = None
    senha_certificado: Optional[str] = None
    transmitir: bool = True

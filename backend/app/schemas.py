from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Literal
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
    ultimo_nsu_adn: Optional[int] = 0
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[int] = 1
    enviar_email_automatico: Optional[int] = 0


class ClientCreate(ClientBase):
    password: str
    cert_password: Optional[str] = None
    smtp_password: Optional[str] = None


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
    ultimo_nsu_adn: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[int] = None
    enviar_email_automatico: Optional[int] = None


class ClientResponse(ClientBase):
    id: int
    cert_valid_until: Optional[datetime] = None
    cert_subject: Optional[str] = None
    dias_para_vencer: Optional[int] = None
    status_certificado: Optional[str] = None
    smtp_configurado: bool = False
    model_config = ConfigDict(from_attributes=True)


class UserClientLinkSchema(BaseModel):
    client_id: int
    access_level: Literal["manager", "operator"] = "operator"
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: str = Field(..., min_length=4)
    role: Literal["admin", "operador"] = "operador"
    client_ids: Optional[List[int]] = None
    client_links: Optional[List[UserClientLinkSchema]] = None


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[Literal["admin", "operador"]] = None
    is_active: Optional[int] = Field(None, ge=0, le=1)
    password: Optional[str] = Field(None, min_length=4)
    client_ids: Optional[List[int]] = None
    client_links: Optional[List[UserClientLinkSchema]] = None


class UserRegister(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: int
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    client_ids: List[int] = Field(default_factory=list)
    client_links: List[UserClientLinkSchema] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CustomerBase(BaseModel):
    client_id: Optional[int] = None
    documento: str
    razao_social: str
    inscricao_municipal: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    codigo_municipio: Optional[str] = "3201308"
    uf: Optional[str] = "ES"


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    client_id: Optional[int] = None
    documento: Optional[str] = None
    razao_social: Optional[str] = None
    inscricao_municipal: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    codigo_municipio: Optional[str] = None
    uf: Optional[str] = None


class CustomerResponse(CustomerBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ServiceItemBase(BaseModel):
    client_id: Optional[int] = None
    codigo_interno: Optional[str] = None
    titulo: str
    descricao: str
    valor_unitario: Optional[float] = 0.0
    c_trib_nac: Optional[str] = "010101"
    c_nbs: Optional[str] = None
    c_class_trib: Optional[str] = "000001"
    cst_ibscbs: Optional[str] = "000"
    c_ind_op: Optional[str] = "100301"
    aliquota_iss: Optional[float] = 2.0
    iss_retido: Optional[bool] = False
    reter_federais: Optional[bool] = False


class ServiceItemCreate(ServiceItemBase):
    pass


class ServiceItemUpdate(BaseModel):
    client_id: Optional[int] = None
    codigo_interno: Optional[str] = None
    titulo: Optional[str] = None
    descricao: Optional[str] = None
    valor_unitario: Optional[float] = None
    c_trib_nac: Optional[str] = None
    c_nbs: Optional[str] = None
    c_class_trib: Optional[str] = None
    cst_ibscbs: Optional[str] = None
    c_ind_op: Optional[str] = None
    aliquota_iss: Optional[float] = None
    iss_retido: Optional[bool] = None
    reter_federais: Optional[bool] = None


class ServiceItemResponse(ServiceItemBase):
    id: int
    avisos_fiscais: List[Dict[str, str]] = Field(default_factory=list)
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
    tomador_documento: Optional[str] = None
    tomador_nome: Optional[str] = None
    tomador_email: Optional[str] = None
    tentativas_envio: Optional[int] = 0
    ultimo_erro_envio: Optional[str] = None


class InvoiceResponse(InvoiceBase):
    id: int
    client_id: int | None = None
    xml_path: Optional[str] = None
    pdf_path: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None
    ambiente: Optional[str] = None
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


class HtmlToXmlRequest(BaseModel):
    html_content: Optional[str] = Field(None, description="Conteúdo HTML da página de impressão da NFS-e")
    html_path: Optional[str] = Field(None, description="Caminho do arquivo .html já baixado no servidor")
    xml_output_path: Optional[str] = Field(None, description="Caminho opcional de saída para o arquivo .xml")
    invoice_id: Optional[int] = Field(None, description="ID opcional da nota no banco para atualizar xml_path")


class XmlToPdfRequest(BaseModel):
    xml_content: Optional[str] = Field(None, description="Conteúdo XML da NFS-e gerado para conversão em PDF")
    xml_path: Optional[str] = Field(None, description="Caminho do arquivo .xml no servidor")
    pdf_output_path: Optional[str] = Field(None, description="Caminho opcional de saída para o arquivo .pdf")
    invoice_id: Optional[int] = Field(None, description="ID opcional da nota no banco para atualizar pdf_path")
    status: Optional[str] = Field("NORMAL", description="Status da nota para marca d'água (NORMAL, CANCELADA, etc.)")


class DashboardStats(BaseModel):
    total_notas: int
    total_emitidas: int
    total_recebidas: int
    total_clientes: int
    downloads_pendentes: int
    valor_total: float
    valor_emitidas: float
    valor_recebidas: float
    certificados_expirando: int = 0
    certificados_vencidos: int = 0


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
    customer_id: Optional[int] = Field(
        None, description="ID do Tomador recorrente cadastrado no banco (preenche tomador automaticamente)"
    )
    service_item_id: Optional[int] = Field(
        None, description="ID do Serviço recorrente cadastrado no banco (preenche servico automaticamente)"
    )
    ambiente: str = Field("homologacao", description="homologacao | producao")
    prestador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    tomador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    intermediario: Optional[Dict[str, Any]] = None
    servico: Dict[str, Any] = Field(default_factory=dict)
    tributacao: Optional[Dict[str, Any]] = None
    substituicao: Optional[Dict[str, Any]] = None
    serie_dps: str = "900"
    numero_dps: Optional[int] = None
    data_competencia: Optional[str] = None
    incluir_ibscbs: bool = True
    certificado_pfx_b64: Optional[str] = None
    senha_certificado: Optional[str] = None
    transmitir: bool = True
    enviar_email: bool = False
    email_destinatario: Optional[str] = None


class EmitirDpsLoteItemRequest(BaseModel):
    customer_id: Optional[int] = None
    service_item_id: Optional[int] = None
    tomador: Optional[Dict[str, Any]] = Field(default_factory=dict)
    servico: Optional[Dict[str, Any]] = Field(default_factory=dict)
    tributacao: Optional[Dict[str, Any]] = None
    serie_dps: Optional[str] = None
    numero_dps: Optional[int] = None
    data_competencia: Optional[str] = None
    incluir_ibscbs: bool = True
    enviar_email: Optional[bool] = None
    email_destinatario: Optional[str] = None


class EmitirDpsLoteRequest(BaseModel):
    client_id: int = Field(..., description="ID do cliente prestador cadastrado no banco")
    ambiente: str = Field("homologacao", description="homologacao | producao")
    serie_dps: Optional[str] = None
    data_competencia: Optional[str] = None
    incluir_ibscbs: bool = True
    transmitir: bool = True
    enviar_email: bool = False
    itens: List[EmitirDpsLoteItemRequest] = Field(..., min_length=1, max_length=200)


class ReenviarFilaRequest(BaseModel):
    client_id: Optional[int] = Field(None, description="Filtrar reenvio apenas para as notas deste cliente")
    invoice_ids: Optional[List[int]] = Field(None, description="Lista específica de IDs de notas na fila para reenviar")


class EnviarEmailNfseRequest(BaseModel):
    destinatario: Optional[str] = Field(None, description="E-mail do destinatário (usa o e-mail do tomador se omitido)")
    assunto: Optional[str] = Field(None, description="Assunto personalizado do e-mail")
    mensagem: Optional[str] = Field(None, description="Mensagem adicional no corpo do e-mail")


class SincronizarCofreAdnRequest(BaseModel):
    client_id: int = Field(..., description="ID do cliente (prestador/tomador) com Certificado A1 configurado")
    ultimo_nsu: Optional[int] = Field(None, description="NSU inicial (se omitido, usa ultimo_nsu_adn salvo no cliente)")
    max_paginas: int = Field(5, ge=1, le=50, description="Máximo de lotes de NSU a consultar por chamada")


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


# ==============================================================================
# Schemas do Módulo Persistente de Importação e Emissão em Lote (Planilhas)
# ==============================================================================


class BatchItemValidationError(BaseModel):
    field: str
    level: str = "estrutural"  # estrutural | cadastral | fiscal
    message: str


class BatchImportItemUpdateRequest(BaseModel):
    documento_tomador: Optional[str] = None
    nome_tomador: Optional[str] = None
    email_tomador: Optional[str] = None
    cep_tomador: Optional[str] = None
    logradouro_tomador: Optional[str] = None
    numero_tomador: Optional[str] = None
    bairro_tomador: Optional[str] = None
    municipio_tomador: Optional[str] = None
    codigo_servico: Optional[str] = None
    c_trib_nac: Optional[str] = None
    c_nbs: Optional[str] = None
    descricao_servico: Optional[str] = None
    discriminacao: Optional[str] = None
    valor_servico: Optional[float] = None
    valor_deducao: Optional[float] = None
    valor_desconto: Optional[float] = None
    aliquota_iss: Optional[float] = None
    iss_retido: Optional[bool] = None
    reter_federais: Optional[bool] = None
    municipio_prestacao: Optional[str] = None
    competencia: Optional[str] = None
    cst_ibs_cbs: Optional[str] = None
    cclasstrib: Optional[str] = None
    indop: Optional[str] = None


class BatchImportItemResponse(BaseModel):
    id: str
    batch_id: str
    row_number: int
    status: str
    payload: Dict[str, Any]
    validation_errors: List[BatchItemValidationError] = Field(default_factory=list)
    invoice_id: Optional[int] = None
    id_dps: Optional[str] = None
    serie_dps: Optional[str] = None
    numero_dps: Optional[int] = None
    chave_acesso: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    processed_at: Optional[datetime] = None


class BatchImportResponse(BaseModel):
    id: str
    client_id: int
    prestador_nome: Optional[str] = None
    filename: str
    file_hash: str
    ambiente: str
    status: str
    total_items: int
    valid_items: int
    invalid_items: int
    processed_items: int
    authorized_items: int
    rejected_items: int
    unknown_items: int
    created_by: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class BatchProcessRequest(BaseModel):
    item_ids: Optional[List[str]] = Field(None, description="Se omitido, processa todos os itens válidos elegíveis")
    transmitir: bool = Field(True, description="Transmitir via mTLS ao ADN (False permite validação/assinatura local)")
    enviar_email: bool = False


class BatchRetryRequest(BaseModel):
    item_ids: Optional[List[str]] = Field(None, description="Itens específicos para reprocessar/consultar")
    transmitir: bool = True
    enviar_email: bool = False


class BatchItemsDeleteRequest(BaseModel):
    item_ids: Optional[List[str]] = Field(None, description="IDs específicos de itens para excluir")
    delete_all: bool = Field(False, description="Se true, exclui todos os itens removíveis do lote")


class RegistryBatchDeleteRequest(BaseModel):
    ids: Optional[List[int]] = Field(None, description="IDs específicos para excluir")
    client_id: Optional[int] = Field(None, description="Filtrar exclusão em massa pelo cliente quando delete_all=true")
    delete_all: bool = Field(False, description="Se true, exclui todos os registros filtrados")


class AuditLogItemResponse(BaseModel):
    id: int
    created_at: datetime
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    client_cnpj: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    summary: str
    details: Optional[Dict[str, Any]] = None
    status: str = "success"
    ip_address: Optional[str] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItemResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25
    facets: Dict[str, List[str]] = Field(default_factory=dict)

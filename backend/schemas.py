from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ClientBase(BaseModel):
    cnpj: str
    razao_social: str
    username: str
    description: Optional[str] = None
    cert_path: Optional[str] = None
    save_path: Optional[str] = None
    path_structure: Optional[str] = None


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


class ClientResponse(ClientBase):
    id: int

    class Config:
        from_attributes = True


class NoteBase(BaseModel):
    numero: str
    chave: str
    status: str
    tipo: str
    valor: Optional[float] = None
    data_emissao: datetime
    download_url_xml: Optional[str] = None
    download_url_pdf: Optional[str] = None


class NoteResponse(NoteBase):
    id: int
    client_id: int | None = None
    xml_path: Optional[str] = None
    pdf_path: Optional[str] = None

    class Config:
        from_attributes = True


class SyncRequest(BaseModel):
    client_id: Optional[int] = None
    data_inicio: str  # DD/MM/AAAA
    data_fim: str  # DD/MM/AAAA
    tipo: str  # emitidas or recebidas


class DownloadRequest(BaseModel):
    client_id: int
    note_ids: List[int]
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

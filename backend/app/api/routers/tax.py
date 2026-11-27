"""Router Tributário - Cálculo e validação de ISSQN, Retenções Federais e IBS/CBS (NT 1.101 / v1.01).

Delega ao `AdnService` (que utiliza o motor tributário de `pynfse.adn`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routers.auth import get_current_user
from app.schemas import SimplesNacionalTaxRequest, TaxCalculationRequest, TaxValidationRequest
from app.services.adn_service import AdnService

router = APIRouter(prefix="/api/tax", tags=["tax", "ibscbs"], dependencies=[Depends(get_current_user)])


@router.post("/calculate")
def calculate_taxes(req: TaxCalculationRequest):
    """Calcula ISSQN, Retenções Federais (PIS, COFINS, IRRF, CSLL, INSS) e IBS/CBS conforme regras da NT 1.101."""
    return AdnService.calcular_tributos(req)


@router.post("/calculate-simples")
def calculate_simples_nacional_taxes(req: SimplesNacionalTaxRequest):
    """Calcula o grupo gTribSN (IBS/CBS por dentro do Simples Nacional na NFS-e — NT 2026.005 / NT 009)."""
    return AdnService.calcular_simples_nacional(req)


@router.post("/validate-ibscbs")
def validate_ibscbs_rules(req: TaxValidationRequest):
    """Valida as regras de negócio de IBS/CBS (CST x cClassTrib x cNBS, cIndOp, gTribRegular, gDif, etc.)."""
    return AdnService.validar_ibscbs(req)

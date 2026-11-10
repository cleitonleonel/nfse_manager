"""Router Tributário - Cálculo e validação de ISSQN, Retenções Federais e IBS/CBS (NT 1.101 / v1.01).

Delega ao `AdnService` (que utiliza o motor tributário de `pynfse.adn`).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import TaxCalculationRequest, TaxValidationRequest
from app.services.adn_service import AdnService

router = APIRouter(prefix="/api/tax", tags=["tax", "ibscbs"])


@router.post("/calculate")
def calculate_taxes(req: TaxCalculationRequest):
    """Calcula ISSQN, Retenções Federais (PIS, COFINS, IRRF, CSLL, INSS) e IBS/CBS conforme regras da NT 1.101."""
    return AdnService.calcular_tributos(req)


@router.post("/validate-ibscbs")
def validate_ibscbs_rules(req: TaxValidationRequest):
    """Valida as regras de negócio de IBS/CBS (CST x cClassTrib, cIndOp, gTribRegular, gDif, etc.)."""
    return AdnService.validar_ibscbs(req)

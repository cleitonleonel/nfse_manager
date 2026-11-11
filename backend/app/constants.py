"""Constantes globais da aplicação NFSe Manager."""

from typing import Dict

# Padrões fiscais e municipais
DEFAULT_CODIGO_MUNICIPIO = "3201308"
DEFAULT_UF = "ES"
DEFAULT_SERIE_DPS = "900"
DEFAULT_AMBIENTE = "homologacao"
DEFAULT_REGIME_TRIBUTARIO = "normal"
DEFAULT_REGIME_APURACAO_SN = "1"
DEFAULT_REGIME_ESPECIAL = "0"

# Períodos de tempo para relatórios e analytics
PERIOD_DAYS_MAP: Dict[str, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "12m": 365,
}
DEFAULT_PERIOD = "30d"

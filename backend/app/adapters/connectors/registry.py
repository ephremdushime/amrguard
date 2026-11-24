"""Modular EMR Connector Registry and Factory.

Allows dynamic plug-and-play registration of external hospital and national EMR connectors.
"""

from typing import Type

from app.adapters.connectors.base import BaseEMRConnector
from app.adapters.connectors.ebuzima import EBuzimaConnector
from app.adapters.connectors.openmrs import OpenMRSConnector

_CONNECTOR_REGISTRY: dict[str, Type[BaseEMRConnector]] = {
    'EBUZIMA': EBuzimaConnector,
    'EBUZIMA_CANONICAL': EBuzimaConnector,
    'OPENMRS': OpenMRSConnector,
    'OPENMRS_FHIR_V1': OpenMRSConnector,
}


def get_connector(system_or_code: str) -> BaseEMRConnector:
    """Instantiates a registered connector by system type or connector code."""
    key = system_or_code.upper()
    cls = _CONNECTOR_REGISTRY.get(key)
    if not cls:
        raise ValueError(f"No EMR connector registered for '{system_or_code}'. Available: {list(_CONNECTOR_REGISTRY.keys())}")
    return cls()


def list_registered_connectors() -> list[dict[str, str]]:
    """Returns metadata for all available EMR connectors."""
    connectors = [EBuzimaConnector(), OpenMRSConnector()]
    return [
        {
            'connector_code': c.connector_code,
            'name': c.name,
            'system_type': c.system_type,
        }
        for c in connectors
    ]

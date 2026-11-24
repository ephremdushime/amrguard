"""Modular EMR Connector Framework Base Interface.

Defines the pluggable connector contract for external hospital, district,
and national EMR systems (e.g. e-Buzima, OpenMRS, DHIS2 Tracker, Generic FHIR R4).
"""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session

from app.models.core import DispensingTransaction, Prescription
from app.schemas.prescriptions import PrescriptionIn


class BaseEMRConnector(ABC):
    """Abstract Base Class for institutional and national EMR adapters."""

    connector_code: str
    name: str
    system_type: str  # EBUZIMA, OPENMRS, DHIS2, FHIR_R4

    @abstractmethod
    def parse_inbound_prescription(
        self,
        raw_payload: dict[str, Any],
        db: Session,
    ) -> tuple[PrescriptionIn, list[dict[str, Any]]]:
        """Parses vendor-specific or FHIR prescription payload into canonical PrescriptionIn schema."""
        pass

    @abstractmethod
    def format_outbound_reconciliation(
        self,
        prescription: Prescription,
        transaction: DispensingTransaction,
        db: Session,
    ) -> dict[str, Any]:
        """Formats canonical dispensing reconciliation event for transmission to partner EMR."""
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Verifies connector availability and cryptographic readiness."""
        pass

"""e-Buzima Modular EMR Connector Implementation."""

from typing import Any
from sqlalchemy.orm import Session

from app.adapters.connectors.base import BaseEMRConnector
from app.adapters.ebuzima import EBuzimaAdapter
from app.models.core import DispensingTransaction, Prescription
from app.schemas.prescriptions import PrescriptionIn


class EBuzimaConnector(BaseEMRConnector):
    connector_code = 'EBUZIMA_CANONICAL_V1'
    name = 'e-Buzima National EMR Adapter'
    system_type = 'EBUZIMA'

    def __init__(self, transport_client=None):
        self._adapter = EBuzimaAdapter()
        self.transport_client = transport_client

    def parse_inbound_prescription(
        self,
        raw_payload: dict[str, Any],
        db: Session,
    ) -> tuple[PrescriptionIn, list[dict[str, Any]]]:
        rx_in, ingest_result = self._adapter.parse_prescription(raw_payload, db)
        warnings = getattr(ingest_result, 'warnings', [])
        return rx_in, warnings

    def format_outbound_reconciliation(
        self,
        prescription: Prescription,
        transaction: DispensingTransaction,
        db: Session,
    ) -> dict[str, Any]:
        return self._adapter.format_reconciliation_payload(prescription, transaction, db)

    def health_check(self) -> dict[str, Any]:
        return {
            'connector_code': self.connector_code,
            'name': self.name,
            'system_type': self.system_type,
            'status': 'HEALTHY',
            'supported_formats': ['JSON_PROPRIETARY_V1', 'FHIR_R4_BUNDLE'],
        }

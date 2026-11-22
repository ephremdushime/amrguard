"""AMRGuard canonical partner integration adapters package.

Defines isolated, contract-tested adapters for external health and supply-chain systems:
- ebuzima: e-Buzima EMR prescription intake, code resolution, and dispense status callbacks
- rms: RMS / eLMIS supply chain stock movements, batch tracking, and dispense stock consumption
- outbox_worker: Transactional outbox background processor with backoff retry and dead-letter handling
"""

from app.adapters.base import (
    AdapterDispatchResult,
    AdapterIngestResult,
    PartnerAdapter,
    PartnerContractError,
    PartnerReplayConflictError,
    PartnerTransportClient,
    PartnerTransportError,
    UnmappedCodeError,
)
from app.adapters.ebuzima import EBuzimaAdapter, MockEBuzimaTransportClient
from app.adapters.outbox_worker import process_integration_outbox_batch, retry_dead_letter
from app.adapters.rms import MockRMSTransportClient, RMSAdapter

__all__ = [
    'AdapterDispatchResult',
    'AdapterIngestResult',
    'EBuzimaAdapter',
    'MockEBuzimaTransportClient',
    'MockRMSTransportClient',
    'PartnerAdapter',
    'PartnerContractError',
    'PartnerReplayConflictError',
    'PartnerTransportClient',
    'PartnerTransportError',
    'RMSAdapter',
    'UnmappedCodeError',
    'process_integration_outbox_batch',
    'retry_dead_letter',
]

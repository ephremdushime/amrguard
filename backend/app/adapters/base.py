"""Base classes, interfaces, and utilities for AMRGuard partner adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any


class PartnerContractError(Exception):
    """Raised when an external partner payload violates the canonical contract."""


class UnmappedCodeError(PartnerContractError):
    """Raised when an inbound code (facility, medication, pharmacy) cannot be mapped."""

    def __init__(self, code: str, domain: str, source_system: str, details: str = ''):
        self.code = code
        self.domain = domain
        self.source_system = source_system
        self.details = details
        msg = f'Unmapped {domain} code "{code}" from {source_system}'
        if details:
            msg += f': {details}'
        super().__init__(msg)


class PartnerReplayConflictError(PartnerContractError):
    """Raised when an idempotent source reference is replayed with contradictory content."""


class PartnerTransportError(Exception):
    """Raised when communication with an external partner gateway fails."""

    def __init__(self, message: str, status_code: int | None = None, is_retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.is_retryable = is_retryable


@dataclass
class AdapterIngestResult:
    """Canonical envelope returned by an adapter when parsing an inbound payload."""

    source_system: str
    event_type: str
    external_id: str
    payload_hash: str
    canonical_data: Any
    raw_payload: dict[str, Any]
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AdapterDispatchResult:
    """Envelope returned when an adapter dispatches an outbox event to a partner."""

    destination_system: str
    event_type: str
    aggregate_id: str
    external_reference: str | None
    status: str  # DISPATCHED, FAILED
    status_code: int = 200
    response_body: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


def calculate_payload_hash(payload: str | bytes | dict[str, Any]) -> str:
    """Calculate a deterministic SHA-256 hash of a payload for idempotency checking."""
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    elif isinstance(payload, str):
        raw = payload.encode('utf-8')
    else:
        raw = payload
    return hashlib.sha256(raw).hexdigest()


def verify_partner_signature(secret: str, payload_bytes: bytes, signature_header: str) -> bool:
    """Verify an HMAC-SHA256 signature from a partner intake request."""
    if not secret or not signature_header:
        return False
    computed = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    # Support both raw hex or sha256=prefix
    sig = signature_header.strip()
    if sig.startswith('sha256='):
        sig = sig[7:]
    return hmac.compare_digest(computed.lower(), sig.lower())


class PartnerAdapter(ABC):
    """Abstract base class for partner integration adapters."""

    @property
    @abstractmethod
    def system_name(self) -> str:
        """Partner system name (e.g. 'e-Buzima', 'RMS')."""
        ...


class PartnerTransportClient(ABC):
    """Abstract base transport client for communicating with external partner endpoints."""

    @abstractmethod
    def send(self, endpoint: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> AdapterDispatchResult:
        """Deliver a payload to an external partner HTTP gateway."""
        ...

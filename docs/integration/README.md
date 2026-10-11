# AMRGuard Integration Contract

AMRGuard is API-first and adapter-based. External systems are not hard-coded into the core transaction engine.

## Integration boundaries

### e-Buzima / clinical source
**Inbound:** authenticated antibiotic prescription, prescriber provenance, facility provenance, patient reference, regimen and expiry/status metadata.

**Outbound:** AMRGuard validation/status and dispensing-event references where an approved callback contract exists.

### RMS/eLMIS / supply chain
**Inbound:** approved stock and movement events, product/batch identifiers, expiry and location information.

AMRGuard does not become the authoritative national supply-chain inventory.

### Pharmacy systems
**Inbound/outbound:** pharmacy identity, stock/batch events, verification and dispensing transactions. A pharmacy without an integration can use the AMRGuard portal.

### Insurance/billing
AMRGuard stores an optional payment/claim reference only. Billing and claims remain authoritative in the existing system.

## Idempotency
External systems should send a stable external event or prescription identifier. AMRGuard must safely replay duplicate messages without creating duplicate clinical or dispensing transactions.

## FHIR direction
AMRGuard contains internal mappings for `MedicationRequest` and `MedicationDispense`. These are compatibility mappings, not a declaration of the final national FHIR profile. Final profiles, code systems, identifiers and security mechanisms must be agreed with the system owner.

## Production integration checklist

1. Obtain approved API specification and test environment.
2. Agree identifiers and terminology.
3. Configure service-to-service authentication.
4. Map external payloads to AMRGuard canonical contracts.
5. Configure retry/idempotency semantics.
6. Test failure, timeout and duplicate-event handling.
7. Validate privacy/security controls.
8. Run end-to-end UAT with the integration owner.
9. Obtain deployment/governance approval.

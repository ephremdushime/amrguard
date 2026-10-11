# AMRGuard integration adapters

AMRGuard uses adapters so the core transaction engine does not need to be rewritten when an external system is connected.

```text
External system -> adapter -> AMRGuard canonical contract -> core services
```

## Planned adapters

- `ebuzima/` — prescription and status integration
- `rms/` — supply-chain and stock/movement events
- `pharmacy/` — pharmacy inventory, verification and dispensing
- `insurance/` — optional claim/payment reference linkage

No endpoint names in this repository should be interpreted as current government API contracts. Actual integration must use the approved specifications, credentials, sandbox and governance process supplied by the system owner.

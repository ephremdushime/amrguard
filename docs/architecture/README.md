# AMRGuard architecture

AMRGuard is an antibiotic-specific interoperability and transaction layer. It does not replace the EMR, supply-chain system, pharmacy POS, insurer or national AMR surveillance platform.

Core flow:
`e-Buzima -> adapter -> prescription validation -> QR/OTP -> pharmacy verification -> stock/batch -> dispensing -> traceability -> analytics`

External integration is implemented through adapters so the core remains stable when an approved API specification becomes available.

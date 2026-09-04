# Plan: Scaffold iOS client consuming the /api/v1 contract

- [x] Extract live /api/v1 field shapes (status, memory, twin, shadow, decision, ledger)
- [x] Scaffold Swift Package skeleton (ios/): Package.swift, APIClient/transport, Codable models mirroring the contract — Scaffolding the Swift Package skeleton mirroring the /api/v1 contract — iOS skeleton scaffolded — Package.swift + Models + APIClient + facade, all balanced
- [x] Add the same epistemic/authority discipline + governance-bound commands (no execute) — Cross-check caught AuthorityBoundary key mismatch — correcting the Swift model to the live contract keys — iOS Codable models cross-checked and corrected against live contract; guard test passes (19/19)
- [~] Verify Swift files are well-formed (syntax check via a parser where possible); run suite; commit + push — Running the full suite set, then committing and pushing the iOS skeleton

# Crypto Payment Monitor — implementation plan and operational controls

## Scope
Read-only, non-custodial payment observation for ETH, BTC and stablecoins. No wallet generation, private-key handling, signing, spending, or custody.

## MVP design
- **Bitcoin:** Esplora-compatible API adapter; poll address transaction history and validate output address/amount; confirmation count derived from block height.
- **EVM:** RPC adapter with chain ID validation and ERC-20 Transfer event parsing; explicit token contract allowlist and recipient address filter.
- **Event ledger:** stable event key (chain + tx hash + log index / output index); idempotent processing; immutable observed events and status transitions.
- **Settlement policy:** operator-configured confirmations per chain/token; never mark paid solely from mempool/receipt inclusion. Reorgs may demote events.
- **Evidence:** retain chain, asset identifier (contract/mint), tx hash, recipient, amount in integer base units, block height/hash, timestamp observed, and status.

## Initial chain coverage
- Ethereum Mainnet: native ETH and ERC-20 (USDC/USDT only when operator explicitly supplies verified contract addresses).
- Bitcoin mainnet: BTC.
- Expansion candidates: Base, Arbitrum, Polygon and Solana, after adapter-specific tests and token identity verification.

## Safety requirements
1. No keys, seed phrases, signing, or custody.
2. Provider URL allowlisting; secrets via environment/secret manager only.
3. Reject unknown chain IDs and unknown token contracts.
4. Integer-only amounts; no floating-point arithmetic for money.
5. Idempotency and replay protection.
6. Reorg-aware status machine: observed → confirming → confirmed; confirmed may be invalidated on reorg and reconciliation must be recorded.
7. Health stability window and provider error/lag alerts.
8. Audit event lifecycle: monitor.start/stop, event.observed, event.confirmation_update, event.reorg.
9. Privacy: address metadata minimized; avoid exposing customer identifiers in logs.

## Readiness gates (not yet satisfied)
- Unit tests and adapter integration tests pass.
- Live provider behavior validated against known transaction fixtures.
- Token contract addresses checked against authoritative issuer documentation and on-chain code.
- Confirmation and reorg simulations pass.
- Provider allowlist and rate-limit handling implemented.
- Monitoring, alerting, uptime/lag SLI, and recovery procedure validated.
- Deployment target and secrets configured; deployment health stable for a defined observation window.

## Current status
Scaffold only. No RPC provider or explorer endpoint configured; no live transaction polling or payment settlement has been enabled. Do not use as proof of paid orders yet.

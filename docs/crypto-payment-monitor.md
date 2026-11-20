# Crypto Payment Monitor — controls and readiness

## Scope
Read-only observer for BTC mainnet and Ethereum mainnet (chain ID is configurable). No keys, signing, custody, or transaction submission.

## Implemented in this PR
- HTTPS provider endpoint validation and endpoint credentials rejection.
- JSON-RPC chain-ID verification and bounded response reads.
- EVM initial window scanning with chunked RPC calls and a durable block cursor.
- Native ETH scanning checks transaction receipt status.
- ERC-20 Transfer event filtering by explicitly configured contract and watched recipient.
- Esplora BTC address-history pagination and confirmation counts from tip height.
- JSONL append ledger with event ID deduplication and durable writes.
- Unit tests and CI.

## Remaining GO gates
- EVM reorg detection and cursor rollback; confirmation-state reconciliation.
- BTC reorg detection and persisted confirmation transitions.
- Checkpoint recovery/backfill semantics verified, including cursor corruption handling.
- Verified token contract registry/validation for USDC and USDT.
- RPC log range/response validation, hostname allowlist, provider rate limits, retry/backoff, and failover.
- Multi-provider validation of blocks, receipts, and logs.
- CI passing, integration tests and simulated reorg tests.
- Live data run and independent explorer confirmation of transaction hash(es).
- SLI/health monitoring, alerts, deployment and stable observation window.

## Evidence policy
A scan result is an observation, not proof of settlement. Evidence must contain chain, transaction hash, block height/hash, token contract (where applicable), address, base-unit amount, timestamp, and independently checked status. GO remains blocked until gates above are satisfied.

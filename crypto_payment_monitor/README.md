# Non-custodial Crypto Payment Monitor

Read-only observer for configured Bitcoin and Ethereum addresses. It never stores keys, signs, broadcasts, or holds funds.

## Run
Configure HTTPS provider endpoints and watchlists, then run:

```bash
python -m crypto_payment_monitor --ledger ./events.jsonl
```

Variables: `ETHEREUM_RPC_URL`, `ETHEREUM_CHAIN_ID` (default 1), `BITCOIN_ESPLORA_URL`, `BTC_WATCH_ADDRESSES`, `EVM_WATCH_ADDRESSES`, `ERC20_TOKEN_CONTRACTS` (comma-separated `SYMBOL=contract`), `EVM_SCAN_CHUNK` (1..1000, default 100), `EVM_SCAN_BLOCKS` (initial bootstrap window, default 500), `CONFIRMATIONS_ETH`, `CONFIRMATIONS_BTC`.

## Implemented
- HTTPS-only endpoint validation (no embedded endpoint credentials).
- EVM chain-ID check and bounded JSON-RPC response reads.
- EVM recent-window bootstrap and persisted block cursor; EVM requests are chunked.
- Native ETH transaction/receipt checks and ERC-20 Transfer log filtering.
- Esplora address history pagination and tip-height-based BTC confirmation count.
- Append-only JSONL ledger, stable event IDs, duplicate prevention and state file.
- Unit tests and CI workflow.

## Known readiness gaps
This is not a payment settlement service and **not GO**. Remaining gaps include complete reorg/reconciliation handling (including EVM cursor rollback and Bitcoin event demotion), cursor backfill/recovery and provider failover/rate limiting, strict token-contract verification against authoritative chain/issuer data, receipt and block consistency checks across provider responses, hardened hostname allowlisting, multi-provider quorum, continuous polling/health telemetry, operational alerting, production persistence/locking, and a live test run with independently verified transaction hashes. The single-shot CLI does not currently operate as a continuous monitor. Do not rely on its observations to release goods or accept payments.

Token symbols are operator labels only; contract addresses must be verified for the chain before use.

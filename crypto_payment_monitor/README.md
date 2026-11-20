# Non-custodial Crypto Payment Monitor

Read-only observer. It never stores private keys, signs, submits transactions, or holds funds.

## Run
Set HTTPS provider URLs and watchlists via environment variables, then:

```bash
python -m crypto_payment_monitor --ledger ./events.jsonl
```

Environment variables: `ETHEREUM_RPC_URL`, `ETHEREUM_CHAIN_ID` (default 1), `BITCOIN_ESPLORA_URL`, `BTC_WATCH_ADDRESSES` (comma-separated), `EVM_WATCH_ADDRESSES` (comma-separated), `ERC20_TOKEN_CONTRACTS` (comma-separated SYMBOL=contract pairs), `EVM_SCAN_BLOCKS` (default 500), `POLL_INTERVAL_SECONDS`, confirmation settings.

**MVP limitations:** single-shot scans; recent bounded EVM window; BTC adapter fetches transaction history; no pagination beyond Esplora's initial address tx endpoint, no robust reconciliation/reorg state machine, no settlement-grade confirmation policy, no provider allowlisting, and no production database. Events are observations only. This is not yet a payment acceptance/settlement system.

Only configure contract addresses verified independently for the intended chain. Symbols alone do not establish token identity.

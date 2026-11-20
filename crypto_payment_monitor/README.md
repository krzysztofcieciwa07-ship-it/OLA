# Non-custodial Crypto Payment Monitor (MVP)

Read-only monitoring service for customer-owned receiving addresses. It does not custody assets, sign transactions, create wallets, or store private keys.

## Supported sources (initial adapter scaffold)
- Ethereum / EVM: JSON-RPC, configurable chain IDs and ERC-20 contract allowlist.
- Bitcoin: Esplora-compatible REST API.

**Important:** This initial scaffold is not a production payment processor. It needs provider configuration, confirmation policy, address/contract allowlists, integration tests against live providers, and operational deployment before accepting payments as settled.

## Security boundaries
- No private keys, seed phrases, signing, withdrawals, or transaction construction.
- Token contract allowlists are explicit; symbol/name are never trusted.
- Monitor only addresses configured by the operator.
- RPC/API URLs must be explicitly configured; no user-controlled arbitrary URLs.
- Pending/observed events are not payment confirmations.

See ../docs/crypto-payment-monitor.md for architecture and rollout gates.

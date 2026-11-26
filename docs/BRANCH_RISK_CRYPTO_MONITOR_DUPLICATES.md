# Branch Risk Report: crypto-monitor duplicate group

## Branches
- `fix/crypto-monitor-canonical-reconciliation`
- `fix/crypto-monitor-e2e-hardening`
- `feat/noncustodial-crypto-payment-monitor`

All three recorded branch tips resolve to:
`42ba5be3924d7901099e899790e13afbcfbca155`.

## Pull-request dependency
- No PR was found for `fix/crypto-monitor-canonical-reconciliation`.
- No PR was found for `fix/crypto-monitor-e2e-hardening`.
- `feat/noncustodial-crypto-payment-monitor` is associated with closed draft PR #265, `Scaffold non-custodial crypto payment monitor`.

## Reachability
Default-branch commit search did not return commit `42ba5be3924d7901099e899790e13afbcfbca155`.
Assessment: `NOT PROVEN REACHABLE FROM CURRENT MAIN`.

## Unique content
The tip commit changes only `crypto_payment_monitor/tests/test_monitor.py` (3 additions, 1 deletion), but the branch tree contains the `crypto_payment_monitor/` package including README, CLI, Bitcoin/EVM/config/monitor modules and tests.

Current `main` does not contain `crypto_payment_monitor/tests/test_monitor.py` at that path.
Assessment: `UNIQUE BRANCH MATERIAL EXISTS / SALVAGE REQUIRED BEFORE DELETION`.

## Risk
- Code-loss risk: HIGH until the whole branch ancestry is reconciled.
- Test-loss risk: HIGH; current `main` does not contain the assessed test path.
- PR/reference risk: MEDIUM; one branch name is tied to closed PR #265.
- Security risk: REVIEW; non-custodial payment code requires explicit assessment before any salvage decision.
- Migration risk: not established by this tip assessment.
- CI/workflow risk: not established by this tip assessment.

## Disposition
- `feat/noncustodial-crypto-payment-monitor`: `SALVAGE-FIRST / HOLD-DEPENDENCY-HISTORY`.
- `fix/crypto-monitor-canonical-reconciliation`: `SALVAGE-FIRST`.
- `fix/crypto-monitor-e2e-hardening`: `SALVAGE-FIRST`.

No branch in this group is approved for deletion yet.

Next requirement: analyze the branch ancestry and package contents against current product scope. Preserve only material that belongs to the existing product; do not add a new product/module merely because the branch contains one.

# Business invoice demo admission — production NO-GO

The `/business-invoice-run` route is a deterministic **test invoice** runtime,
not a bank transfer, payment authorization, accounting approval, or customer
delivery. It previously bypassed `/agent-run` admission. It now has an
independent deny-by-default `ExecutionSafetyGate` and a trusted, append-only
`execution.safety_gate` decision **before** any invoice runtime call.

## Safe default

- Without `OLA_BUSINESS_INVOICE_DEMO_ENABLED=1`, an authenticated call returns
  HTTP 403 and writes a `DENY` decision to the caller's tenant Evidence chain.
- Enabling it permits *only* the exact 5-field invoice schema, EUR, 21% VAT,
  finite net amount from 0 to 10,000 EUR with at most two decimals, and
  bounded identifiers. Everything else is classified HIGH and blocked.
- The caller's `risk`, `human_approved`, or other extra request fields never
  alter the server-side decision. There is no path for a buyer to self-approve.
- A missing/broken gate or missing Evidence write always blocks execution.
- Successful demo responses explicitly include `production_authorized=false`
  and `external_effects_executed=false`.

## Operator use

Only in an isolated, non-production demonstration with test-only API keys:

```powershell
$env:OLA_BUSINESS_INVOICE_DEMO_ENABLED = '1'
```

Unset the flag before any live deployment. Running the demo is not evidence
that payments, invoices, taxes, or external transfers were independently
verified. The internal test output `APPROVE_FOR_TEST_TRANSFER` does not
authorize any bank action. The actual upstream production gates remain
owner signature, independent IGOR/human review, source-bound CI, and
provider-backed payment/delivery reconciliation.

## Verification

`python -m pytest -q tests/test_business_invoice_admission.py`

The regression suite covers default deny, malformed/excessive amounts,
currency/VAT bypass, opt-in execution ordering, broken gate, and Evidence
failure. No live provider calls or transfers are performed by these tests.

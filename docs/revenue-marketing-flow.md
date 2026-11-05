# OLA Revenue + Marketing Flow

## Verified implementation scope

The repository contains a payment execution path:

MARKETING SURFACE → Stripe Checkout Session → signed `checkout.session.completed` webhook → payment validation → OLA execution → Evidence V2 records → session-bound result lookup.

The source implements:
- Checkout Session creation with offer, task and tenant metadata;
- Stripe webhook HMAC signature and timestamp verification;
- validation of the offer, paid status, EUR 99 amount and task;
- idempotency by Stripe event ID;
- payment and execution evidence appended to the tenant evidence chain;
- `/payment-success` lookup bound to the exact Checkout Session, so a result from another order is not returned.

**Implemented backend code is not the same as an available public checkout or a live payment proof.**

## Current verified state — 2026-11-05

Read-only inspection of the connected Stripe account `ola sandbox` (`livemode=false`) returned:
- Products: **0**;
- Prices: **0**;
- Payment Links: **0**;
- Checkout Sessions: **0**.

No Stripe LIVE account is available in the connected integration. These results describe only the connected sandbox account; they do not prove that no other account exists.

The advertised EUR 99 amount is a planned price, not a currently configured Stripe Price. No Payment Link, product, Price, Checkout Session or customer payment was created during this audit.

## Public customer path — not yet connected

- `POST /checkout` requires an existing tenant `X-API-Key`.
- The marketing page is a static HTML file; it does not collect a task, provision a customer tenant or call the authenticated `/checkout` API.
- There is no verified public customer-onboarding path from the landing page to the backend.
- The previous static Stripe TEST URL was not present among the connected account's Payment Links. It has been removed from the page.
- The page now labels runtime claims as CI-verified and shows a disabled checkout state. This is deliberate; it prevents visitors being sent to an unverified test URL.

The Revenue Surface Gate now fails if a Stripe Payment Link URL is reintroduced into the static page and checks that the disabled checkout state is visible. It is a static honesty guard, **not** a Stripe API availability test.

## Test scope and limits

- `tests/test_stripe_webhook.py` validates signature and payment fields with synthetic payloads and a test webhook secret.
- `tests/test_payment_session_binding.py` stubs Checkout Session retrieval to test order/result isolation; it does not execute a real Stripe request.
- Runtime and NINA/IGOR evidence is verified in isolated CI scope; it is not a real customer delivery.
- No production payment, real customer, first euro or public checkout completion is proven.

## Required next chain

1. Configure an authorized Stripe LIVE account.
2. Create and verify the OLA product and one-time EUR 99 Price.
3. Configure the LIVE API key and webhook secret in the authorized production environment.
4. Implement public task submission and tenant/customer provisioning without exposing API keys.
5. Connect the landing page to the authenticated backend checkout-bootstrap flow.
6. Verify signed LIVE webhook delivery, exact Price ID, paid status and idempotent processing.
7. Run OLA, independently verify evidence and provide the exact order-bound customer result.
8. Observe a real payment and customer delivery before marking revenue LIVE.

Never promote:
- sandbox configuration to live revenue;
- synthetic webhook fixtures to a live Stripe event;
- a hard-coded Payment Link URL to an active link without an account-side read;
- CI evidence to production evidence;
- a runtime proof to a customer-delivery claim.

Until the complete chain is observed end-to-end, status remains **LIVE_PAYMENT_NOT_PROVEN**.

# Razorpay test-mode setup (Phase 12)

Recoup runs fully in `mock` mode with no Razorpay account. To exercise the **live**
adapter and receive genuine signed webhooks, follow this once. Everything here is
**test mode** — no real money moves.

## 1. Keys

Razorpay Dashboard → **Settings → API Keys** → *Generate Test Key*. Copy into
`.env`:

```
RECOUP_MODE=live
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
```

`RECOUP_MODE=live` is what makes the composition root select `RazorpayGateway` over
the mock. With the mode left at `mock`, the keys are ignored.

## 2. Expose the local server

Razorpay must reach your webhook endpoint over HTTPS:

```
uv run uvicorn recoup.api.app:app --port 8000
ngrok http 8000
```

`ngrok` prints a public URL like `https://abcd-1234.ngrok-free.app`.

## 3. Register the webhook

Dashboard → **Settings → Webhooks → Add New Webhook**:

- **URL:** `https://<your-ngrok-id>.ngrok-free.app/webhooks/razorpay`
- **Secret:** any string you choose — copy the **same** value into
  `RAZORPAY_WEBHOOK_SECRET` in `.env`. This is the HMAC key the endpoint
  verifies every delivery against; an unsigned or wrong-secret delivery is rejected
  with `401` and nothing is written (PRD §14).
- **Active events:** `payment.failed`, `subscription.halted`, `invoice.expired`.

## 4. Trigger a genuine test-mode failure

Create a payment with a **failure test card** so a real `payment.failed` webhook
fires. Razorpay's documented test instruments include:

- **Card that fails:** `4111 1111 1111 1105` (any future expiry, any CVV) — declines.
- Or use the **Payment Links** flow: create a test payment link, open it, and pay
  with the failing card above.

Within a second or two Razorpay delivers a signed `payment.failed` to your endpoint.
Watch the dashboard (`npm run dev`) — the failed payment appears as
a work item, is diagnosed, gated, and its full audit trail is visible.

## 5. Confirm the path

- `GET /api/health` reports `"mode": "live"`.
- The webhook returns `202` for a new event, `200` for a duplicate, `401` for a bad
  signature (the body is discarded unparsed).
- The work item's `GET /api/workitems/{txn_id}/audit` shows the complete trail.

## Notes

- The adapter never imports a Razorpay SDK; it speaks the documented REST API over
  `httpx`, so timeouts and error codes are mapped explicitly (5xx → retryable,
  4xx → escalate, unknown id → typed not-found).
- Recovery is modelled as a re-collection **payment link** carrying the idempotency
  key — see the module docstring in `src/recoup/gateways/razorpay.py`. A
  failed payment cannot be re-charged directly in test mode; the link is how a
  merchant actually recovers the amount.
- **Tests always use the mock** — the live adapter is exercised by this manual flow
  and by the `httpx`-transport contract run, never by the automated suite hitting a
  real account.

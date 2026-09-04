# Voice recovery call setup (Phase 14)

The Hinglish hero call runs on Twilio. It is the demo's cut-line (PRD §9.7) and the
first thing to drop if anything upstream is unfinished — but when it works, a
high-value expired-mandate subscription gets a real phone call offering to text a
payment link. **Do the number verification the night before, not live** (PRD §13.3).

## 1. Credentials and a public URL

In `backend/.env`:

```
RECOUP_MODE=live
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...        # a Twilio number (trial gives one free)
PUBLIC_BASE_URL=https://<your-ngrok-id>.ngrok-free.app
```

- **A Twilio number is required for voice and SMS.** A trial account includes one
  free number under **Phone Numbers → Manage → Buy a number**. Without it, the voice
  channel is not built and nudges fall through to email.
- **`PUBLIC_BASE_URL`** is the ngrok URL Twilio uses to fetch the call's TwiML and
  post callbacks. Without it, voice is not built.

```
uv run uvicorn recoup.api.app:app --port 8000
ngrok http 8000
```

## 2. Verify the demo number (trial-account limitation)

A Twilio **trial** account can only call or text **verified** numbers. Verify your
demo phone under **Phone Numbers → Manage → Verified Caller IDs → Add a new number**,
confirm the code, and use that number as the customer's phone in the demo.

## 3. The two voice paths (cost discipline, PRD §9.7)

- **Default — Twilio native TTS.** Every call uses `<Say>` with an Indian voice. Free,
  used for all testing.
- **Hero call — ElevenLabs.** Set `USE_PREMIUM_VOICE=true` and `ELEVENLABS_API_KEY=...`
  **only** for the single staged call. The audio is rendered once and cached on disk,
  so the small free character quota is never spent twice. Leave it `false` for every
  test call.

## 4. Place one end-to-end test call

With the server and ngrok running, and a verified demo number set as the customer's
phone, inject a high-value expired-mandate case (or let a real Razorpay
`subscription.halted` webhook arrive). The flow:

1. Twilio places the call; it speaks the Hinglish script and names the amount.
2. **Press 1** — you receive the payment-link SMS; the audit trail records "link sent".
3. **Press 2** — the call ends politely and records a decline.
4. No input — records a no-answer.
5. Twilio posts the final call status to `/voice/status/{txn_id}`, recorded too.

Every branch writes an audit row, and each callback's `X-Twilio-Signature` is verified
against the auth token — an unsigned request is rejected with `403`.

## Notes

- The core Hinglish line is PRD §16.4's: *"aapka payment fail ho gaya hai, link
  bhejoon retry karne ke liye?"* — used with a title when one is known, and a
  gender-neutral opening otherwise.
- Voice is reserved for **high-value** items with a phone (Phase 5's channel policy),
  and the channel independently re-checks that. A voice failure falls through to SMS
  then email, every attempt audited.

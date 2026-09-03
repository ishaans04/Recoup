"""Razorpay webhook signature verification (PRD sections 8.1 and 14).

Razorpay signs the **raw request body** with HMAC-SHA256, keyed by a secret shared
out of band with the merchant dashboard, and sends the hex digest in the
``X-Razorpay-Signature`` header. This is the front door's only gate: PRD section 14
requires that no unsigned payload is ever processed, so everything downstream of
:func:`verify_razorpay_signature` returning ``False`` must be unreachable.

Two properties are non-negotiable here, both because a signature check is exactly
the kind of code a security-literate reviewer reads first:

**Constant-time comparison.** A naive ``==`` on two strings short-circuits at the
first differing byte, so its running time leaks how many leading bytes of a guess
were correct — the textbook timing side-channel. :func:`hmac.compare_digest` is
built to leak no such thing.

**Bytes, not the parsed object.** Verification must run against the exact bytes
Razorpay sent, before any JSON parsing. Re-serialising the parsed payload before
verifying would change the digest for any payload whose key order round-trips
differently — which is legitimate JSON, not tampering — and would either break
verification for real deliveries or, worse, invite an attacker to find a
byte-for-byte-different-but-semantically-equal payload that verifies against a
signature computed over different bytes. The caller (:mod:`recoup.ingestion.idempotency`)
enforces the ordering; this module simply never accepts anything but raw bytes.
"""

import hashlib
import hmac
import re

__all__ = ["compute_razorpay_signature", "verify_razorpay_signature"]

_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]+$")
"""A signature header must be pure hex to even be worth comparing. Anything else
(empty, whitespace, punctuation, a JWT someone pasted in the wrong header) is
rejected before it reaches :func:`hmac.compare_digest`."""


def compute_razorpay_signature(body: bytes, secret: str) -> str:
    """The hex-encoded HMAC-SHA256 of ``body`` keyed by ``secret``.

    Used two ways: by tests to produce genuine signatures without a Razorpay
    account, and by :func:`verify_razorpay_signature` itself. Phase 12 reuses it to
    verify signatures on live-replayed deliveries.
    """
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_razorpay_signature(body: bytes, signature_header: str | None, secret: str) -> bool:
    """Whether ``signature_header`` is a valid HMAC-SHA256 signature of ``body``.

    Never raises. An empty or ``None`` secret, an empty or ``None`` header, or a
    header containing anything but hex digits all return ``False`` rather than
    raising or accidentally validating — an unconfigured secret must never be
    mistaken for permission to accept unsigned traffic, and a malformed header
    must never crash the ingestion path a real Razorpay outage could hammer.
    """
    if not secret or not signature_header:
        return False
    if not _HEX_DIGEST.fullmatch(signature_header):
        return False
    expected = compute_razorpay_signature(body, secret)
    return hmac.compare_digest(expected, signature_header.lower())

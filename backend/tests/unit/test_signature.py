"""Behavioural tests for :mod:`recoup.ingestion.signature` (PRD sections 8.1 and 14).

No unsigned payload may ever be treated as verified. Every test here proves either
a genuine signature verifies, or some deviation from it fails closed.
"""

import json

from recoup.ingestion.signature import compute_razorpay_signature, verify_razorpay_signature

SECRET = "whsec_test_9f8a3c1e7b2d4f60"
BODY = b'{"event":"payment.failed","id":"evt_1"}'


def test_genuine_signature_verifies() -> None:
    signature = compute_razorpay_signature(BODY, SECRET)

    assert verify_razorpay_signature(BODY, signature, SECRET) is True


def test_one_byte_mutation_fails_verification() -> None:
    signature = compute_razorpay_signature(BODY, SECRET)
    mutated = BODY[:-1] + bytes([BODY[-1] ^ 0x01])

    assert verify_razorpay_signature(mutated, signature, SECRET) is False


def test_signature_from_a_different_secret_fails() -> None:
    signature = compute_razorpay_signature(BODY, "a-different-secret")

    assert verify_razorpay_signature(BODY, signature, SECRET) is False


def test_malformed_header_returns_false() -> None:
    assert verify_razorpay_signature(BODY, "not-a-hex-signature!!", SECRET) is False


def test_empty_header_returns_false() -> None:
    assert verify_razorpay_signature(BODY, "", SECRET) is False


def test_non_hex_header_returns_false() -> None:
    assert verify_razorpay_signature(BODY, "zz" * 32, SECRET) is False


def test_none_header_returns_false() -> None:
    assert verify_razorpay_signature(BODY, None, SECRET) is False


def test_empty_secret_returns_false_even_for_a_genuine_looking_header() -> None:
    signature = compute_razorpay_signature(BODY, SECRET)

    assert verify_razorpay_signature(BODY, signature, "") is False


def test_verification_operates_on_raw_bytes_not_reserialised_json() -> None:
    payload = {"b": 1, "a": 2}
    body_one = json.dumps(payload, sort_keys=False).encode("utf-8")
    body_two = json.dumps(payload, sort_keys=True).encode("utf-8")
    assert body_one != body_two, "the two encodings must differ for this test to prove anything"

    signature_one = compute_razorpay_signature(body_one, SECRET)
    signature_two = compute_razorpay_signature(body_two, SECRET)
    assert signature_one != signature_two

    assert verify_razorpay_signature(body_one, signature_one, SECRET) is True
    assert verify_razorpay_signature(body_one, signature_two, SECRET) is False
    assert verify_razorpay_signature(body_two, signature_two, SECRET) is True
    assert verify_razorpay_signature(body_two, signature_one, SECRET) is False

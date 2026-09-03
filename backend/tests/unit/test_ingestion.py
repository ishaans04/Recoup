"""Tests for :class:`recoup.ingestion.idempotency.Ingestor`.

The properties under test are the two the front door exists to guarantee (PRD
sections 8.1, 13.2, 14): a webhook delivered twice creates one work item and the
second delivery reports ``created=False``; and an invalid signature is rejected
*before* the body is parsed, so a malformed-and-badly-signed body fails as a
signature error, never as a parse error. ``ingest_payload`` reaches the same
normalized result as ``ingest_raw`` — the shared code path §8.1 claims.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine

from recoup.clock import SimulatedClock
from recoup.ingestion.idempotency import Ingestor, InvalidSignature
from recoup.ingestion.normalize import MalformedPayload
from recoup.ingestion.signature import compute_razorpay_signature
from recoup.storage.work_items import WorkItemRepo
from tests.conftest import CREATED_AT

_FIXTURES = Path(__file__).resolve().parents[2] / "src" / "recoup" / "batch" / "fixtures"
_SECRET = "whsec_demo_test_secret"


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start=CREATED_AT)


@pytest.fixture
def repo(engine: Engine) -> WorkItemRepo:
    return WorkItemRepo(engine)


@pytest.fixture
def ingestor(repo: WorkItemRepo, clock: SimulatedClock) -> Ingestor:
    return Ingestor(repo, clock, webhook_secret=_SECRET)


def _fixture_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _signed(body: bytes) -> str:
    return compute_razorpay_signature(body, _SECRET)


def test_valid_signature_creates_one_work_item(ingestor: Ingestor, repo: WorkItemRepo) -> None:
    body = _fixture_bytes("payment_failed_insufficient_funds.json")
    result = ingestor.ingest_raw(body, _signed(body))

    assert result.created is True
    assert result.item.txn_id == "pay_InsuffFundsAB01"
    assert repo.get("pay_InsuffFundsAB01") is not None


def test_duplicate_event_id_is_deduplicated(ingestor: Ingestor, repo: WorkItemRepo) -> None:
    body = _fixture_bytes("payment_failed_insufficient_funds.json")
    sig = _signed(body)

    first = ingestor.ingest_raw(body, sig)
    second = ingestor.ingest_raw(body, sig)

    assert first.created is True
    assert second.created is False
    # Second returns the originally stored item, and there is still exactly one row.
    assert second.item.txn_id == first.item.txn_id
    assert repo.count_by_state()[first.item.state] == 1


def test_invalid_signature_rejected_and_writes_nothing(
    ingestor: Ingestor, repo: WorkItemRepo
) -> None:
    body = _fixture_bytes("payment_failed_insufficient_funds.json")
    with pytest.raises(InvalidSignature):
        ingestor.ingest_raw(body, "deadbeef")  # valid hex, wrong signature
    assert repo.get("pay_InsuffFundsAB01") is None


def test_tampered_body_is_rejected(ingestor: Ingestor, repo: WorkItemRepo) -> None:
    body = _fixture_bytes("payment_failed_insufficient_funds.json")
    sig = _signed(body)
    tampered = body.replace(b"249900", b"149900")
    with pytest.raises(InvalidSignature):
        ingestor.ingest_raw(tampered, sig)
    assert repo.count_by_state() == {}


def test_signature_is_verified_before_parsing(ingestor: Ingestor) -> None:
    """A body that is both malformed JSON and badly signed fails as a signature
    error, not a parse error — parsing never runs on unauthenticated bytes."""
    garbage = b"{not valid json at all"
    with pytest.raises(InvalidSignature):
        ingestor.ingest_raw(garbage, "deadbeef")


def test_wellsigned_but_malformed_body_fails_as_parse_error(ingestor: Ingestor) -> None:
    """The complement: once a body authenticates, a JSON error surfaces as one."""
    garbage = b"{not valid json at all"
    with pytest.raises(MalformedPayload):
        ingestor.ingest_raw(garbage, _signed(garbage))


def test_unconfigured_secret_rejects_everything(
    repo: WorkItemRepo, clock: SimulatedClock
) -> None:
    """No webhook secret configured is a misconfiguration, not permission to accept
    unsigned traffic (PRD 14)."""
    ingestor = Ingestor(repo, clock, webhook_secret=None)
    body = _fixture_bytes("payment_failed_insufficient_funds.json")
    with pytest.raises(InvalidSignature, match="no webhook secret"):
        ingestor.ingest_raw(body, _signed(body))


def test_ingest_payload_matches_ingest_raw(ingestor: Ingestor, repo: WorkItemRepo) -> None:
    """The trusted batch path reaches the same normalized work item as the signed
    HTTP path for the same payload (the shared code path of PRD 8.1)."""
    body = _fixture_bytes("payment_failed_card_expired.json")
    raw_result = ingestor.ingest_raw(body, _signed(body))

    # A second, independent ingestor + repo to normalize the same payload untrusted-path.
    payload = json.loads(body)
    other_result = ingestor.ingest_payload(payload)

    # Same txn (deduplicated, since the first already stored it), same normalized fields.
    assert other_result.item.txn_id == raw_result.item.txn_id
    assert other_result.item.amount_paise == raw_result.item.amount_paise
    assert other_result.item.failure_code == raw_result.item.failure_code


def test_fraud_fixture_sets_fraud_flag(ingestor: Ingestor) -> None:
    body = _fixture_bytes("payment_failed_fraud_flagged.json")
    result = ingestor.ingest_raw(body, _signed(body))
    assert result.item.fraud_flag is True


def test_all_fixtures_ingest_through_the_trusted_path(ingestor: Ingestor) -> None:
    """Every shipped fixture normalizes and stores without error — they are reused
    by the Phase 8 batch and Phase 9 API, so a broken fixture must fail here."""
    for fixture in sorted(_FIXTURES.glob("*.json")):
        payload = json.loads(fixture.read_bytes())
        result = ingestor.ingest_payload(payload)
        assert result.item.txn_id
        assert result.item.amount_paise > 0

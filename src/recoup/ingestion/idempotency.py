"""The ingestion entry points: signature-first verification, then a shared
normalize-and-store path (PRD sections 8.1, 13.2 and 14).

Two callers, one code path. :meth:`Ingestor.ingest_raw` is what the HTTP webhook
route (Phase 9) will call: raw bytes off the wire plus whatever the
``X-Razorpay-Signature`` header held. :meth:`Ingestor.ingest_payload` is what the
batch demo runner (Phase 8) and any future replay tooling call: an already-parsed,
already-trusted payload — a stored fixture, not an inbound HTTP request, so there
is no signature to check. Both end up in :func:`~recoup.ingestion.normalize.normalize`
and :meth:`~recoup.storage.work_items.WorkItemRepo.create_if_absent`, which is
exactly the "live and batch runs use identical code paths" claim PRD section 8.1
makes — it is true because this is the one place either path is implemented.

The ordering inside :meth:`Ingestor.ingest_raw` is load-bearing and covered by a
dedicated test: verify the signature, *then* parse the JSON. Parsing
attacker-controlled bytes before authenticating them is the exact bug that
ordering exists to prevent — a malformed-but-well-signed body should fail with a
parse error, and a malformed-and-badly-signed body must fail with a signature
error, never the other way around.
"""

import json
from dataclasses import dataclass

from recoup.clock import Clock
from recoup.domain.models import WorkItem
from recoup.ingestion.normalize import MalformedPayload, normalize
from recoup.ingestion.signature import verify_razorpay_signature
from recoup.storage.work_items import WorkItemRepo

__all__ = ["IngestResult", "Ingestor", "InvalidSignature"]


class InvalidSignature(Exception):
    """Raised by :meth:`Ingestor.ingest_raw` when a webhook does not verify.

    Covers three cases alike: a signature that does not match the body, a
    malformed/missing signature header, and no webhook secret configured at all.
    None of the three is treated as "skip verification" — an unconfigured secret
    is a misconfiguration, not permission to accept unsigned traffic.
    """


@dataclass(frozen=True)
class IngestResult:
    """What ingesting one webhook produced.

    ``created=False`` means this ``event_id`` was already stored — PRD section
    13.2's duplicate-delivery case — and :attr:`item` is the originally stored work
    item, not a second one derived from this delivery's (possibly different) bytes.
    """

    item: WorkItem
    created: bool


class Ingestor:
    """Verifies, normalizes and idempotently stores inbound Razorpay webhooks."""

    def __init__(self, repo: WorkItemRepo, clock: Clock, webhook_secret: str | None) -> None:
        self._repo = repo
        self._clock = clock
        self._webhook_secret = webhook_secret

    def ingest_raw(self, body: bytes, signature_header: str | None) -> IngestResult:
        """Verify signature -> parse -> normalize -> idempotent create.

        Raises :class:`InvalidSignature` before parsing anything — including when
        no webhook secret is configured, in which case every delivery is rejected
        regardless of what the header holds.
        """
        if not self._webhook_secret:
            raise InvalidSignature("no webhook secret configured; rejecting webhook")
        if not verify_razorpay_signature(body, signature_header, self._webhook_secret):
            raise InvalidSignature("webhook signature verification failed")

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MalformedPayload(f"body is not valid JSON: {exc}") from exc

        return self._ingest(payload)

    def ingest_payload(self, payload: dict[str, object]) -> IngestResult:
        """Normalize and idempotently store an already-trusted payload.

        No signature check: the trusted path for the batch runner and replay
        tooling (PRD section 8.1), reaching the same downstream code as
        :meth:`ingest_raw`.
        """
        return self._ingest(payload)

    def _ingest(self, payload: dict[str, object]) -> IngestResult:
        item = normalize(payload, clock=self._clock)
        stored, created = self._repo.create_if_absent(item)
        return IngestResult(item=stored, created=created)

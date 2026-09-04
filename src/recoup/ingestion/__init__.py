"""The ingestion front door (PRD sections 8.1, 13.2 and 14).

Three concerns, three modules, deliberately separate so each is testable without
the other two: :mod:`recoup.ingestion.signature` verifies that a webhook is
genuinely from Razorpay, :mod:`recoup.ingestion.normalize` converts its raw shape
into the internal :class:`~recoup.domain.models.WorkItem`, and
:mod:`recoup.ingestion.idempotency` composes both behind the ordering PRD section
14 requires — signature first, parsing second — plus the database-enforced
deduplication PRD section 13.2 requires.
"""

from recoup.ingestion.idempotency import Ingestor, IngestResult, InvalidSignature
from recoup.ingestion.normalize import MalformedPayload, UnsupportedEvent, normalize
from recoup.ingestion.signature import compute_razorpay_signature, verify_razorpay_signature

__all__ = [
    "IngestResult",
    "Ingestor",
    "InvalidSignature",
    "MalformedPayload",
    "UnsupportedEvent",
    "compute_razorpay_signature",
    "normalize",
    "verify_razorpay_signature",
]

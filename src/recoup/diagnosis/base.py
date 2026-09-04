"""The Tier-2 diagnosis interface.

PRD section 11 splits diagnosis in two. Tier 1 is a deterministic rules table:
most PSP failure codes are unambiguous and an ``insufficient_funds`` code does not
need a model. Tier 2 is an LLM, called only for the ambiguous long tail.

:class:`LLMClient` is that second tier, and it is deliberately the narrowest
interface in the system. The LLM's entire authority is to return a
:class:`~recoup.domain.models.Diagnosis`. It does not choose an action, does not
touch a gateway, and does not know that money exists (PRD section 4). One method,
one return type, no side effects — the restraint is visible in the type signature
rather than asserted in a comment.

Phase 0 declares this. Phase 4 composes it behind the rules table, phase 11
implements the Groq client.
"""

from typing import Protocol, runtime_checkable

from recoup.domain.models import Diagnosis, FailureContext

__all__ = ["LLMClient"]


@runtime_checkable
class LLMClient(Protocol):
    """A model that classifies an ambiguous payment failure."""

    async def classify(self, ctx: FailureContext) -> Diagnosis | None:
        """Classify ``ctx``, or return ``None``.

        **This method never raises, and never returns an unvalidated cause.**
        ``None`` is the single, complete signal for every way this can fail:

        - the provider is rate-limited, down, or times out;
        - the response is not JSON, or is JSON of the wrong shape;
        - the model names a cause outside :class:`~recoup.domain.enums.Cause`;
        - the model returns a confidence outside ``0.0`` to ``1.0``;
        - the model returns an empty rationale.

        Two reasons for collapsing all of that into one return value rather than an
        exception hierarchy.

        First, availability. PRD section 13.1 requires the system to degrade rather
        than stop when an external service fails, and every one of the cases above
        means the same thing to the caller: Tier 2 produced nothing usable, so fall
        back to ``unknown`` with ``source="fallback"`` and let the confidence floor
        route the item safely. A caller that must distinguish a timeout from a
        malformed response would still take the same action in both cases, so the
        distinction belongs in the implementation's logging, not in its contract.

        Second, and more important, safety. A cause selects a money action. An
        out-of-enum cause coerced into the nearest known one, or a hallucinated
        cause allowed through unvalidated, would pick an action nobody authorised.
        Rejecting it to ``None`` costs one recovery attempt; accepting it costs the
        guarantee that the action space is closed.

        An implementation that lets an exception escape is a defect, not a variant:
        the diagnosis engine has no handler for one, by design.
        """
        ...

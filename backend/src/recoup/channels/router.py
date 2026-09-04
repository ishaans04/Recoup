"""The nudge fallback router (PRD §8.7, §13.1, §13.2).

A nudge is resilient only if a failure on one channel still tries the next. This
walks the ordered chain Phase 5 chose — voice, then SMS, then email, filtered to
what the customer can receive — and **records every attempt as its own audited
outcome before falling through**, so a reviewer can read the trail and see that
voice was tried and failed before SMS was tried. The first channel that delivers
wins; if every channel fails or none can handle the item, the returned result names
the full chain of reasons, so the escalation record explains exactly why the customer
could not be reached (PRD §13.2).

Being in the channels package, this may drive channels — but it is only ever called
by the executor, after the gate pass is verified, so the gate stays the only door.
"""

from __future__ import annotations

from collections.abc import Sequence

from recoup.channels.base import ChannelRegistry
from recoup.clock import Clock
from recoup.domain.enums import Channel
from recoup.domain.models import Action, AuditEvent, ChannelResult, WorkItem
from recoup.storage.audit import AuditLog

__all__ = ["ChannelRouter"]


class ChannelRouter:
    """Walks a nudge channel chain, auditing each attempt, and returns the first delivery."""

    def __init__(self, registry: ChannelRegistry, audit: AuditLog, clock: Clock) -> None:
        self._registry = registry
        self._audit = audit
        self._clock = clock

    async def deliver(
        self, item: WorkItem, action: Action, chain: Sequence[Channel]
    ) -> ChannelResult:
        """Try each channel in ``chain`` until one delivers; audit every attempt."""
        if not chain:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail="no reachable channel: the customer has no phone or email on file",
            )

        reasons: list[str] = []
        for channel_name in chain:
            channel = self._registry.resolve(channel_name, item)
            if channel is None:
                reasons.append(f"{channel_name.value}: no channel available")
                continue

            result = await channel.execute(item, action)
            self._record_attempt(item, action, channel_name, result)
            if result.delivered:
                return result
            reasons.append(f"{channel_name.value}: {result.detail}")

        return ChannelResult(
            delivered=False,
            recovered=False,
            detail="all nudge channels failed: " + "; ".join(reasons),
        )

    def _record_attempt(
        self, item: WorkItem, action: Action, channel: Channel, result: ChannelResult
    ) -> None:
        """Append an audit row for one delivery attempt.

        A same-state annotation (``from_state == to_state == item.state``): it records
        that an attempt happened while the item was in this state, without pretending
        to be a lifecycle transition, so it never disturbs the state chain the trail's
        completeness rests on.
        """
        outcome = "delivered" if result.delivered else "not delivered"
        self._audit.append(
            AuditEvent(
                timestamp=self._clock.now(),
                txn_id=item.txn_id,
                from_state=item.state,
                to_state=item.state,
                action_chosen=action.type,
                outcome=outcome,
                rationale=f"nudge attempt via {channel.value}: {result.detail}",
            )
        )

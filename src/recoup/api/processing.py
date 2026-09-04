"""Driving a single work item through the live orchestrator (PRD §7.4, §8.2).

The batch runner fast-forwards a simulated clock to resolve scheduled retries; the
live API cannot — its clock is real wall time. So live processing drives a work
item until it either settles (a terminal state) or parks in a not-yet-due
``SCHEDULED``, and leaves a parked item for a future scheduler to pick up. The
demo-critical paths — a gate rejection, an immediate recovery, an escalation — all
settle synchronously; only a genuinely future-dated retry parks.
"""

from __future__ import annotations

from recoup.clock import Clock
from recoup.domain.enums import State
from recoup.domain.models import WorkItem
from recoup.fsm.orchestrator import Orchestrator

__all__ = ["drive_until_settled"]

_MAX_STEPS = 64


def _is_parked(item: WorkItem, clock: Clock) -> bool:
    if item.state is not State.SCHEDULED:
        return False
    action = item.action
    if action is None or action.scheduled_for is None:
        return False
    return clock.now() < action.scheduled_for


async def drive_until_settled(orchestrator: Orchestrator, clock: Clock, item: WorkItem) -> WorkItem:
    """Advance ``item`` until it is terminal or parked in a future-dated SCHEDULED."""
    current = item
    for _ in range(_MAX_STEPS):
        if current.is_terminal or _is_parked(current, clock):
            return current
        current = await orchestrator.advance(current)
    return current

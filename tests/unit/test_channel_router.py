"""Tests for the nudge fallback router (PRD §8.7, §13.1, §13.2).

The router must walk the chain in order, stop at the first delivery, and — the
load-bearing part — record every attempt as its own audit row *before* falling
through, so the trail shows voice was tried before SMS.
"""

from __future__ import annotations

from sqlalchemy import Engine

from recoup.channels.base import ChannelRegistry
from recoup.channels.router import ChannelRouter
from recoup.clock import SimulatedClock
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, ChannelResult, WorkItem
from recoup.storage.audit import AuditLog
from tests.conftest import CREATED_AT, make_work_item


class _FakeChannel:
    def __init__(self, name: Channel, *, delivers: bool) -> None:
        self._name = name
        self._delivers = delivers
        self.calls = 0

    @property
    def name(self) -> Channel:
        return self._name

    def can_handle(self, item: WorkItem) -> bool:
        return True

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        self.calls += 1
        verb = "delivered" if self._delivers else "failed"
        return ChannelResult(
            delivered=self._delivers,
            recovered=False,
            detail=f"{self._name.value} {verb}",
            channel=self._name,
        )


def _router(engine: Engine, *channels: _FakeChannel) -> tuple[ChannelRouter, AuditLog]:
    registry = ChannelRegistry()
    for channel in channels:
        registry.register(channel)
    audit = AuditLog(engine)
    return ChannelRouter(registry, audit, SimulatedClock(start=CREATED_AT)), audit


def _nudge() -> Action:
    return Action(type=ActionType.CUSTOMER_NUDGE, channel=Channel.VOICE, reason="expired mandate")


async def test_chain_is_walked_in_order_and_stops_at_the_first_success(engine: Engine) -> None:
    sms = _FakeChannel(Channel.SMS, delivers=False)
    email = _FakeChannel(Channel.EMAIL, delivers=True)
    router, _ = _router(engine, sms, email)
    item = make_work_item()

    result = await router.deliver(item, _nudge(), [Channel.SMS, Channel.EMAIL])
    assert result.delivered is True
    assert result.channel is Channel.EMAIL
    assert (sms.calls, email.calls) == (1, 1)


async def test_a_failed_first_attempt_is_audited_before_the_second_is_tried(engine: Engine) -> None:
    sms = _FakeChannel(Channel.SMS, delivers=False)
    email = _FakeChannel(Channel.EMAIL, delivers=True)
    router, audit = _router(engine, sms, email)
    item = make_work_item()

    await router.deliver(item, _nudge(), [Channel.SMS, Channel.EMAIL])
    rows = audit.for_txn(item.txn_id)
    # One audit row per attempt, in order: the SMS failure recorded before the email.
    attempts = [r.rationale for r in rows if "nudge attempt" in r.rationale]
    assert len(attempts) == 2
    assert "sms" in attempts[0] and "not delivered" in (rows[0].outcome or "")
    assert "email" in attempts[1] and rows[1].outcome == "delivered"


async def test_all_channels_failing_names_every_reason(engine: Engine) -> None:
    sms = _FakeChannel(Channel.SMS, delivers=False)
    email = _FakeChannel(Channel.EMAIL, delivers=False)
    router, _ = _router(engine, sms, email)

    result = await router.deliver(make_work_item(), _nudge(), [Channel.SMS, Channel.EMAIL])
    assert result.delivered is False
    assert "sms failed" in result.detail
    assert "email failed" in result.detail


async def test_a_channel_not_registered_is_reported_as_unavailable(engine: Engine) -> None:
    # Voice is in the chain but not registered; only email is, and it delivers.
    email = _FakeChannel(Channel.EMAIL, delivers=True)
    router, _ = _router(engine, email)
    result = await router.deliver(make_work_item(), _nudge(), [Channel.VOICE, Channel.EMAIL])
    assert result.delivered is True
    assert result.channel is Channel.EMAIL


async def test_an_empty_chain_names_the_missing_contact(engine: Engine) -> None:
    router, _ = _router(engine)
    result = await router.deliver(make_work_item(), _nudge(), [])
    assert result.delivered is False
    assert "no phone or email" in result.detail.lower()

"""The recovery channel interface and the registry that resolves one.

A recovery channel is anything that can act on a failed payment: re-present it to
the gateway, text the customer, email them, call them, or hand them to a person
(PRD section 8.7). They differ enormously in implementation and not at all in
shape, so the orchestrator is written against one interface and never learns which
channels exist.

The registry is where "no channel available" becomes real behaviour rather than a
gap. With nothing registered, :meth:`ChannelRegistry.resolve` returns ``None`` and
the executor escalates — a correct, auditable outcome, not a crash and not a
silently skipped work item. That is why phases 0 through 6 can run the full
recovery loop before a single channel implementation exists.

Phase 0 declares the interface and ships the complete registry. Phase 7 registers
the payment retry channel, phase 13 SMS and email, phase 14 voice.
"""

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from recoup.domain.enums import Channel
from recoup.domain.models import Action, ChannelResult, WorkItem

__all__ = ["ChannelRegistry", "RecoveryChannel"]


@runtime_checkable
class RecoveryChannel(Protocol):
    """One way of acting on a failed payment."""

    @property
    def name(self) -> Channel:
        """Which channel this is. The registry key, and the audit log's label."""
        ...

    def can_handle(self, item: WorkItem) -> bool:
        """Whether this channel can act on this work item *right now*.

        Deliberately per-item rather than a static capability. A voice channel is
        configured and healthy but still cannot call a customer with no phone
        number; an SMS channel cannot text one with no phone number either. Asking
        first turns "this recovery had no viable channel" into a decision the audit
        log records, instead of a delivery failure discovered after the attempt.

        Must not perform I/O and must not raise: it is called while choosing, not
        while acting.
        """
        ...

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        """Carry out ``action`` for ``item``.

        Called only after the constraint gate has passed the action. The returned
        :class:`~recoup.domain.models.ChannelResult` reports delivery and recovery
        separately, because a nudge can be delivered perfectly and recover nothing
        at the moment it is sent.
        """
        ...


class ChannelRegistry:
    """The set of channels available to the executor, keyed by :class:`Channel`.

    Registration happens once at startup; resolution happens per work item. Keeping
    those apart is what lets the executor ask "can anything handle this?" without
    knowing what has been wired in.
    """

    def __init__(self) -> None:
        self._channels: dict[Channel, RecoveryChannel] = {}

    def register(self, channel: RecoveryChannel) -> None:
        """Add ``channel`` under its own :attr:`RecoveryChannel.name`.

        Registering a second channel for the same name raises rather than
        overwriting. Two implementations claiming ``sms`` is a wiring mistake, and
        silently keeping whichever was registered last would make which one runs
        depend on import order — an invisible difference in behaviour that would
        show up as an unreproducible recovery outcome.
        """
        name = channel.name
        if name in self._channels:
            raise ValueError(f"a channel is already registered for {name!r}")
        self._channels[name] = channel

    def resolve(self, name: Channel, item: WorkItem) -> RecoveryChannel | None:
        """The channel registered under ``name``, if it can handle ``item``.

        Returns ``None`` when nothing is registered under that name, and also when
        something is registered but reports it cannot handle this particular item.
        Both are the same answer to the executor's question — there is no channel
        for this work item — and the executor escalates with "no channel available".

        That is real behaviour with an empty registry, which is what lets the
        recovery loop be built and tested before any channel exists.
        """
        channel = self._channels.get(name)
        if channel is None or not channel.can_handle(item):
            return None
        return channel

    def get(self, name: Channel) -> RecoveryChannel | None:
        """The channel registered under ``name`` regardless of any item, or ``None``.

        Unlike :meth:`resolve`, this does not consult ``can_handle`` — it answers
        "is this channel wired in at all?", which the voice keypress route needs to
        find the SMS sender to hand a payment link to.
        """
        return self._channels.get(name)

    def resolve_chain(self, names: Iterable[Channel], item: WorkItem) -> list[RecoveryChannel]:
        """Every channel in ``names`` that can handle ``item``, in the given order.

        Order is preference, and it is preserved exactly: the policy expresses
        "voice, then SMS, then email" for a high-value nudge, and the executor
        walks the result until one succeeds. Channels that are unregistered or
        report they cannot handle the item are dropped rather than represented by a
        placeholder, so the returned list is exactly what can be attempted.

        A name appearing twice yields that channel twice; deduplication is the
        caller's business, since a deliberate retry down the same channel is a
        legitimate chain.
        """
        resolved = (self.resolve(name, item) for name in names)
        return [channel for channel in resolved if channel is not None]

    def __contains__(self, name: object) -> bool:
        """Whether anything is registered under ``name``, regardless of any item."""
        return name in self._channels

    def __len__(self) -> int:
        """How many channels are registered."""
        return len(self._channels)

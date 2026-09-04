"""The action executor: verifies a gate pass, then runs the recovery channel.

This module is the **only** one in the codebase that imports
:mod:`recoup.channels`. That is the mechanism behind PRD §12.3's "the gate is the
only door": if a channel can only be reached from here, and here refuses to act
without a verified :class:`~recoup.constraints.gate.GatePass`, then every money
action provably passed the gate. ``tests/architecture/test_single_door.py`` walks
the source and fails the build if any other module imports the channels package.

A retry runs against a single resolved channel; a customer nudge is handed to the
:class:`~recoup.channels.router.ChannelRouter`, which walks the voice→SMS→email
fallback chain and audits each attempt. Both paths run only after the pass verifies.
"""

from __future__ import annotations

from recoup.channels.base import ChannelRegistry
from recoup.channels.router import ChannelRouter
from recoup.constraints.gate import ConstraintGate, GatePass
from recoup.domain.enums import ActionType
from recoup.domain.models import Action, ExecutionResult, WorkItem
from recoup.policy.selector import chain_for

__all__ = ["ActionExecutor"]


class ActionExecutor:
    """Runs a gated action against its recovery channel, or reports why it could not."""

    def __init__(
        self,
        gate: ConstraintGate,
        registry: ChannelRegistry,
        nudge_router: ChannelRouter | None = None,
    ) -> None:
        self._gate = gate
        self._registry = registry
        self._nudge_router = nudge_router

    async def execute(self, gate_pass: GatePass, item: WorkItem, action: Action) -> ExecutionResult:
        """Verify the pass first; only then resolve a channel (or the nudge chain) and run it.

        The verification is the first statement, before any channel is even looked
        up: a forged, mismatched or stale pass raises
        :class:`~recoup.constraints.gate.GateBypassError` and nothing runs.
        """
        self._gate.verify(gate_pass, action, item)

        if action.type is ActionType.CUSTOMER_NUDGE and self._nudge_router is not None:
            chain = chain_for(item, item.diagnosis) if item.diagnosis is not None else []
            result = await self._nudge_router.deliver(item, action, chain)
            return ExecutionResult(
                recovered=result.recovered,
                channel=result.channel or action.channel,
                detail=result.detail,
                provider_ref=result.provider_ref,
            )

        channel = self._registry.resolve(action.channel, item)
        if channel is None:
            # No channel registered for the action (or none able to handle this item):
            # a real, bounded outcome, never a silent drop.
            return ExecutionResult(
                recovered=False,
                channel=action.channel,
                detail=f"no channel available for {action.channel.value}",
                provider_ref=None,
            )

        result = await channel.execute(item, action)
        return ExecutionResult(
            recovered=result.recovered,
            channel=channel.name,
            detail=result.detail,
            provider_ref=result.provider_ref,
        )

"""Action execution: the one place a gated action actually runs (PRD §12).

:class:`~recoup.execution.executor.ActionExecutor` is the sole module in the
codebase permitted to import :mod:`recoup.channels`, and it runs nothing without a
valid :class:`~recoup.constraints.gate.GatePass`. :class:`~recoup.execution.pipeline.GatePipeline`
composes the gate and the executor into the ``check_and_execute`` callable the
orchestrator (Phase 2) drives, returning the ``GateOutcome`` it routes on.
"""

from recoup.execution.executor import ActionExecutor
from recoup.execution.pipeline import GatePipeline

__all__ = ["ActionExecutor", "GatePipeline"]

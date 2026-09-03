"""The constraint gate and its inputs.

The gate is the single door through which every money action must pass (PRD
section 12.1). Phase 0 declares the breaker state it consults; the gate itself
arrives in phase 6 and the real circuit breaker in phase 7.
"""

from recoup.constraints.base import BreakerState, NullBreaker
from recoup.constraints.gate import (
    ConstraintGate,
    GateBypassError,
    GatePass,
    GateVerdict,
)
from recoup.constraints.rules import ConstraintRule, RuleVerdict, default_rules

__all__ = [
    "BreakerState",
    "ConstraintGate",
    "ConstraintRule",
    "GateBypassError",
    "GatePass",
    "GateVerdict",
    "NullBreaker",
    "RuleVerdict",
    "default_rules",
]

"""The constraint gate and its inputs.

The gate is the single door through which every money action must pass (PRD
section 12.1). Phase 0 declares the breaker state it consults; the gate itself
arrives in phase 6 and the real circuit breaker in phase 7.
"""

from recoup.constraints.base import BreakerState, NullBreaker

__all__ = ["BreakerState", "NullBreaker"]

"""The recovery lifecycle transition table (PRD sections 4 and 7.4).

This module is the data form of the governing principle: **recovery is a state
machine, not a chatbot.** :data:`LEGAL_TRANSITIONS` is the exhaustive, closed set of
edges a work item may ever walk. Nothing outside this file decides what a legal next
state is — :class:`~recoup.fsm.machine.StateMachine` consults it and refuses
everything else, so "illegal transitions are impossible" is a property of this table,
not a habit callers are trusted to keep.

```
DETECTED -> DIAGNOSED
DIAGNOSED -> ACTION_CHOSEN
ACTION_CHOSEN -> CONSTRAINT_CHECKED
CONSTRAINT_CHECKED -> SCHEDULED | EXECUTED | ESCALATED
SCHEDULED -> EXECUTED | ESCALATED
EXECUTED -> RESOLVED | ACTION_CHOSEN | ESCALATED
RESOLVED -> (terminal)
ESCALATED -> (terminal)
```

**Division of responsibility for the ``EXECUTED -> ACTION_CHOSEN`` edge.** This is
the bounded retry loop from PRD section 7.4 step 7 ("failed, retries remain -> back
to step 4"). The bound itself — "retries remain" — is *not* this module's concern.
The FSM only answers "is this edge ever legal", and the answer is yes: a work item
may cycle from ``EXECUTED`` back to ``ACTION_CHOSEN`` any number of times as far as
this table is concerned. What stops it happening a fourth time is the constraint
gate built in Phase 6, which reads ``retry_count`` against the configured cap and
refuses to propose another action once it is exhausted — at that point the
orchestrator routes to ``ESCALATED`` instead. Put another way: the FSM permits the
edge; the gate decides how many times to walk it. Keeping that decision out of this
module is deliberate — the transition table must stay a pure function of state, with
no policy (a retry cap, a time, an amount) folded into it.

``SCHEDULED`` is the parking state for two distinct waiting reasons that the FSM
does not need to tell apart: a salary-cycle-timed retry for an unfunded account
(PRD section 11.4) and a work item held behind an open circuit breaker (PRD section
13.1). Both cases are "constraints passed, execution deferred", which is exactly what
``SCHEDULED`` means; the orchestrator built in this phase re-evaluates a parked item
against the clock (or, in a later phase, the breaker) each time it is advanced.
"""

from collections.abc import Mapping

from recoup.domain.enums import State

__all__ = ["LEGAL_TRANSITIONS", "is_terminal", "legal_next"]

LEGAL_TRANSITIONS: Mapping[State, frozenset[State]] = {
    State.DETECTED: frozenset({State.DIAGNOSED}),
    State.DIAGNOSED: frozenset({State.ACTION_CHOSEN}),
    State.ACTION_CHOSEN: frozenset({State.CONSTRAINT_CHECKED}),
    State.CONSTRAINT_CHECKED: frozenset({State.SCHEDULED, State.EXECUTED, State.ESCALATED}),
    State.SCHEDULED: frozenset({State.EXECUTED, State.ESCALATED}),
    State.EXECUTED: frozenset({State.RESOLVED, State.ACTION_CHOSEN, State.ESCALATED}),
    State.RESOLVED: frozenset(),
    State.ESCALATED: frozenset(),
}
"""Exhaustive over :class:`~recoup.domain.enums.State`: every member is a key, so a
state added later without an accompanying transition rule fails
``test_fsm_states.py``'s exhaustiveness check rather than silently having no legal
successors (which would make it a de facto terminal state with no one having decided
that on purpose)."""


def is_terminal(state: State) -> bool:
    """Whether ``state`` has no legal successor.

    Equivalent to ``state in TERMINAL_STATES`` (PRD section 12.2's stopping rule)
    but expressed against :data:`LEGAL_TRANSITIONS` so the two can never drift apart:
    a state is terminal exactly when its transition-table entry is empty.
    """
    return not LEGAL_TRANSITIONS[state]


def legal_next(state: State) -> frozenset[State]:
    """The set of states ``state`` may legally transition to. Empty for a terminal state."""
    return LEGAL_TRANSITIONS[state]

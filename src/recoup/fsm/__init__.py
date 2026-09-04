"""The recovery lifecycle: the transition table, the audited state machine, and
the orchestrator that drives a work item through it (PRD sections 4, 7.4 and 8.2).

Nothing outside this package decides what state a work item may move to next, or
writes a state change without a matching audit row. That is the whole claim of
PRD section 4 made literal: recovery is a state machine, not a chatbot.
"""

from recoup.fsm.machine import IllegalTransition, StateMachine, TerminalStateError
from recoup.fsm.orchestrator import GateOutcome, Orchestrator, OrchestratorDeps
from recoup.fsm.states import LEGAL_TRANSITIONS, is_terminal, legal_next

__all__ = [
    "LEGAL_TRANSITIONS",
    "GateOutcome",
    "IllegalTransition",
    "Orchestrator",
    "OrchestratorDeps",
    "StateMachine",
    "TerminalStateError",
    "is_terminal",
    "legal_next",
]

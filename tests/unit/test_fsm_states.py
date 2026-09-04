"""Tests for :mod:`recoup.fsm.states`.

The property under test is the one PRD section 4 depends on: the transition table is
exhaustive and closed. A new :class:`~recoup.domain.enums.State` added later without
an accompanying entry in ``LEGAL_TRANSITIONS`` must fail
``test_every_state_has_a_transition_rule`` rather than silently behave as an
unreachable dead end.
"""

from recoup.domain.enums import State
from recoup.fsm.states import LEGAL_TRANSITIONS, is_terminal, legal_next


def test_every_state_has_a_transition_rule() -> None:
    """Exhaustiveness: every member of State is a key in LEGAL_TRANSITIONS."""
    assert set(LEGAL_TRANSITIONS.keys()) == set(State)


def test_terminal_states_have_no_successors() -> None:
    assert LEGAL_TRANSITIONS[State.RESOLVED] == frozenset()
    assert LEGAL_TRANSITIONS[State.ESCALATED] == frozenset()
    assert is_terminal(State.RESOLVED) is True
    assert is_terminal(State.ESCALATED) is True


def test_non_terminal_states_have_at_least_one_successor() -> None:
    for state in State:
        if state in (State.RESOLVED, State.ESCALATED):
            continue
        assert LEGAL_TRANSITIONS[state], f"{state} has no legal successor but is not terminal"
        assert is_terminal(state) is False


def test_legal_next_matches_the_table_exactly() -> None:
    for state, successors in LEGAL_TRANSITIONS.items():
        assert legal_next(state) == successors


def test_the_table_matches_the_prd_lifecycle_exactly() -> None:
    """PRD section 7.4's lifecycle, pinned edge for edge."""
    assert {
        State.DETECTED: frozenset({State.DIAGNOSED}),
        State.DIAGNOSED: frozenset({State.ACTION_CHOSEN}),
        State.ACTION_CHOSEN: frozenset({State.CONSTRAINT_CHECKED}),
        State.CONSTRAINT_CHECKED: frozenset({State.SCHEDULED, State.EXECUTED, State.ESCALATED}),
        State.SCHEDULED: frozenset({State.EXECUTED, State.ESCALATED}),
        State.EXECUTED: frozenset({State.RESOLVED, State.ACTION_CHOSEN, State.ESCALATED}),
        State.RESOLVED: frozenset(),
        State.ESCALATED: frozenset(),
    } == LEGAL_TRANSITIONS


def test_executed_may_cycle_back_to_action_chosen() -> None:
    """The bounded retry loop of PRD section 7.4 step 7. The FSM permits the edge
    unconditionally; the constraint gate (Phase 6) is what bounds how many times it
    is actually walked."""
    assert State.ACTION_CHOSEN in legal_next(State.EXECUTED)


def test_a_graph_walk_from_detected_reaches_every_state() -> None:
    """No state is an island: every state is reachable from the entry state."""
    reached: set[State] = set()
    frontier = [State.DETECTED]
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        frontier.extend(legal_next(current))

    assert reached == set(State)


def test_resolved_and_escalated_are_reachable_from_constraint_checked_and_executed() -> None:
    assert State.ESCALATED in legal_next(State.CONSTRAINT_CHECKED)
    assert State.ESCALATED in legal_next(State.EXECUTED)
    assert State.RESOLVED in legal_next(State.EXECUTED)
    assert State.RESOLVED not in legal_next(State.CONSTRAINT_CHECKED)

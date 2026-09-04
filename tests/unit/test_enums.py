"""The enum values are contract, not implementation detail.

They are written into the append-only audit log and rendered by the dashboard, so
a rename silently invalidates history and breaks the frontend. These tests pin the
exact wire strings from ``docs/interface-contract.md`` section 1.
"""

from recoup.domain.enums import (
    TERMINAL_STATES,
    ActionType,
    Cause,
    Channel,
    FailureType,
    State,
)


def test_state_values_are_uppercase_names() -> None:
    """States are shouted in the audit log; the contract documents that asymmetry."""
    assert {s.name: s.value for s in State} == {
        "DETECTED": "DETECTED",
        "DIAGNOSED": "DIAGNOSED",
        "ACTION_CHOSEN": "ACTION_CHOSEN",
        "CONSTRAINT_CHECKED": "CONSTRAINT_CHECKED",
        "SCHEDULED": "SCHEDULED",
        "EXECUTED": "EXECUTED",
        "RESOLVED": "RESOLVED",
        "ESCALATED": "ESCALATED",
    }


def test_cause_wire_values() -> None:
    assert {c.value for c in Cause} == {
        "insufficient_funds",
        "gateway_degradation",
        "soft_decline",
        "expired_instrument",
        "fraud_flagged",
        "unknown",
    }


def test_action_type_wire_values() -> None:
    assert {a.value for a in ActionType} == {
        "scheduled_retry",
        "backoff_retry",
        "immediate_retry",
        "customer_nudge",
        "no_action",
        "escalate",
    }


def test_channel_wire_values() -> None:
    assert {c.value for c in Channel} == {
        "payment_retry",
        "voice",
        "sms",
        "email",
        "human_queue",
    }


def test_failure_type_wire_values() -> None:
    assert {f.value for f in FailureType} == {"subscription", "one_time", "invoice"}


def test_str_enums_compare_and_serialise_as_plain_strings() -> None:
    """A StrEnum member must cross the SQLite, JSON and HTTP boundaries unconverted."""
    assert State.RESOLVED == "RESOLVED"
    assert Cause.INSUFFICIENT_FUNDS == "insufficient_funds"
    assert f"{Channel.SMS}" == "sms"
    assert {"sms": 1}[Channel.SMS] == 1


def test_terminal_states_are_exactly_resolved_and_escalated() -> None:
    """The stopping rule of PRD section 12.2 lives here and nowhere else."""
    assert isinstance(TERMINAL_STATES, frozenset)
    assert set(TERMINAL_STATES) == {State.RESOLVED, State.ESCALATED}
    non_terminal = set(State) - TERMINAL_STATES
    assert non_terminal == {
        State.DETECTED,
        State.DIAGNOSED,
        State.ACTION_CHOSEN,
        State.CONSTRAINT_CHECKED,
        State.SCHEDULED,
        State.EXECUTED,
    }

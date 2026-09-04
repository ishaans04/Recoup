"""Tests for the cross-layer protocols and the two implementations shipped with them.

Phase 0 owns the interfaces and later phases own the implementations, so what is
testable here is conformance and the registry's real behaviour when nothing has
been registered yet. That last case is not a degenerate one: phases 0 to 6 run the
whole recovery loop against an empty registry.
"""

from datetime import datetime, timedelta, timezone

import pytest

from recoup.channels.base import ChannelRegistry, RecoveryChannel
from recoup.constraints.base import BreakerState, NullBreaker
from recoup.diagnosis.base import LLMClient
from recoup.domain.enums import ActionType, Cause, Channel, FailureType, State
from recoup.domain.models import (
    Action,
    ChannelResult,
    Customer,
    Diagnosis,
    ExecutionResult,
    FailureContext,
    WorkItem,
)
from recoup.gateways.base import GatewayTxn, PaymentGateway

IST = timezone(timedelta(hours=5, minutes=30), "IST")
CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)


def make_work_item(**overrides: object) -> WorkItem:
    fields: dict[str, object] = {
        "txn_id": "pay_QjK9x2LmN4TzAb",
        "event_id": "evt_8fH2kQpR7sVdWx",
        "merchant_id": "acc_MerchantDemo01",
        "amount_paise": 249900,
        "failure_code": "BAD_REQUEST_ERROR",
        "failure_message": "Your card has insufficient balance.",
        "failure_type": FailureType.SUBSCRIPTION,
        "method": "card",
        "issuer": "HDFC",
        "customer": Customer(name="Ananya Rao", phone="+919876543210"),
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return WorkItem(**fields)  # type: ignore[arg-type]


NUDGE = Action(
    type=ActionType.CUSTOMER_NUDGE,
    channel=Channel.SMS,
    reason="Expired instrument: the customer must re-authorise.",
)


class RecordingChannel:
    """A channel that reports what it was asked and what it agreed to handle."""

    def __init__(self, name: Channel, *, handles: bool = True) -> None:
        self._name = name
        self._handles = handles
        self.handled_items: list[str] = []
        self.executed: list[str] = []

    @property
    def name(self) -> Channel:
        return self._name

    def can_handle(self, item: WorkItem) -> bool:
        self.handled_items.append(item.txn_id)
        return self._handles

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        self.executed.append(item.txn_id)
        return ChannelResult(
            delivered=True,
            recovered=False,
            detail=f"{self._name} delivered for {item.txn_id}.",
            provider_ref="SM8fH2kQpR7sVdWx",
        )


class ContactAwareChannel:
    """A realistic can_handle: an SMS channel cannot text a customer with no phone."""

    @property
    def name(self) -> Channel:
        return Channel.SMS

    def can_handle(self, item: WorkItem) -> bool:
        return bool((item.customer.phone or "").strip())

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        return ChannelResult(
            delivered=True,
            recovered=False,
            detail=f"Re-authorisation SMS delivered to {item.customer.phone}.",
        )


class StubGateway:
    """A minimal PaymentGateway, present to prove the protocol is satisfiable."""

    async def get_transaction(self, txn_id: str) -> GatewayTxn:
        return GatewayTxn(
            txn_id=txn_id, amount_paise=249900, status="failed", method="card", issuer="HDFC"
        )

    async def fetch_failure_reason(self, txn_id: str) -> FailureContext:
        return FailureContext(
            failure_code="BAD_REQUEST_ERROR",
            failure_message="Your card has insufficient balance.",
            method="card",
            issuer="HDFC",
            failure_type=FailureType.SUBSCRIPTION,
            amount_paise=249900,
        )

    async def retry_payment(self, txn_id: str, idempotency_key: str) -> ExecutionResult:
        return ExecutionResult(
            recovered=True,
            channel=Channel.PAYMENT_RETRY,
            detail=f"Retry {idempotency_key} captured 249900 paise.",
            provider_ref=f"{txn_id}/rt1",
        )

    async def send_payment_link(self, txn_id: str) -> str:
        return f"https://rzp.io/i/{txn_id}"


class StubLLM:
    """A minimal LLMClient. Returns None for anything it is unsure of, as required."""

    async def classify(self, ctx: FailureContext) -> Diagnosis | None:
        if "balance" not in ctx.failure_message:
            return None
        return Diagnosis(
            cause=Cause.INSUFFICIENT_FUNDS,
            confidence=0.91,
            rationale="The failure message names an insufficient balance.",
            source="llm",
        )


# --------------------------------------------------------------------------- #
# NullBreaker
# --------------------------------------------------------------------------- #


def test_null_breaker_satisfies_the_breaker_state_protocol() -> None:
    """Phase 7 substitutes the real CircuitBreaker; both must be the same shape."""
    assert isinstance(NullBreaker(), BreakerState)


@pytest.mark.parametrize(
    "route",
    ["card:hdfc", "upi:unknown", "unknown:unknown", "netbanking:icici", ""],
)
def test_null_breaker_is_closed_for_every_route(route: str) -> None:
    """No counters means no evidence of degradation, so nothing may be barred."""
    assert NullBreaker().is_open(route) is False


def test_null_breaker_does_not_accumulate_state() -> None:
    """It is stateless: the thousandth call answers exactly as the first."""
    breaker = NullBreaker()

    assert [breaker.is_open("card:hdfc") for _ in range(1000)] == [False] * 1000


# --------------------------------------------------------------------------- #
# ChannelRegistry — the empty case
# --------------------------------------------------------------------------- #


def test_resolve_returns_none_when_nothing_is_registered() -> None:
    """Real behaviour, not a gap: the executor escalates "no channel available"."""
    registry = ChannelRegistry()

    assert registry.resolve(Channel.SMS, make_work_item()) is None
    assert len(registry) == 0


@pytest.mark.parametrize("channel", list(Channel))
def test_an_empty_registry_resolves_no_channel_at_all(channel: Channel) -> None:
    assert ChannelRegistry().resolve(channel, make_work_item()) is None


def test_resolve_chain_is_empty_when_nothing_is_registered() -> None:
    registry = ChannelRegistry()

    chain = registry.resolve_chain([Channel.VOICE, Channel.SMS, Channel.EMAIL], make_work_item())

    assert chain == []


# --------------------------------------------------------------------------- #
# ChannelRegistry — registration and resolution
# --------------------------------------------------------------------------- #


def test_resolve_returns_a_registered_channel_that_can_handle_the_item() -> None:
    registry = ChannelRegistry()
    sms = RecordingChannel(Channel.SMS)
    registry.register(sms)
    item = make_work_item()

    resolved = registry.resolve(Channel.SMS, item)

    assert resolved is sms
    assert sms.handled_items == [item.txn_id]
    assert Channel.SMS in registry
    assert len(registry) == 1


def test_resolve_returns_none_when_the_channel_cannot_handle_the_item() -> None:
    """Registered but inapplicable is the same answer as absent: no channel."""
    registry = ChannelRegistry()
    registry.register(RecordingChannel(Channel.SMS, handles=False))

    assert registry.resolve(Channel.SMS, make_work_item()) is None
    assert Channel.SMS in registry


def test_resolve_asks_the_named_channel_only() -> None:
    registry = ChannelRegistry()
    sms = RecordingChannel(Channel.SMS)
    email = RecordingChannel(Channel.EMAIL)
    registry.register(sms)
    registry.register(email)

    registry.resolve(Channel.EMAIL, make_work_item())

    assert sms.handled_items == []
    assert email.handled_items == ["pay_QjK9x2LmN4TzAb"]


def test_resolve_is_decided_per_item_not_per_channel() -> None:
    """The same SMS channel handles a reachable customer and refuses an unreachable one."""
    registry = ChannelRegistry()
    registry.register(ContactAwareChannel())

    reachable = make_work_item(customer=Customer(name="Ananya", phone="+919876543210"))
    unreachable = make_work_item(customer=Customer(name="Rohit"))

    assert registry.resolve(Channel.SMS, reachable) is not None
    assert registry.resolve(Channel.SMS, unreachable) is None


def test_registering_a_duplicate_channel_name_raises() -> None:
    """Two implementations claiming `sms` would make behaviour depend on import order."""
    registry = ChannelRegistry()
    registry.register(RecordingChannel(Channel.SMS))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(RecordingChannel(Channel.SMS))

    assert len(registry) == 1


# --------------------------------------------------------------------------- #
# ChannelRegistry.resolve_chain
# --------------------------------------------------------------------------- #


def test_resolve_chain_preserves_the_requested_order() -> None:
    """Order is preference: voice, then SMS, then email for a high-value nudge."""
    registry = ChannelRegistry()
    voice = RecordingChannel(Channel.VOICE)
    sms = RecordingChannel(Channel.SMS)
    email = RecordingChannel(Channel.EMAIL)
    for channel in (email, sms, voice):
        registry.register(channel)

    chain = registry.resolve_chain([Channel.VOICE, Channel.SMS, Channel.EMAIL], make_work_item())

    assert chain == [voice, sms, email]


def test_resolve_chain_drops_channels_that_cannot_handle_the_item() -> None:
    registry = ChannelRegistry()
    voice = RecordingChannel(Channel.VOICE, handles=False)
    sms = RecordingChannel(Channel.SMS)
    email = RecordingChannel(Channel.EMAIL, handles=False)
    for channel in (voice, sms, email):
        registry.register(channel)

    chain = registry.resolve_chain([Channel.VOICE, Channel.SMS, Channel.EMAIL], make_work_item())

    assert chain == [sms]


def test_resolve_chain_drops_unregistered_names_without_placeholders() -> None:
    """The returned list is exactly what can be attempted, with no gaps to skip over."""
    registry = ChannelRegistry()
    sms = RecordingChannel(Channel.SMS)
    registry.register(sms)

    chain = registry.resolve_chain(
        [Channel.VOICE, Channel.SMS, Channel.EMAIL, Channel.HUMAN_QUEUE], make_work_item()
    )

    assert chain == [sms]


def test_resolve_chain_of_no_names_is_empty() -> None:
    registry = ChannelRegistry()
    registry.register(RecordingChannel(Channel.SMS))

    assert registry.resolve_chain([], make_work_item()) == []


def test_resolve_chain_keeps_a_repeated_name_twice() -> None:
    """A deliberate second attempt down the same channel is a legitimate chain."""
    registry = ChannelRegistry()
    sms = RecordingChannel(Channel.SMS)
    registry.register(sms)

    chain = registry.resolve_chain([Channel.SMS, Channel.SMS], make_work_item())

    assert chain == [sms, sms]


def test_resolve_chain_accepts_any_iterable_not_only_a_list() -> None:
    """The policy may hand over a generator; consuming it once must be enough."""
    registry = ChannelRegistry()
    sms = RecordingChannel(Channel.SMS)
    voice = RecordingChannel(Channel.VOICE)
    registry.register(sms)
    registry.register(voice)

    chain = registry.resolve_chain((c for c in (Channel.VOICE, Channel.SMS)), make_work_item())

    assert chain == [voice, sms]


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_a_channel_implementation_satisfies_the_recovery_channel_protocol() -> None:
    assert isinstance(RecordingChannel(Channel.SMS), RecoveryChannel)
    assert isinstance(ContactAwareChannel(), RecoveryChannel)


def test_a_gateway_implementation_satisfies_the_payment_gateway_protocol() -> None:
    assert isinstance(StubGateway(), PaymentGateway)


def test_an_llm_implementation_satisfies_the_llm_client_protocol() -> None:
    assert isinstance(StubLLM(), LLMClient)


@pytest.mark.parametrize(
    ("protocol", "impostor"),
    [
        (PaymentGateway, NullBreaker()),
        (RecoveryChannel, NullBreaker()),
        (LLMClient, NullBreaker()),
        (BreakerState, StubGateway()),
    ],
)
def test_an_unrelated_object_does_not_satisfy_a_protocol(protocol: type, impostor: object) -> None:
    """The conformance assertions above would be worthless if everything passed."""
    assert not isinstance(impostor, protocol)


# --------------------------------------------------------------------------- #
# The declared async surfaces actually work end to end
# --------------------------------------------------------------------------- #


async def test_a_resolved_channel_executes_and_reports_delivery_and_recovery() -> None:
    registry = ChannelRegistry()
    registry.register(ContactAwareChannel())
    item = make_work_item()

    channel = registry.resolve(Channel.SMS, item)
    assert channel is not None
    result = await channel.execute(item, NUDGE)

    assert result.delivered is True
    assert result.recovered is False
    assert "+919876543210" in result.detail


async def test_the_gateway_protocol_round_trips_its_four_methods() -> None:
    gateway: PaymentGateway = StubGateway()

    txn = await gateway.get_transaction("pay_QjK9x2LmN4TzAb")
    context = await gateway.fetch_failure_reason("pay_QjK9x2LmN4TzAb")
    retry = await gateway.retry_payment("pay_QjK9x2LmN4TzAb", "idem-1")
    link = await gateway.send_payment_link("pay_QjK9x2LmN4TzAb")

    assert txn.amount_paise == 249900
    assert context.route == "card:hdfc"
    assert retry.recovered is True
    assert retry.channel is Channel.PAYMENT_RETRY
    assert link.endswith("pay_QjK9x2LmN4TzAb")


async def test_the_llm_protocol_returns_none_rather_than_guessing() -> None:
    """None is the whole failure vocabulary; an unvalidated cause never escapes."""
    llm: LLMClient = StubLLM()
    undecidable = FailureContext(
        failure_code="GATEWAY_ERROR",
        failure_message="Payment processing failed.",
        failure_type=FailureType.ONE_TIME,
        amount_paise=249900,
    )

    assert await llm.classify(undecidable) is None

    decidable = FailureContext(
        failure_code="BAD_REQUEST_ERROR",
        failure_message="Your card has insufficient balance.",
        failure_type=FailureType.ONE_TIME,
        amount_paise=249900,
    )
    diagnosis = await llm.classify(decidable)

    assert diagnosis is not None
    assert diagnosis.cause is Cause.INSUFFICIENT_FUNDS
    assert diagnosis.source == "llm"


# --------------------------------------------------------------------------- #
# GatewayTxn
# --------------------------------------------------------------------------- #


def test_gateway_txn_keeps_the_provider_status_string_unmodified() -> None:
    """Coercing an unrecognised status into a known bucket would misreport the fact."""
    txn = GatewayTxn(txn_id="pay_X", amount_paise=100, status="authorized_pending_capture")

    assert txn.status == "authorized_pending_capture"
    assert txn.method is None
    assert txn.issuer is None


def test_gateway_txn_enforces_integer_paise() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GatewayTxn(txn_id="pay_X", amount_paise=99.99, status="failed")  # type: ignore[arg-type]


def test_work_item_state_is_untouched_by_channel_resolution() -> None:
    """Resolution is a query. Only the state machine may move a work item."""
    registry = ChannelRegistry()
    registry.register(RecordingChannel(Channel.SMS))
    item = make_work_item()

    registry.resolve(Channel.SMS, item)
    registry.resolve_chain([Channel.SMS], item)

    assert item.state is State.DETECTED

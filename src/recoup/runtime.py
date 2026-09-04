"""The composition root: wire the whole recovery stack together in one place.

Every phase built one layer behind an interface; something has to assemble them,
and that assembly is a real architectural surface, not glue to scatter. Both the
batch runner (Phase 8) and the FastAPI app (Phase 9) need the *same* wiring — the
same shared clock, the one circuit breaker that both the gate and the retry channel
hold, the registry the executor resolves against — so it lives here once and is
reused, rather than being rebuilt (and subtly diverging) at each entry point.

This module is also the single sanctioned place that imports
:mod:`recoup.channels` in order to *register* a channel. Registration is not
execution: it only makes a channel resolvable, and the executor remains the sole
caller of :meth:`RecoveryChannel.execute`. ``tests/architecture/test_single_door.py``
allows this module by name alongside the executor for exactly that reason — a
reviewer can read the few lines below and confirm no channel is ever executed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from recoup.channels.base import ChannelRegistry
from recoup.channels.factory import build_nudge_channels
from recoup.channels.retry import PaymentRetryChannel
from recoup.channels.router import ChannelRouter
from recoup.clock import Clock
from recoup.config import Settings
from recoup.constraints.gate import ConstraintGate
from recoup.constraints.rules import default_rules
from recoup.diagnosis.base import LLMClient
from recoup.diagnosis.engine import DiagnosisEngine
from recoup.diagnosis.rules import RulesTable
from recoup.domain.models import Action, Diagnosis, WorkItem
from recoup.events import EventSink
from recoup.execution.executor import ActionExecutor
from recoup.execution.pipeline import GatePipeline
from recoup.fsm.machine import StateMachine
from recoup.fsm.orchestrator import Orchestrator, OrchestratorDeps
from recoup.gateways.base import PaymentGateway
from recoup.gateways.circuit_breaker import CircuitBreaker
from recoup.ingestion.idempotency import Ingestor
from recoup.policy.selector import select_action
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo

__all__ = ["RecoveryRuntime", "build_recovery_runtime"]


@dataclass(frozen=True)
class RecoveryRuntime:
    """Every wired collaborator an entry point needs to run the recovery loop.

    A single value object so a caller can pull out exactly the pieces it drives —
    the batch runner needs the ingestor, orchestrator, repo, audit and breaker; the
    API additionally exposes the gateway and gate — without re-deriving the wiring.
    """

    repo: WorkItemRepo
    audit: AuditLog
    machine: StateMachine
    breaker: CircuitBreaker
    gateway: PaymentGateway
    diagnosis_engine: DiagnosisEngine
    gate: ConstraintGate
    registry: ChannelRegistry
    executor: ActionExecutor
    pipeline: GatePipeline
    orchestrator: Orchestrator
    ingestor: Ingestor


def build_recovery_runtime(
    engine: Engine,
    clock: Clock,
    gateway: PaymentGateway,
    *,
    max_retries: int = 3,
    max_amount_paise: int = 5_000_000,
    min_llm_confidence: float = 0.7,
    llm: LLMClient | None = None,
    webhook_secret: str | None = None,
    sink: EventSink | None = None,
    settings: Settings | None = None,
) -> RecoveryRuntime:
    """Assemble the full recovery stack around one engine, clock and gateway.

    The circuit breaker is shared between the constraint gate (which asks whether a
    route is open) and the retry channel (which records outcomes against it), and
    ``clock`` is shared with the gateway, the breaker and the retry-timing policy —
    sharing those two instances is what makes the breaker a closed loop and the
    Phase 8 fast-forward coherent. ``llm`` defaults to ``None`` so the stack runs on
    the rules tier alone with an empty ``.env`` (Phase 11 supplies the Groq client).
    """
    repo = WorkItemRepo(engine)
    audit = AuditLog(engine)
    machine = StateMachine(engine, audit, repo, clock, sink=sink)

    breaker = CircuitBreaker(clock=clock)
    diagnosis_engine = DiagnosisEngine(RulesTable(), llm=llm, min_confidence=min_llm_confidence)
    gate = ConstraintGate(
        default_rules(max_retries=max_retries, max_amount_paise=max_amount_paise, breaker=breaker),
        clock=clock,
    )
    registry = ChannelRegistry()
    registry.register(PaymentRetryChannel(gateway, breaker))
    if settings is not None:
        for channel in build_nudge_channels(settings, gateway):
            registry.register(channel)
    nudge_router = ChannelRouter(registry, audit, clock)
    executor = ActionExecutor(gate, registry, nudge_router)
    pipeline = GatePipeline(
        gate,
        executor,
        clock,
        sink,
        max_amount_paise=max_amount_paise,
        max_retries=max_retries,
    )

    async def diagnose(item: WorkItem) -> Diagnosis:
        return await diagnosis_engine.diagnose(item)

    def select(item: WorkItem, diagnosis: Diagnosis) -> Action:
        return select_action(item, diagnosis, clock=clock)

    deps = OrchestratorDeps(
        diagnose=diagnose,
        select_action=select,
        check_and_execute=pipeline.check_and_execute,
    )
    orchestrator = Orchestrator(machine, deps, clock)
    ingestor = Ingestor(repo, clock, webhook_secret=webhook_secret)

    return RecoveryRuntime(
        repo=repo,
        audit=audit,
        machine=machine,
        breaker=breaker,
        gateway=gateway,
        diagnosis_engine=diagnosis_engine,
        gate=gate,
        registry=registry,
        executor=executor,
        pipeline=pipeline,
        orchestrator=orchestrator,
        ingestor=ingestor,
    )

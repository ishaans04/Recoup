"""The batch CLI: ``uv run python -m recoup.batch --n 50 --seed 42 --report``.

Runs the full recovery loop over a freshly generated synthetic batch against a
seeded :class:`~recoup.gateways.mock.MockGateway`, in a private throwaway SQLite
database, and prints the report. This is a demo artifact (PRD §15.1, §16): the
default text output is written to be read aloud from a terminal — the recovered
figure in lakh-grouped rupees, the recovery rate, the by-cause and by-channel
breakdowns, the constraint rejections, and then the full, un-cherry-picked
exception list with a specific reason for each (PRD §13.4). ``--json`` emits the
same report as machine-readable JSON for tooling.

The clock starts at a fixed instant so a run is reproducible end to end, and the
database lives in a temporary directory that is deleted when the process exits, so
running the CLI never touches a developer's real ``recoup.db``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import tempfile
from datetime import datetime

from recoup.batch.generator import build_gateway, generate_batch
from recoup.batch.runner import build_batch_runner
from recoup.clock import IST, SimulatedClock
from recoup.config import Settings
from recoup.diagnosis.factory import build_llm
from recoup.metrics import BatchReport
from recoup.money import format_inr_paise
from recoup.storage.db import create_engine_for, init_schema

_DEFAULT_START = datetime(2026, 9, 4, 11, 0, 0, tzinfo=IST)
"""A fixed, in-window start instant so the printed report is identical run to run."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m recoup.batch",
        description="Run the Recoup recovery loop over a synthetic batch and report.",
    )
    parser.add_argument("--n", type=int, default=50, help="number of transactions (default 50)")
    parser.add_argument("--seed", type=int, default=42, help="generator seed (default 42)")
    parser.add_argument(
        "--report",
        action="store_true",
        help="print the human-readable report (the default when no format is given)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead")
    return parser.parse_args(argv)


def _report_to_json(report: BatchReport) -> str:
    """Serialise a report to JSON, rendering enums and datetimes as strings."""

    def _default(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.asdict(value)
        return str(value)

    payload = {
        "run_id": report.run_id,
        "total_transactions": report.total_transactions,
        "total_at_risk_paise": report.total_at_risk_paise,
        "total_recovered_paise": report.total_recovered_paise,
        "recovery_rate": report.recovery_rate,
        "recovered_count": report.recovered_count,
        "by_cause": {
            cause.value: dataclasses.asdict(stats) for cause, stats in report.by_cause.items()
        },
        "by_channel": {channel.value: count for channel, count in report.by_channel.items()},
        "constraint_rejections": [dataclasses.asdict(r) for r in report.constraint_rejections],
        "escalations": [dataclasses.asdict(e) for e in report.escalations],
        "exceptions": [
            {
                "txn_id": exc.txn_id,
                "amount_paise": exc.amount_paise,
                "cause": exc.cause.value if exc.cause else None,
                "final_state": exc.final_state.value,
                "reason": exc.reason,
            }
            for exc in report.exceptions
        ],
        "diagnosis_sources": dict(report.diagnosis_sources),
        "breaker_trips": dict(report.breaker_trips),
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
    }
    return json.dumps(payload, indent=2, default=_default)


async def _run(n: int, seed: int) -> BatchReport:
    """Build a private database, a seeded gateway and the runner, then run the batch."""
    with tempfile.TemporaryDirectory(prefix="recoup-batch-") as tmp_dir:
        db_path = f"{tmp_dir}/batch.db".replace("\\", "/")
        settings = Settings(database_url=f"sqlite:///{db_path}")
        engine = create_engine_for(settings)
        init_schema(engine)
        try:
            clock = SimulatedClock(start=_DEFAULT_START)
            payloads = generate_batch(n, seed=seed, clock=clock)
            gateway = build_gateway(clock, n=n, seed=seed)
            runner = build_batch_runner(
                engine,
                clock,
                gateway,
                min_llm_confidence=settings.min_llm_confidence,
                llm=build_llm(settings, clock),
            )
            return await runner.run(payloads, run_id=f"cli-n{n}-seed{seed}")
        finally:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(_run(args.n, args.seed))

    if args.json:
        print(_report_to_json(report))
    else:
        print(report.render_text())
        print()
        print(
            f"Headline: recovered {format_inr_paise(report.total_recovered_paise)} of "
            f"{format_inr_paise(report.total_at_risk_paise)} at risk "
            f"({report.recovery_rate:.1%}), {len(report.exceptions)} honest exceptions."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

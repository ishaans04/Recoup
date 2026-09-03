# Recoup — backend

The money-safe core: state machine, diagnosis engine, constraint gate, audit log and
the adapters for every external service.

Specification: [`prd.md`](../prd.md). Service contract: [`docs/interface-contract.md`](../docs/interface-contract.md).

## Requirements

- Python 3.13 (pinned in `.python-version`; `uv` will fetch it)
- [`uv`](https://docs.astral.sh/uv/)

## Setup

```
uv sync
```

No credentials are required. Every external service key is optional; with an empty
environment the application runs in `mock` mode and selects mock adapters.

## Commands

| Task | Command |
|---|---|
| Tests | `uv run pytest -q` |
| Coverage | `uv run pytest --cov=recoup --cov-report=term-missing` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Types | `uv run mypy src` |

`mypy` runs in strict mode over `src/recoup`. Findings are fixed in the code; the
setting is not relaxed.

## Layout

```
src/recoup/
├── __init__.py
├── clock.py            Clock protocol, SystemClock, SimulatedClock
├── config.py           pydantic-settings; every credential optional
├── domain/
│   ├── enums.py        State, Cause, ActionType, Channel, FailureType
│   └── models.py       WorkItem, AuditEvent, Diagnosis, Action, ...
├── gateways/base.py    PaymentGateway protocol, GatewayTxn
├── channels/base.py    RecoveryChannel protocol, ChannelRegistry
├── diagnosis/base.py   LLMClient protocol
└── constraints/base.py BreakerState protocol, NullBreaker
tests/unit/             Unit tests
```

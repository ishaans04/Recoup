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

## Running the service

```
uv run uvicorn recoup.api.app:app --port 8000
```

Serves the webhook (`POST /webhooks/razorpay`), the REST surface under `/api`, and
the WebSocket stream at `/ws`, all per [`docs/interface-contract.md`](../docs/interface-contract.md).
With an empty `.env` the service runs in `mock` mode; `GET /api/health` reports the
mode. `POST /api/batch/run` drives a synthetic batch and streams `batch.progress`
and `batch.completed` over `/ws`; `POST /api/demo/inject` injects the Rs 75,000
guardrail case through the real gate.

Headless batch (no server): `uv run python -m recoup.batch --n 50 --seed 42 --report`.

## Generating the frontend API types

The dashboard's TypeScript types are generated from this service's OpenAPI schema,
so a contract drift breaks the frontend build rather than the demo. With the server
running on port 8000:

```
npm --prefix ../frontend run gen:types
```

This writes `frontend/src/lib/api-types.d.ts` from `http://localhost:8000/openapi.json`
(via `openapi-typescript`). Requires network access the first time to fetch the
generator.

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

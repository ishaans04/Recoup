# Recoup

An autonomous, money-safe revenue-recovery agent for Razorpay merchants: it detects
failed payments and renewals, diagnoses *why* each failed, and executes a **bounded**
recovery workflow — an LLM diagnoses, a deterministic state machine decides, a single
constraint gate guards every money action, and an append-only audit log proves it.

Specification: [`prd.md`](prd.md). Service contract: [`docs/interface-contract.md`](docs/interface-contract.md).

The Python backend (`src/recoup`, `tests/`) and the Next.js dashboard
(`src/app`, `src/components`, `src/lib`) live in one flat repository and share the
`src/` root; each toolchain uses its own config at the root.

## Backend

Requirements: Python 3.13 (pinned in `.python-version`; `uv` fetches it) and
[`uv`](https://docs.astral.sh/uv/).

```
uv sync
```

No credentials are required. Every external service key is optional; with an empty
`.env` the application runs in `mock` mode and selects mock adapters.

| Task | Command |
|---|---|
| Tests | `uv run pytest -q` |
| Coverage | `uv run pytest --cov=recoup --cov-report=term-missing` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Types | `uv run mypy src` |

`mypy` runs in strict mode over `src/recoup`; findings are fixed in the code, the
setting is not relaxed.

### Running the service

```
uv run uvicorn recoup.api.app:app --port 8000
```

Serves the webhook (`POST /webhooks/razorpay`), the REST surface under `/api`, and
the WebSocket stream at `/ws`, all per [`docs/interface-contract.md`](docs/interface-contract.md).
With an empty `.env` the service runs in `mock` mode; `GET /api/health` reports the
mode. `POST /api/batch/run` drives a synthetic batch and streams `batch.progress` and
`batch.completed` over `/ws`; `POST /api/demo/inject` injects the Rs 75,000 guardrail
case through the real gate.

Headless batch (no server): `uv run python -m recoup.batch --n 50 --seed 42 --report`.

Live integrations are credential-gated and documented in
[`docs/razorpay-setup.md`](docs/razorpay-setup.md) and
[`docs/voice-setup.md`](docs/voice-setup.md).

## Dashboard

Requirements: Node 20 or newer and npm.

```
npm install
npm run dev
```

The console runs at <http://localhost:3000> and expects the backend at
<http://localhost:8000>. It renders with no backend running; the header's link light
reports what it actually found. Set `NEXT_PUBLIC_API_BASE_URL` in `.env.local` to
point at a non-local backend (the WebSocket URL is derived from it).

| Task | Command |
|---|---|
| Dev server | `npm run dev` |
| Production build | `npm run build` |
| Lint | `npm run lint` |
| Unit tests | `npm test` |

### Generating the API types

The dashboard's TypeScript types are generated from the backend's OpenAPI schema, so
a contract drift breaks the frontend build rather than the demo. With the server
running on port 8000:

```
npm run gen:types
```

This writes `src/lib/api-types.d.ts` from `http://localhost:8000/openapi.json` via
`openapi-typescript` (needs network the first time to fetch the generator). Until it
is run, `src/lib/types.ts` is a hand-written mirror of the frozen contract.

## Layout

```
src/
├── recoup/            Python backend — the money-safe core and every adapter
│   ├── domain/        enums, models (WorkItem, AuditEvent, Diagnosis, Action, …)
│   ├── fsm/           state machine + orchestrator
│   ├── constraints/   the single gate (the only door to a money action)
│   ├── diagnosis/     two-tier engine (rules + Groq)
│   ├── policy/        cause→action selector, retry timing, channel policy
│   ├── gateways/      PaymentGateway adapter, mock + Razorpay, circuit breaker
│   ├── channels/      retry, SMS, email, voice + the audited fallback router
│   ├── execution/     the gated executor
│   ├── storage/       append-only audit trail + work-item repo
│   └── api/           FastAPI: webhooks, REST, WebSocket, voice callbacks
├── app/               Next.js app router
├── components/        dashboard panels
└── lib/               typed API + WebSocket clients, formatting
tests/                 backend unit / integration / contract / architecture tests
docs/                  interface contract and setup runbooks
```

Money is integer **paise** everywhere; the dashboard divides by 100 only at display.
Every money action passes the gate; every transition is appended to the audit log.

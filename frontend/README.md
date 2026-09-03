# Recoup — dashboard

The recovery console: the live view of what Recoup detected, diagnosed, refused and
recovered, and the proof that every money action passed the gate (PRD section 8.8).

Specification: [`prd.md`](../prd.md). Service contract: [`docs/interface-contract.md`](../docs/interface-contract.md).

## Requirements

- Node 20 or newer
- npm

## Setup

```
npm install
npm run dev
```

The console runs at <http://localhost:3000> and expects the FastAPI backend at
<http://localhost:8000>. It starts and renders with no backend running; the link
light in the header reports what it actually found rather than assuming.

## Commands

| Task | Command |
|---|---|
| Dev server | `npm run dev` |
| Production build | `npm run build` |
| Lint | `npm run lint` |

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend origin. The WebSocket URL is derived from it, so the two cannot disagree. |

Set it in `frontend/.env.local` when pointing at a non-local backend. No variable
is required for local development.

## Layout

```
src/
├── app/
│   ├── globals.css       Console theme tokens
│   ├── layout.tsx        Root shell
│   └── page.tsx          The console
├── components/
│   └── BackendStatus.tsx Live link light; polls GET /api/health
└── lib/
    ├── config.ts         API and WebSocket URLs
    └── types.ts          Hand-written mirror of the backend contract
```

## Notes

`src/lib/types.ts` is written by hand from the frozen interface contract so the
dashboard can be built before the backend exists. Phase 9 replaces it with types
generated from the backend's OpenAPI schema, which turns any drift between the two
halves into a compile error. Until then, every string literal in that file must
match the contract exactly.

Two rules the contract places on this side:

- **Money is integer paise.** Divide by 100 at the point of display and nowhere
  else. `formatPaise` in `lib/types.ts` is the only place that conversion happens.
- **Render `state`; never infer it.** Unknown enum values are shown verbatim rather
  than dropped, because silently omitting a row from an audit view would break the
  claim the audit view exists to make.

The console is dark in every light. It is an operations surface read at a glance
in a dim room, so it does not follow the viewer's colour-scheme preference. No web
font is loaded either: a build-time font fetch is a network failure mode the design
does not need.

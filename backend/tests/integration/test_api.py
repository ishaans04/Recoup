"""Integration tests for the FastAPI surface (PRD §8.1, §8.8, §14; contract §3, §4).

Driven in-process through ``httpx.ASGITransport`` (HTTP) and a minimal in-loop ASGI
harness (the WebSocket) — no live server. The load-bearing cases are the webhook security
boundary (unsigned and tampered payloads are refused and write nothing; a duplicate
is an idempotent 200), the demo guardrail (the Rs 75,000 injection is refused by the
real gate and lands in the escalation queue), and the stream's reconnect backfill.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from recoup.api.app import create_app
from recoup.config import Settings
from recoup.ingestion.signature import compute_razorpay_signature

_SECRET = "whsec_test_recoup"


@pytest.fixture
def api_app() -> Iterator[FastAPI]:
    """A fresh app backed by a private temp SQLite database, with a webhook secret set."""
    with tempfile.TemporaryDirectory(prefix="recoup-api-") as tmp_dir:
        db_path = f"{tmp_dir}/api.db".replace("\\", "/")
        settings = Settings(
            _env_file=None,  # hermetic: never read the real .env
            database_url=f"sqlite:///{db_path}",
            razorpay_webhook_secret=_SECRET,
        )
        app = create_app(settings)
        try:
            yield app
        finally:
            app.state.ctx.engine.dispose()


@pytest_asyncio.fixture
async def client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _webhook_body(*, event_id: str, txn_id: str, amount: int = 249900) -> bytes:
    """A raw ``payment.failed`` envelope as bytes, as Razorpay would deliver it."""
    payload = {
        "entity": "event",
        "account_id": "acc_MerchantDemo01",
        "event": "payment.failed",
        "contains": ["payment"],
        "id": event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": txn_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "failed",
                    "method": "card",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Your card has insufficient balance.",
                    "card": {"issuer": "HDFC"},
                    "notes": {"customer_name": "Ananya Rao"},
                    "contact": "+919876543210",
                    "email": "ananya.rao@example.com",
                }
            }
        },
        "created_at": 1788509525,
    }
    return json.dumps(payload).encode("utf-8")


def _signed_headers(body: bytes) -> dict[str, str]:
    return {"X-Razorpay-Signature": compute_razorpay_signature(body, _SECRET)}


async def _run_batch_and_wait(client: httpx.AsyncClient, *, size: int = 12) -> str:
    """Start a batch and poll its status until it finishes; return the run_id."""
    response = await client.post("/api/batch/run", json={"size": size, "seed": 42})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    for _ in range(200):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/api/batch/{run_id}")).json()
        if status["status"] in ("completed", "failed"):
            assert status["status"] == "completed"
            return run_id
    raise AssertionError("batch did not complete in time")


# --- Health ------------------------------------------------------------------


async def test_health_reports_mock_mode(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/health")).json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"
    assert body["database"] == "ok"


# --- Webhook security boundary (PRD §14) -------------------------------------


async def test_unsigned_webhook_rejected_and_nothing_written(client: httpx.AsyncClient) -> None:
    body = _webhook_body(event_id="evt_unsigned", txn_id="pay_unsigned")
    response = await client.post("/webhooks/razorpay", content=body)  # no signature header
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"
    # Nothing was created.
    assert (await client.get("/api/workitems/pay_unsigned")).status_code == 404


async def test_tampered_body_rejected(client: httpx.AsyncClient) -> None:
    signed = _webhook_body(event_id="evt_a", txn_id="pay_a")
    tampered = _webhook_body(event_id="evt_a", txn_id="pay_a", amount=9999999)
    response = await client.post(
        "/webhooks/razorpay", content=tampered, headers=_signed_headers(signed)
    )
    assert response.status_code == 401
    assert (await client.get("/api/workitems/pay_a")).status_code == 404


async def test_valid_webhook_creates_work_item_and_returns_202(client: httpx.AsyncClient) -> None:
    body = _webhook_body(event_id="evt_ok", txn_id="pay_ok")
    response = await client.post("/webhooks/razorpay", content=body, headers=_signed_headers(body))
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "txn_id": "pay_ok", "duplicate": False}
    assert (await client.get("/api/workitems/pay_ok")).status_code == 200


async def test_duplicate_webhook_returns_200_and_does_not_reprocess(
    client: httpx.AsyncClient,
) -> None:
    body = _webhook_body(event_id="evt_dupe", txn_id="pay_dupe")
    headers = _signed_headers(body)
    first = await client.post("/webhooks/razorpay", content=body, headers=headers)
    second = await client.post("/webhooks/razorpay", content=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    # Exactly one work item exists for that txn.
    listing = (await client.get("/api/workitems")).json()
    assert sum(1 for item in listing["items"] if item["txn_id"] == "pay_dupe") == 1


# --- Reads over a real batch -------------------------------------------------


async def test_workitems_filters_by_state_and_paginates(client: httpx.AsyncClient) -> None:
    await _run_batch_and_wait(client)
    escalated = (await client.get("/api/workitems", params={"state": "ESCALATED"})).json()
    assert escalated["total"] >= 1
    assert all(item["state"] == "ESCALATED" for item in escalated["items"])

    first_page = (await client.get("/api/workitems", params={"limit": 3})).json()
    assert len(first_page["items"]) == 3
    assert first_page["next_cursor"] is not None
    second_page = (
        await client.get("/api/workitems", params={"limit": 3, "cursor": first_page["next_cursor"]})
    ).json()
    first_ids = {item["txn_id"] for item in first_page["items"]}
    second_ids = {item["txn_id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)  # no repeats across the page boundary


async def test_audit_since_id_returns_only_newer_rows_in_order(client: httpx.AsyncClient) -> None:
    await _run_batch_and_wait(client)
    full = (await client.get("/api/audit", params={"since_id": 0, "limit": 500})).json()
    assert len(full["events"]) > 0
    ids = [event["id"] for event in full["events"]]
    assert ids == sorted(ids)  # ascending

    midpoint = ids[len(ids) // 2]
    tail = (await client.get("/api/audit", params={"since_id": midpoint})).json()
    assert all(event["id"] > midpoint for event in tail["events"])


async def test_metrics_matches_the_batch_it_ran(client: httpx.AsyncClient) -> None:
    run_id = await _run_batch_and_wait(client)
    metrics = (await client.get("/api/metrics")).json()
    batch = (await client.get(f"/api/batch/{run_id}")).json()["metrics"]
    # The global metrics scan and the batch report derive from the same rows, so on
    # a fresh single-batch database they agree on every shared field.
    for field in (
        "total_failed",
        "total_failed_paise",
        "recovered",
        "recovered_paise",
        "escalated",
        "attempted",
        "recovery_rate",
    ):
        assert metrics[field] == batch[field], field


async def test_escalations_lists_the_over_cap_rejection(client: httpx.AsyncClient) -> None:
    await _run_batch_and_wait(client)
    escalations = (await client.get("/api/escalations")).json()
    assert escalations["total"] >= 1
    reasons = [entry["reason"] for entry in escalations["escalations"]]
    assert any("amount_cap" in reason for reason in reasons)


# --- Demo guardrail (PRD §16.5) ----------------------------------------------


async def test_demo_inject_75000_produces_a_gate_rejection(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/demo/inject", json={})  # defaults to the over-cap case
    assert response.status_code == 201
    txn_id = response.json()["txn_id"]

    audit = (await client.get(f"/api/workitems/{txn_id}/audit")).json()
    assert any(row["constraint_result"] == "FAIL" for row in audit["events"])
    assert any("amount_cap" in (row["constraint_reason"] or "") for row in audit["events"])

    item = (await client.get(f"/api/workitems/{txn_id}")).json()
    assert item["state"] == "ESCALATED"

    escalations = (await client.get("/api/escalations")).json()
    assert any(entry["txn_id"] == txn_id for entry in escalations["escalations"])


async def test_batch_run_returns_immediately_then_completes(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/batch/run", json={"size": 12, "seed": 42})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"  # returned before the work is done
    run_id = body["run_id"]

    for _ in range(200):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/api/batch/{run_id}")).json()
        if status["status"] == "completed":
            assert status["processed"] == 12
            return
    raise AssertionError("batch did not complete")


# --- OpenAPI contract lock ---------------------------------------------------


def test_openapi_exposes_exactly_the_contract_routes(api_app: FastAPI) -> None:
    paths = api_app.openapi()["paths"]
    actual = {(path, method.upper()) for path, ops in paths.items() for method in ops}
    expected = {
        ("/webhooks/razorpay", "POST"),
        ("/api/health", "GET"),
        ("/api/workitems", "GET"),
        ("/api/workitems/{txn_id}", "GET"),
        ("/api/workitems/{txn_id}/audit", "GET"),
        ("/api/audit", "GET"),
        ("/api/metrics", "GET"),
        ("/api/escalations", "GET"),
        ("/api/batch/run", "POST"),
        ("/api/batch/{run_id}", "GET"),
        ("/api/demo/inject", "POST"),
    }
    assert actual == expected


# --- WebSocket stream (contract §4) ------------------------------------------
#
# Driven through a minimal ASGI harness on the test's own event loop rather than
# Starlette's TestClient, whose background portal clashes with pytest-asyncio's
# auto mode. The harness speaks raw ASGI websocket messages to the same app object.


class _WSDriver:
    """A tiny in-loop ASGI websocket client: connect, send JSON, receive frames."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._to_server: asyncio.Queue[dict] = asyncio.Queue()
        self._from_server: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _WSDriver:
        await self._to_server.put({"type": "websocket.connect"})
        scope = {
            "type": "websocket",
            "path": "/ws",
            "raw_path": b"/ws",
            "headers": [],
            "query_string": b"",
            "client": ("test", 0),
            "server": ("test", 80),
            "scheme": "ws",
            "subprotocols": [],
            "app": self._app,
        }
        self._task = asyncio.ensure_future(
            self._app(scope, self._to_server.get, self._from_server.put)
        )
        accept = await asyncio.wait_for(self._from_server.get(), timeout=5)
        assert accept["type"] == "websocket.accept"
        return self

    async def send_json(self, data: dict) -> None:
        await self._to_server.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def recv_json(self) -> dict:
        message = await asyncio.wait_for(self._from_server.get(), timeout=5)
        result: dict = json.loads(message["text"])
        return result

    async def __aexit__(self, *exc: object) -> None:
        await self._to_server.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=5)


async def test_ws_hello_ack_then_backfills_in_seq_order(
    api_app: FastAPI, client: httpx.AsyncClient
) -> None:
    await client.post("/api/demo/inject", json={})  # generate a burst of frames
    async with _WSDriver(api_app) as ws:
        await ws.send_json({"type": "hello", "last_seq": 0})
        ack = await ws.recv_json()
        assert ack["type"] == "hello.ack"
        assert ack["payload"]["mode"] == "mock"
        count = ack["payload"]["backfill_count"]
        assert count > 0
        frames = [await ws.recv_json() for _ in range(count)]
        seqs = [frame["seq"] for frame in frames]
        assert seqs == sorted(seqs)
        assert {frame["type"] for frame in frames} >= {"gate.rejected", "audit.appended"}


async def test_ws_reconnect_with_last_seq_backfills_only_missed(
    api_app: FastAPI, client: httpx.AsyncClient
) -> None:
    await client.post("/api/demo/inject", json={})
    async with _WSDriver(api_app) as ws:
        await ws.send_json({"type": "hello", "last_seq": 0})
        ack = await ws.recv_json()
        seen_up_to = ack["payload"]["current_seq"]
        for _ in range(ack["payload"]["backfill_count"]):
            await ws.recv_json()

    # More events happen while "disconnected".
    await client.post("/api/demo/inject", json={})
    async with _WSDriver(api_app) as ws:
        await ws.send_json({"type": "hello", "last_seq": seen_up_to})
        ack = await ws.recv_json()
        count = ack["payload"]["backfill_count"]
        assert count > 0
        frames = [await ws.recv_json() for _ in range(count)]
        # Only genuinely newer frames are replayed — nothing at or below last_seq.
        assert all(frame["seq"] > seen_up_to for frame in frames)

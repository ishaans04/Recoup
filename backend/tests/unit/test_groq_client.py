"""Tests for the Groq Tier-2 client (PRD §9.2, §13.1, §13.2, §13.3).

Every network interaction is mocked with ``respx``; no test needs a real API key.
The through-line is the :class:`~recoup.diagnosis.base.LLMClient` contract: the client
never raises and never returns an unvalidated cause, so every malformed, rate-limited
or failed response collapses to ``None`` — which is what stops a bad model response
from ever selecting a money action. One opt-in live test (``-m live``) does a single
real round-trip when a key is present.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

from recoup.clock import SimulatedClock
from recoup.diagnosis.groq_client import _GROQ_URL, GroqClient
from recoup.domain.enums import Cause, FailureType
from recoup.domain.models import FailureContext
from tests.conftest import CREATED_AT

_SECRET = "gsk_test_do_not_log_this_value_1234567890"


def _ctx(code: str = "BAD_REQUEST_ERROR") -> FailureContext:
    return FailureContext(
        failure_code=code,
        failure_message="A temporary problem occurred at the bank; please try later.",
        method="upi",
        issuer="SBIN",
        failure_type=FailureType.ONE_TIME,
        amount_paise=249900,
    )


def _groq_body(cause: str, confidence: float, rationale: str) -> dict:
    """A Groq chat-completion response whose content is the model's JSON answer."""
    content = json.dumps({"cause": cause, "confidence": confidence, "rationale": rationale})
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _recording_sleep(
    clock: SimulatedClock, recorded: list[float]
) -> Callable[[float], Awaitable[None]]:
    """A fake sleep that records its durations and advances the simulated clock."""

    async def sleep(seconds: float) -> None:
        recorded.append(seconds)
        clock.advance(timedelta(seconds=seconds))

    return sleep


def _client(clock: SimulatedClock, **kwargs: object) -> GroqClient:
    return GroqClient(_SECRET, clock=clock, **kwargs)  # type: ignore[arg-type]


@respx.mock
async def test_well_formed_response_yields_an_llm_diagnosis() -> None:
    respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(
            200, json=_groq_body("gateway_degradation", 0.82, "Route looks unhealthy.")
        )
    )
    result = await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx())
    assert result is not None
    assert result.cause is Cause.GATEWAY_DEGRADATION
    assert result.source == "llm"
    assert result.confidence == 0.82


@respx.mock
async def test_out_of_enum_cause_returns_none() -> None:
    respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(
            200, json=_groq_body("customer_confused", 0.9, "Made-up cause.")
        )
    )
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_confidence_out_of_range_returns_none() -> None:
    respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(
            200, json=_groq_body("soft_decline", 1.5, "Impossible confidence.")
        )
    )
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_empty_rationale_returns_none() -> None:
    respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(200, json=_groq_body("soft_decline", 0.7, "   "))
    )
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_non_json_content_returns_none() -> None:
    body = {"choices": [{"message": {"content": "not json at all"}}]}
    respx.post(_GROQ_URL).mock(return_value=httpx.Response(200, json=body))
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_500_returns_none() -> None:
    respx.post(_GROQ_URL).mock(return_value=httpx.Response(500, text="server error"))
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_timeout_returns_none_without_raising() -> None:
    respx.post(_GROQ_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    assert await _client(SimulatedClock(start=CREATED_AT)).classify(_ctx()) is None


@respx.mock
async def test_429_is_retried_honouring_retry_after_then_returns_none() -> None:
    clock = SimulatedClock(start=CREATED_AT)
    recorded: list[float] = []
    route = respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0.5"}, text="slow down")
    )
    result = await _client(clock, sleep=_recording_sleep(clock, recorded)).classify(_ctx())
    assert result is None
    # Initial attempt plus the retries, and every retry waited the Retry-After delay.
    assert route.call_count == 4  # 1 + _MAX_RETRIES
    assert recorded == [0.5, 0.5, 0.5]


async def test_rate_limiter_delays_the_31st_call_in_a_window() -> None:
    clock = SimulatedClock(start=CREATED_AT)
    recorded: list[float] = []
    client = _client(clock, rpm_limit=30, sleep=_recording_sleep(clock, recorded))
    for _ in range(30):
        await client._limiter.acquire()  # all inside one window, all admitted immediately
    assert recorded == []
    await client._limiter.acquire()  # the 31st must wait for the window to free a slot
    assert len(recorded) == 1
    assert recorded[0] > 0


@respx.mock
async def test_cache_hit_returns_stored_diagnosis_and_makes_no_http_call() -> None:
    route = respx.post(_GROQ_URL).mock(
        return_value=httpx.Response(200, json=_groq_body("insufficient_funds", 0.9, "Unfunded."))
    )
    # tempfile rather than pytest's tmp_path: the machine's pytest temp tree is
    # broken (see tests/conftest.py), so tests provision their own directories.
    with tempfile.TemporaryDirectory(prefix="recoup-groq-cache-") as tmp_dir:
        cache = Path(tmp_dir) / "cache.json"
        client = _client(SimulatedClock(start=CREATED_AT), cache_path=cache)
        first = await client.classify(_ctx())
        second = await client.classify(_ctx())  # identical context -> served from cache
        assert first == second
        assert route.call_count == 1  # the second call never touched the network

        # A brand-new client reading the same cache file also skips the network.
        fresh = _client(SimulatedClock(start=CREATED_AT), cache_path=cache)
        third = await fresh.classify(_ctx())
        assert third == first
        assert route.call_count == 1


@respx.mock
async def test_the_api_key_never_leaks_into_logs_or_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post(_GROQ_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    client = _client(SimulatedClock(start=CREATED_AT))
    assert _SECRET not in repr(client)
    with caplog.at_level(logging.DEBUG):
        await client.classify(_ctx())
    assert all(_SECRET not in record.getMessage() for record in caplog.records)


@pytest.mark.live
async def test_live_round_trip_when_a_key_is_present() -> None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        pytest.skip("no GROQ_API_KEY set")
    result = await GroqClient(key, clock=SimulatedClock(start=CREATED_AT)).classify(_ctx())
    # A live model may legitimately answer 'unknown'; the contract is only that the
    # result is either a validated Diagnosis or None, never a raise or a bad shape.
    if result is not None:
        assert result.source == "llm"
        assert 0.0 <= result.confidence <= 1.0

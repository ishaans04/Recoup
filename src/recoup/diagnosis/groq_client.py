"""The Groq Tier-2 classifier: one real implementation of :class:`LLMClient` (PRD §9.2).

Phase 4 built and tested the entire two-tier engine against a fake; this module is
the single real client it composes, and it changes nothing about the engine. Groq is
chosen for LPU-hosted open models at very low latency (PRD §9.2), so the ambiguous
tail of a 50-transaction batch resolves near-instantly on stage.

Every requirement here maps to a PRD failure-handling clause, and the through-line is
:class:`LLMClient`'s contract: **this never raises and never returns an unvalidated
cause.** ``None`` is the single signal for every failure — a timeout, a 4xx/5xx, a
429 whose retries were exhausted, a non-JSON body, a schema violation, an
out-of-enum cause, a confidence outside 0–1, an empty rationale. The engine turns
``None`` into a safe ``unknown``/``fallback``, which is what keeps a bad model
response from ever selecting a money action nobody authorised (PRD §13.2).

Three defences run in front of the network. A client-side rate limiter keeps calls
under the free tier's 30 RPM using the injected clock (PRD §13.1). A 429 is retried
honouring ``Retry-After``. And an on-disk cache keyed by the failure context means a
pre-cached classification serves with zero network and zero rate-limit budget, so a
live 429 can never stall the demo (PRD §13.3).

The API key is held privately and never logged, never put in an exception message,
and never rendered in a ``repr``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import httpx

from recoup.clock import Clock
from recoup.diagnosis.prompts import build_messages
from recoup.domain.enums import Cause
from recoup.domain.models import Diagnosis, FailureContext

__all__ = ["GroqClient"]

_LOG = logging.getLogger("recoup.diagnosis.groq")

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# openai/gpt-oss-120b is a current Groq-hosted model that supports JSON mode and
# follows the strict-JSON classification prompt reliably. The Llama 3.x models the
# PRD sketch named were retired from the free catalogue; this was confirmed against
# the live /models endpoint and a JSON-mode round trip during Phase 11.
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_WINDOW_SECONDS = 60.0
_MAX_RETRIES = 3
_VALID_CAUSES = {cause.value for cause in Cause}

Sleep = Callable[[float], Awaitable[None]]


class _RateLimiter:
    """A per-minute request limiter aged on the injected clock, not wall time.

    Records the clock time of each admitted call; a call is admitted immediately
    while fewer than ``rpm`` calls fall inside the trailing 60-second window, and
    otherwise waits (via the injected ``sleep``) until the oldest call ages out.
    Aging on the injected clock is what lets a test drive the limiter with a
    :class:`~recoup.clock.SimulatedClock` instead of real seconds.
    """

    def __init__(self, clock: Clock, rpm: int, sleep: Sleep) -> None:
        self._clock = clock
        self._rpm = max(1, rpm)
        self._sleep = sleep
        self._admitted: deque[datetime] = deque()

    async def acquire(self) -> None:
        while True:
            now = self._clock.now()
            while self._admitted and (now - self._admitted[0]).total_seconds() >= _WINDOW_SECONDS:
                self._admitted.popleft()
            if len(self._admitted) < self._rpm:
                self._admitted.append(now)
                return
            wait = _WINDOW_SECONDS - (now - self._admitted[0]).total_seconds()
            await self._sleep(max(wait, 0.0))


class GroqClient:
    """Classifies an ambiguous payment failure via Groq, or returns ``None``."""

    def __init__(
        self,
        api_key: str,
        *,
        clock: Clock,
        model: str = _DEFAULT_MODEL,
        cache_path: Path | None = None,
        timeout: float = 10.0,
        rpm_limit: int = 30,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        # Name-mangled and never exposed: not an ordinary attribute, never logged,
        # never rendered. The default object repr shows no attributes either.
        self.__api_key = api_key
        self._clock = clock
        self._model = model
        self._timeout = timeout
        self._sleep = sleep
        self._limiter = _RateLimiter(clock, rpm_limit, sleep)
        self._cache_path = cache_path
        self._cache = _load_cache(cache_path)

    async def classify(self, ctx: FailureContext) -> Diagnosis | None:
        """Return a validated Tier-2 :class:`Diagnosis`, or ``None`` on any failure."""
        key = _cache_key(ctx)
        cached = self._cache.get(key)
        if cached is not None:
            # A cache hit must not touch the network or spend rate-limit budget.
            return _diagnosis_from_dict(cached)

        try:
            payload = await self._request_with_retries(ctx)
        except Exception:  # noqa: BLE001 - the contract is to never raise; degrade to None
            _LOG.warning("Groq classification failed; falling back to rules tier")
            return None

        if payload is None:
            return None

        diagnosis = _parse_and_validate(payload)
        if diagnosis is None:
            return None

        self._store(key, diagnosis)
        return diagnosis

    async def _request_with_retries(self, ctx: FailureContext) -> dict[str, object] | None:
        """POST to Groq, honouring the rate limiter and retrying a 429. ``None`` on failure."""
        body = {
            "model": self._model,
            "messages": build_messages(ctx),
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 200,
        }
        headers = {"Authorization": f"Bearer {self.__api_key}", "Content-Type": "application/json"}

        for attempt in range(_MAX_RETRIES + 1):
            await self._limiter.acquire()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(_GROQ_URL, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError):
                return None

            if response.status_code == 429:
                if attempt >= _MAX_RETRIES:
                    return None
                await self._sleep(_retry_after_seconds(response, attempt))
                continue
            if response.status_code >= 400:
                return None

            try:
                data: dict[str, object] = response.json()
            except (json.JSONDecodeError, ValueError):
                return None
            return data

        return None  # pragma: no cover - the loop always returns first

    def _store(self, key: str, diagnosis: Diagnosis) -> None:
        self._cache[key] = diagnosis.model_dump(mode="json")
        _save_cache(self._cache_path, self._cache)


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """The delay before retrying a 429: the ``Retry-After`` header, or exponential backoff."""
    header = response.headers.get("Retry-After")
    if header is not None:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    return float(2**attempt)


def _parse_and_validate(payload: dict[str, object]) -> Diagnosis | None:
    """Extract the model's JSON answer and validate it, or return ``None``.

    Rejects anything the closed action space cannot afford: a non-JSON content body,
    a cause outside the enum, a confidence outside 0–1, or an empty rationale.
    """
    try:
        choices = payload["choices"]
        content = choices[0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None

    try:
        answer = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(answer, dict):
        return None

    cause = answer.get("cause")
    confidence = answer.get("confidence")
    rationale = answer.get("rationale")

    if cause not in _VALID_CAUSES:
        return None
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return None
    if not 0.0 <= float(confidence) <= 1.0:
        return None
    if not isinstance(rationale, str) or not rationale.strip():
        return None

    return Diagnosis(
        cause=Cause(cause),
        confidence=float(confidence),
        rationale=rationale.strip(),
        source="llm",
    )


def _diagnosis_from_dict(data: dict[str, object]) -> Diagnosis | None:
    """Rebuild a cached diagnosis; a corrupted cache entry is simply ignored."""
    try:
        return Diagnosis.model_validate(data)
    except Exception:  # noqa: BLE001 - a bad cache row must never break classification
        return None


def _cache_key(ctx: FailureContext) -> str:
    """A stable hash of the fields that determine a diagnosis."""
    raw = "|".join(
        [
            ctx.failure_code,
            ctx.failure_message,
            ctx.method or "",
            ctx.issuer or "",
            ctx.failure_type.value,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_cache(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_cache(path: Path | None, cache: dict[str, dict[str, object]]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    except OSError:
        # A cache that cannot be written is a performance loss, not a failure: the
        # next identical classification simply goes to the network again.
        _LOG.debug("could not persist Groq classification cache")

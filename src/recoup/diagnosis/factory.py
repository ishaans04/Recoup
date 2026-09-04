"""Selecting the Tier-2 client from configuration (PRD §9.2, §13.1).

One place decides whether the LLM tier is real or absent, so the app and the batch
CLI cannot disagree. A Groq key present yields a :class:`~recoup.diagnosis.groq_client.GroqClient`;
absent yields ``None``, which the diagnosis engine already handles as rules-only
diagnosis. The choice is logged at startup — never the key itself — so a run is
honest about whether Tier 2 was live.
"""

from __future__ import annotations

import logging
from pathlib import Path

from recoup.clock import Clock
from recoup.config import Settings
from recoup.diagnosis.base import LLMClient
from recoup.diagnosis.groq_client import GroqClient

__all__ = ["build_llm", "default_cache_path"]

_LOG = logging.getLogger("recoup.diagnosis")

_DEFAULT_CACHE = Path(".recoup_cache") / "groq_classifications.json"


def default_cache_path() -> Path:
    """The default on-disk classification cache path (gitignored)."""
    return _DEFAULT_CACHE


def build_llm(
    settings: Settings, clock: Clock, *, cache_path: Path | None = None
) -> LLMClient | None:
    """A :class:`GroqClient` when a Groq key is configured, else ``None`` (rules-only).

    ``cache_path`` defaults to the shared on-disk cache so repeated identical
    classifications across a demo are served without a network call.
    """
    if not settings.groq_api_key:
        _LOG.info("diagnosis: Tier-2 LLM disabled (no Groq key); using the rules tier alone")
        return None
    _LOG.info("diagnosis: Tier-2 LLM enabled (Groq)")
    return GroqClient(
        settings.groq_api_key,
        clock=clock,
        cache_path=cache_path if cache_path is not None else _DEFAULT_CACHE,
    )

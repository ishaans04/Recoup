"""The diagnosis engine: deterministic rules first, a language model second.

The LLM's entire authority is to return a
:class:`~recoup.domain.models.Diagnosis`. It never chooses an action and never
touches a gateway (PRD sections 4, 11).
"""

from recoup.diagnosis.base import LLMClient

__all__ = ["LLMClient"]

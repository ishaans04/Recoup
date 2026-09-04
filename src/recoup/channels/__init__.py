"""Recovery channels: the ways an approved action reaches the world.

Retry, SMS, email, voice and the human queue differ entirely in implementation and
not at all in shape, so the executor is written against one protocol and never
learns which channels exist (PRD section 8.7).
"""

from recoup.channels.base import ChannelRegistry, RecoveryChannel

__all__ = ["ChannelRegistry", "RecoveryChannel"]

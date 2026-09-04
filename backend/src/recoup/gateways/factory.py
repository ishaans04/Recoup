"""Selecting the payment gateway from configuration (PRD §9.3, §5.2).

``RECOUP_MODE=live`` with Razorpay credentials present selects the real
:class:`~recoup.gateways.razorpay.RazorpayGateway`; anything else selects the
:class:`~recoup.gateways.mock.MockGateway`. The safe mode is the one you get by
doing nothing, and a ``live`` mode with missing credentials degrades to the mock
with a warning rather than crashing — the money-safe core never depends on a live
account being configured.
"""

from __future__ import annotations

import logging

from recoup.clock import Clock
from recoup.config import Settings
from recoup.gateways.base import PaymentGateway
from recoup.gateways.mock import MockGateway
from recoup.gateways.razorpay import RazorpayGateway

__all__ = ["build_gateway_for"]

_LOG = logging.getLogger("recoup.gateways")


def build_gateway_for(settings: Settings, clock: Clock) -> PaymentGateway:
    """The live gateway: Razorpay in ``live`` mode with keys, otherwise the mock."""
    if settings.is_live and settings.razorpay_key_id and settings.razorpay_key_secret:
        _LOG.info("gateway: live Razorpay adapter")
        return RazorpayGateway(settings.razorpay_key_id, settings.razorpay_key_secret)
    if settings.is_live:
        _LOG.warning("RECOUP_MODE=live but Razorpay keys are missing; using the mock gateway")
    return MockGateway(clock=clock, seed=42)

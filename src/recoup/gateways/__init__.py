"""Payment service provider adapters.

Business logic depends on the :class:`~recoup.gateways.base.PaymentGateway`
protocol declared here and never on a provider SDK, which is what makes a second
PSP a new class rather than a change to the state machine (PRD sections 8.4, 9.3).
"""

from recoup.gateways.base import GatewayTxn, PaymentGateway

__all__ = ["GatewayTxn", "PaymentGateway"]

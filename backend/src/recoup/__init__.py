"""Recoup — an autonomous, money-safe revenue recovery agent.

Recoup detects failed payments and renewals, diagnoses *why* each one failed, and
executes a bounded recovery action that is provable after the fact.

The governing design principle (PRD section 4) is that recovery is a state machine,
not a chatbot: the LLM diagnoses, the state machine decides, the constraint gate
guards every money action, and the append-only audit log proves it.

Package layout, and the phase that fills each part in:

- ``domain``      — the shared vocabulary and models. Every other module imports it.
- ``clock``       — injectable time, so scheduled retries can be fast-forwarded in tests.
- ``config``      — credential-optional settings; an empty ``.env`` selects mock adapters.
- ``gateways``    — payment service provider adapters behind one protocol.
- ``channels``    — recovery channels (retry, SMS, email, voice) behind one protocol.
- ``diagnosis``   — the two-tier diagnosis engine: deterministic rules, then the LLM.
- ``constraints`` — the single gate through which every money action must pass.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]

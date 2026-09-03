"""Indian-format currency rendering for human-facing strings.

Amounts live everywhere else as integer paise (PRD §10.1). The moment one is shown
to a person — a constraint rejection on the dashboard, a line in the batch report,
a nudge message — it becomes lakh-grouped rupees, because that is the grouping an
Indian merchant reads without stumbling. ``Rs 1,20,500`` is legible where
``Rs 120,500`` is not, and the constraint gate's rejection string
``amount_cap: Rs 75,000 > Rs 50,000`` is put on stage verbatim (PRD §12.4, §16.5),
so the formatting is a demo artifact, not incidental.
"""

from __future__ import annotations

__all__ = ["format_inr_paise", "group_indian"]


def group_indian(rupees: int) -> str:
    """Group an integer rupee amount the Indian way: last three digits, then twos.

    ``75000 -> "75,000"``, ``120500 -> "1,20,500"``, ``100000000 -> "10,00,00,000"``.
    A negative amount keeps its sign; the grouping is applied to the magnitude.
    """
    digits = str(abs(rupees))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, last_three = digits[:-3], digits[-3:]
        pairs: list[str] = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        pairs.insert(0, head)
        grouped = ",".join(pairs) + "," + last_three
    return f"-{grouped}" if rupees < 0 else grouped


def format_inr_paise(paise: int) -> str:
    """Render integer paise as a lakh-grouped rupee string prefixed ``Rs ``.

    Whole rupees only: sub-rupee paise are truncated, because every amount this
    system moves in test mode is a whole-rupee figure and the human-facing strings
    (caps, rejections, reports) read cleaner without a trailing ``.00``.
    """
    return f"Rs {group_indian(paise // 100)}"

"""The root-cause action router (PRD section 10.3).

This package turns a :class:`~recoup.domain.models.Diagnosis` into a bounded
:class:`~recoup.domain.models.Action`: it decides *what* intervention follows from
a cause, *when* a retry should fire, and *which* channel should carry a customer
nudge. It never decides whether the action is *allowed* to run — that is the
constraint gate's authority alone (phase 6) — and it never talks to a gateway,
a phone line or an inbox itself (phases 7, 13, 14).
"""

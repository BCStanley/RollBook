"""Matching system.

Queries the candidate database against normalized targets: a rule-based
pass first, then a fuzzy-matching (rapidfuzz) fallback, producing ranked
candidates per target. Every candidate is tagged with a confidence score
and the rule that produced it, so review findings can be traced back to a
specific rule. Ported from `find_candidate.py` and `lookup_pass.py` in
the legacy `case_locator` repo.

Target for this system, measured against `tests/case_matches.csv`: recall
>= 99% and precision ~= 50%, both within the top 10 ranked candidates per
target (see the project plan, "Reading that target").

Implemented in Phase 6 of the project plan.
"""

"""Canonicalization system.

Preprocessing, abbreviation expansion, entity standardization, and
normalized formatting, turning a parsed case record into a structured set
of "case tokens" used for matching. Abbreviation and reporter maps are
loaded as versioned config data from `rollbook/data/`, not hardcoded, so
coverage can be extended without a code change. Ported from the
canonicalization functions in `helpers.py` in the legacy `case_locator`
repo.

Implemented in Phase 4 of the project plan.
"""

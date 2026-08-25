"""OCR cleanup & correction system.

Collapses blank lines, joins trailing-number continuations, expands
duplicate-name shorthand, and flags suspicious lines for review. Ported
from `ocr_tools/final_clean.py` and `ocr_tools/ocr_review.py` in the
legacy `case_locator` repo.

Implemented in Phase 2 of the project plan.
"""

"""OCR adapter system.

Wraps a trained OCR model (initially the existing Kraken model, ported
from the legacy `case_locator` repo) behind a stable contract: a cleaned
scan in, raw text out. Also owns the model manifest/pull mechanism that
fetches model weights from GitHub Release assets on demand, so the rest
of the pipeline never depends on which model produced the text.

Implemented in Phase 2 of the project plan.
"""

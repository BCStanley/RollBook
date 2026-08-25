"""RollBook — turn scans of 19th-century case indexes into a structured,
queryable database of authorities.

The package is organised as one subpackage per "system", following the
breakdown in the project specification (Case Locator: Specification,
Jul 2026, §3). Each system has a fixed, typed input/output contract so it
can be developed, tested, and improved independently of the others:

    ocr_io       -- adapter over a trained OCR model; scan -> raw text
    cleaning     -- correct & normalize OCR output; raw text -> clean lines
    parsing      -- split lines into structured case records
    canonical    -- abbreviation expansion, normalization; record -> tokens
    candidatedb  -- build & query the SQLite database of candidate cases
    matching     -- rule-based + fuzzy ranking of candidates against targets
    narrow       -- rank/format candidates for human review
    review       -- ingest a hand-reviewed CSV back into confirmed matches
    index        -- compile confirmed matches into the final systematic index

See the project plan for the full architecture and roadmap.
"""

from rollbook.__about__ import __version__

__all__ = ["__version__"]

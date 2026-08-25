from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexLine:
    """A dataclass representing a line from a scanned and OCR-ed index of a
    treatise.

    Args:
        source_file (str): the source file, as a string.
        line_no (int): the line number, an integer.
        raw_text (str): the raw text of the line.
    """
    source_file: str
    line_no: int
    raw_text: str


@dataclass(frozen=True)
class PartyvParty:
    party1: str
    party2: str


@dataclass(frozen=True)
class InRe:
    subject: str


@dataclass(frozen=True)
class ExParte:
    applicant: str


@dataclass(frozen=True)
class ShipName:
    name: str


@dataclass(frozen=True)
class Eponymous:
    label: str


@dataclass(frozen=True)
class Anonymous:
    pass


@dataclass(frozen=True)
class Unclassified:
    text: str


CaseSubject = PartyvParty | InRe | ExParte | ShipName | Eponymous | Anonymous | Unclassified


@dataclass(frozen=True)
class CaseRecord:
    """A dataclass representing the separated elements of a line from an
    OCR-ed index of a treatise.

    Args:
        line: the IndexLine object, raw line.
        case_name (str): the line element that is the case name, unprocessed.
        case_subject: one of the specified types of case.
        (e.g. PartyvParty, InRe)
        source_page_refs tuple(int): the page citations in the source.
        citation_fragment (str|none): citation fragments, if present.
    """
    line: IndexLine
    case_name: str
    case_subject: CaseSubject
    source_page_refs: tuple[int, ...]
    citation_fragment: str | None


@dataclass (frozen=True)
class CaseTokens:
    """A dataclass of all the tokens for a given case in an index.
    """
    index_record: CaseRecord
    canonical_short_title: str
    normalized_case_name: str
    primary_year: int | None
    judgment_date: str | None
    parsed_citations: tuple[str, ...]
    keys: tuple[str, ...]
    variants_applied: tuple[str, ...]


@dataclass (frozen=True)
class CandidateCase:
    id: int
    source_file: str
    line_no: int
    raw_text: str
    case_name: str
    clean_name: str
    canonical_short_title: str
    normalized_case_name: str
    party1: str
    party2: str | None
    primary_year: int | None
    judgment_date: str | None
    parsed_citations: tuple[str, ...]
    keys: tuple[str, ...]
    variants_applied: tuple[str, ...]
    notes: str

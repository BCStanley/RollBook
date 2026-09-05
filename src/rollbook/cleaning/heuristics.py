import re
from dataclasses import dataclass
from typing import Protocol, Literal
from collections.abc import Callable, Sequence, Iterator
from config import ReporterMap


# Underlying Dataclasses

@dataclass(frozen=True)
class LineDefect:
    proposed: str | None  # a confident fix, or None if flagged with nothing to propose.


class LineDefectHeuristic(Protocol):
    name: str
    def check(self, line: str) -> LineDefect | None:
        """None = nothing wrong. A LineDefect = something's
        wrong; its proposed field is the fix, or None if there isn't one.
        """


@dataclass(frozen=True)
class StructuralMatch:
    line_indices: tuple[int, ...] # which lines this consumes
    proposed: tuple[str, ...] | None


class StructuralHeuristic(Protocol):
    name: str
    kind: Literal["merge", "party_expansion"]
    def scan(self, lines: Sequence[str], start: int) -> StructuralMatch | None:
        """Search forward from "start" for the first place this heuristic's
        pattern occurs; return None if it doesn't occur again before the
        end of the file. The match's own line indicies carry its actual
        position - it isn't required to start exactly at "start."
        """


# Helper Functions

PAGE_MARKER = "{{/PAGE/}}"

def next_content_index(lines: Sequence[str], i: int) -> int | None:
    """Index of the next non-marker line at or after i, or None at EOF."""
    while i < len(lines):
        if lines[i] != PAGE_MARKER:
            return i
        i += 1
    return None


def prev_content_index(lines: Sequence[str], i: int) -> int | None:
    """Index of the nearest non-marker line at or before i, or None
    if none exists (start of file)."""
    while i >= 0:
        if lines[i] != PAGE_MARKER:
            return i
        i -= 1
    return None

# Automatic Heuristics (Single Line)

class TraillingPunctNumbers(LineDefectHeuristic):
    """
    "Smith v. Smith45,,, 32, 2" -> "Smith v. Smith, 45, 32, 2"
    """
    name = "trailing_punct_numbers"
    TOKEN = re.compile(r"\S+") # Split tokens by whitespace
    INNER = re.compile(
    r"^(?P<lead_punct>[(\[]*)(?P<lead_digits>\d*)"
    r"(?P<core>.*?)"
    r"(?P<trail_digits>\d*)(?P<trail_punct>[)\],;]*)$"
    )
    TAIL_ONLY = re.compile(r"[\d\s,;.]*")


    def __init__(self, reporters: ReporterMap) -> None:
        self.reporters = reporters

    def check(self, line: str) -> LineDefect | None:
        prev_match = None

        for matches in self.TOKEN.finditer(line): # Iterate through the tokens.
            token = matches.group(0)
            m = self.INNER.match(token)
            core = m.group("core")
            lead_digits = m.group("lead_digits") 
            trail_digits = m.group("trail_digits")

            if trail_digits and core not in self.reporters.entries:
                rest_of_line = line[matches.end():]
                if self.TAIL_ONLY.fullmatch(rest_of_line):
                    numbers = [trail_digits] + re.findall(r"\d+", rest_of_line)

                    if core.strip(".,; "):
                        clean_core = core.rstrip(".,; ")
                        start = matches.start()
                    elif prev_match is not None:
                        clean_core = prev_match.group(0).rstrip(".,; ")
                        start = prev_match.start()
                    else:
                        prev_match = matches
                        continue 
                    proposed = line[:start] + clean_core + ", " + ", ".join(numbers)
                    return LineDefect(proposed=proposed)

            prev_match = matches

        return None


class PunctuationClean(LineDefectHeuristic):
    name = "excess_punctuation"
    RUN = re.compile(r"[,;.](?:\s*[,;.])+")

    def _filter_run(self, run_text: str, char_before: str) -> str:
        kept = []
        seen_comma = False
        for i, ch in enumerate(run_text):
            # Period first in run with letter or digit prior
            if ch == "." and i == 0 and char_before.isalnum():
                kept.append(ch)
            elif ch == "," and not seen_comma:
                kept.append(ch)
                seen_comma = True
        return "".join(kept)


    def check(self, line: str) -> LineDefect | None:
        pieces = []
        last = 0
        for run in self.RUN.finditer(line):
            char_before = line[run.start() - 1: run.start()]
            kept = self._filter_run(run.group(0), char_before)
            followed_by_digit = bool(re.match(r"\s*\d", line[run.end():]))

            if kept:
                replacement = kept
            else:
                if followed_by_digit:
                    replacement = ","
                else:
                    replacement = " "

            before_text = line[last:run.start()]
            if replacement[0] == ",":
                before_text = before_text.rstrip()

            pieces.append(before_text)
            pieces.append(replacement)
            last = run.end()

        pieces.append(line[last:])
        fixed = "".join(pieces)

        if fixed != line:
            fixed = re.sub(r" {2,}", " ", fixed)
            return LineDefect(proposed=fixed)
        return None


class CollapseWhitespace(LineDefectHeuristic):
    name = "collapse_whitespace"

    def check(self, line: str) -> LineDefect | None:
        fixed = re.sub(r" {2,}", " ", line)
        if fixed != line:
            return LineDefect(proposed=fixed)
        return None


class EnsureTrailingComma(LineDefectHeuristic):
    """
    Ensures the boundary between the party name and the trailing
    page-number list is always a single comma with no space before it:
    "Smith 45, 67" -> "Smith, 45, 67", "Rogers. 432" -> "Rogers, 432",
    "Dale  , 72" -> "Dale, 72". Skips any line containing a bracket,
    since a bracketed citation can itself contain the line's last letter
    (e.g. "(2 Chitt. 255) 589") and this heuristic has no business
    reaching inside one -- deliberately deferred, not handled here.
    """
    name = "ensure_trailing_comma"
    LETTER = re.compile(r"[A-Za-z]")

    def check(self, line: str) -> LineDefect | None:
        if "(" in line or ")" in line:
            return None

        letters = list(self.LETTER.finditer(line))
        if not letters:
            return None

        boundary = letters[-1].end()  # position right after the last letter
        tail = line[boundary:]

        if not re.search(r"\d", tail):
            return None  # nothing after the name looks like a number list

        stripped = tail.lstrip()
        if not stripped:
            return None

        if stripped[0] == ",":
            if stripped == tail:
                return None  # already correct
            proposed = line[:boundary] + stripped  # strip the stray space before the comma
        elif stripped[0].isdigit():
            proposed = line[:boundary] + ", " + stripped
        else:
            # some other punctuation mark sitting right at the boundary -- replace it
            proposed = line[:boundary] + "," + stripped[1:]

        if proposed != line:
            return LineDefect(proposed=proposed)
        return None


class NormalizeV(LineDefectHeuristic):
    name = "normalize_v"
    PATTERN = re.compile(r"(?P<lead>\s*)\bv\b(?P<trail>[.,\s]*)", re.IGNORECASE)

    def check(self, line: str) -> LineDefect | None:
        def _fix(m: re.Match) -> str:
            lead = "" if m.start() == 0 else " "
            return f"{lead}v "

        fixed = self.PATTERN.sub(_fix, line)
        if fixed != line:
            return LineDefect(proposed=fixed)
        return None

# User Monitored Heuristics (Single Line)

class LowercaseToken(LineDefectHeuristic):
    name = "lowercase_token"
    WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
    UPPERCASE = re.compile(r"[A-Z]")
    ALLOWED = re.compile(
        r"^(?:v|of|and|the|in|ex|parte|re|de|case|pl|la|or|id|et|nb)$",
        re.IGNORECASE,
    )

    def check(self, line: str) -> LineDefect | None:
        for words in self.WORD.finditer(line):
            word = words.group(0)
            first_letter = word[0]
            if not self.UPPERCASE.match(first_letter) and not self.ALLOWED.match(word):
                return LineDefect(proposed=None)
        return None


class InternalCapital(LineDefectHeuristic):
    name = "internal_captial"
    WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

    def check(self, line: str) -> LineDefect | None:
        for m in self.WORD.finditer(line):
            word = m.group(0)
            mc_boundary = 2 if word.startswith("Mc") else 3 if word.startswith("Mac") else None

            split_points = []
            for i in range(1, len(word)):
                if word[i].isupper():
                    if word[i - 1] == "'" or i == mc_boundary:
                        continue
                    split_points.append(i)

            if split_points:
                segments = []
                last = 0
                for p in split_points + [len(word)]:
                    segments.append(word[last:p])
                    last = p
                if all(len(seg) > 3 for seg in segments):
                    proposed = line[:m.start()] + " ".join(segments) + line[m.end():]
                    return LineDefect(proposed=proposed)
                return LineDefect(proposed=None)
        return None


class AutoDigitLetter(LineDefectHeuristic):
    """
    If a line has an obvious letter for number substitution, return
    a correction of that, else return None.
    """
    name = "auto_digit_letter_sub"
    CANDIDATE = re.compile(r"\b[0-9oOlIsS]+\b")
    TRANSLATE = str.maketrans("oOlIsS", "001155")

    def _fix_token(self, match: re.Match) -> str:
        tok = match.group(0)
        if any(c.isdigit() for c in tok) and any(ord(c) in self.TRANSLATE for c in tok):
            return(tok.translate(self.TRANSLATE))
        return tok

    def check(self, line: str) -> LineDefect | None:
        fixed = self.CANDIDATE.sub(self._fix_token, line)
        if fixed != line:
            return LineDefect(proposed=fixed)
        return None


class AutoCitation(LineDefectHeuristic):
    name = "auto_citation_lookup"
    TOKEN = re.compile(r"\S+") # Split tokens by whitespace
    INNER = re.compile(
    r"^(?P<lead_punct>[(\[]*)(?P<lead_digits>\d*)"
    r"(?P<core>.*?)"
    r"(?P<trail_digits>\d*)(?P<trail_punct>[)\],;]*)$"
    )
    CITATION_INITIALS = re.compile(r"^(?:[A-Z]\.?){2,}$")   # QBD, Q.B.D., QB.D, CCC, C.C.C.
    CITATION_CAPWORD  = re.compile(r"^[A-Z][a-z]+\.?$")      # Qbd, Ab, Abc, Abc.

    def __init__(self, reporters: ReporterMap) -> None:
        self.reporters = reporters

    def _fix_token(self, match: re.Match) -> str:
        tok = match.group(0) # get the token: "(1Salk65,"
        m = self.INNER.match(tok) # split the token: "(", 1", "Salk" etc.
        core = m.group("core") # isolate the "core": "Salk"
        lead_punct = m.group("lead_punct") # "("
        lead_digits = m.group("lead_digits") # "1"
        trail_digits = m.group("trail_digits") # "65"
        trail_punct = m.group("trail_punct") # ","
        # Is this a reporter we expect?
        if core in self.reporters.entries:
            # If yes, return it as cleaned up.
            leadspace = " " if lead_digits else ""
            trailspace = " " if trail_digits else ""
            return f"{lead_punct}{lead_digits}{leadspace}{core}{trailspace}{trail_digits}{trail_punct}"
        return tok # otherwise, keep as is.

    def check(self, line: str) -> LineDefect | None:
        fixed = self.TOKEN.sub(self._fix_token, line) # pass each separated token into _fix_token for sub.
        if fixed != line: # If there's been a change, return that
            return LineDefect(proposed=fixed)
        # Might be "citation shaped", but not in our table of citations (yet.)
        for matches in self.TOKEN.finditer(line): # Iterate through the tokens.
            tok = matches.group(0)
            m = self.INNER.match(tok)
            core = m.group("core")
            lead_digits = m.group("lead_digits") 
            trail_digits = m.group("trail_digits")
            has_dig = lead_digits or trail_digits
            if has_dig and (self.CITATION_INITIALS.match(core) or self.CITATION_CAPWORD.match(core)):
                return LineDefect(proposed=None)
        return None # Otherwise, nothing


class UnclosedBracket(LineDefectHeuristic):
    """
    Flags any line whose bracket counts don't balance.
    Does not propose solutions, as may be multi-line.
    """
    name = "unclosed_bracket"
    BRACKET_PAIRS = [("(", ")"), ("[", "]"), ("{", "}")]

    def check(self, line: str) -> LineDefect | None:
        for pair in self.BRACKET_PAIRS:
            open = line.count(pair[0])
            close = line.count(pair[1])
            if open != close:
                return LineDefect(proposed=None)
        return None


class ResidualDigitLetter(LineDefectHeuristic):
    """
    Flags lines with a digit-then-letter shape (e.g. "87l", "Bas4b4")
    that neither AutoDigitLetter nor AutoCitation could resolve.
    If so, then proposed=None: something is wrong, but there is no confident
    fixed.
    """
    name = "residual_digit_letter"
    CANDIDATE = re.compile(r"\d+[A-Za-z]+")

    def __init__(self, auto_digit_letter: AutoDigitLetter, auto_citation: AutoCitation) -> None:
        self.auto_digit_letter = auto_digit_letter
        self.auto_citation = auto_citation

    def check(self, line: str) -> LineDefect | None:
        if self.CANDIDATE.search(line) and self.auto_digit_letter.check(line) == None and self.auto_citation.check(line) == None:
            return LineDefect(proposed=None)
        return None


# Multi-Line Heuristics

class WrapContinuation(StructuralHeuristic):
    """
    Merges a page-nmber only continuation line into the entry above it:
    "Broaddent v Imperial Gas Co 35, / 65, 701, 703" becomes one line.
    The {{/PAGE/}} Marker is accounted for here.
    """
    name = "wrap_continuation"
    kind: Literal["merge"] = "merge"
    NUMERIC_ONLY = re.compile(r"^\s*\d[\d,\s\-]*[.,]?\s*$")

    def scan(self, lines: Sequence[str], start: int) -> StructuralMatch | None:
        for i in range(start, len(lines)):
            line = lines[i]
            if self.NUMERIC_ONLY.fullmatch(line):
                prev_idx = prev_content_index(lines, i - 1)
                prev_line = lines[prev_idx] if prev_idx is not None else None
                if prev_line:
                    merged = f"{prev_line.rstrip(' ,;')}, {line.rstrip(' ,;')}"
                    return StructuralMatch(
                        line_indices=(prev_idx, i),
                        proposed=(merged,)
                    )
        return None


class NameWrapContinuation(StructuralHeuristic):
    """
    Merges a case name wraped across multiple lines. For a run of lines with no digits at 
    all, followed by the line that contians digits. Joins with conactenation when the previous
    fragments ends in hyphen, otherwise a single space.
    """
    name = "name_wrap_continuation"
    kind: Literal["merge"] = "merge"
    HAS_DIGIT = re.compile(r"\d")
    
    def scan(self, lines: Sequence[str], start: int) -> StructuralMatch | None:
        for i in range(start, len(lines)):
            if not self.HAS_DIGIT.search(lines[i]): # No digit:
                indices = [i]
                digit = False
                next = next_content_index(lines, i + 1)
                while not digit: # Keep looping until the next line containing a digit.
                    if next is None:
                        break
                    next_line = lines[next]
                    indices.append(next)
                    if self.HAS_DIGIT.search(next_line):
                        digit = True
                    else:
                        next = next_content_index(lines, next + 1)
                if next is None:
                    continue
                # lines[i:next] are now the parts that need joining.
                merged: str = ""
                last_hyphen = False
                for idx in indices:
                    part = lines[idx].rstrip()
                    current_hyphen = part.endswith("-")
                    if current_hyphen:
                        part = part[:-1]

                    if last_hyphen:
                        merged = f"{merged}{part}" # last part had a hyphen.
                    elif not merged:
                        merged = part
                    else:
                        merged = f"{merged} {part}"
                    last_hyphen = current_hyphen
                return StructuralMatch(line_indices=tuple(indices), proposed=(merged,))
        return None


class ResolveDuplicateParties(StructuralHeuristic):
    """
    For duplicate blocks: Smith v Jones / v. Jacobs / v. Thomas -->
    --> Smith v Jones / Smith v Jacobs / Smith v Thomas
    """
    name = "resolve_duplicate_parties"
    BARE_V_START = re.compile(r"^v\b")
    V_SPLIT = re.compile(r"^(?P<left>.+?)\s+\bv\b\s+(?P<right>.+)$")
    COMMA_ANCHOR = re.compile(r"^(?P<left>[A-Z][^,]*?)\s*,")
    GLUED_V_SPLIT = re.compile(r"^(?P<left>[A-Za-z']+)v\.?\s+(?P<right>.+)$")
    kind: Literal["party_expansion"] = "party_expansion"

    def _resolve_anchor(self, selected_lines: Sequence[str], idx: int) -> str | None:
        for prev in reversed(selected_lines[:idx]):
            m = self.V_SPLIT.match(prev)
            left = m.group("left") if m else None
            right = m.group("right") if m else None
            if left:
                return left.rstrip()
            m = self.GLUED_V_SPLIT.match(prev)
            other_left = m.group("left") if m else None
            if other_left:
                return other_left.rstrip()
            m = self.COMMA_ANCHOR.match(prev)
            comma_left = m.group("left") if m else None
            if comma_left:
                return comma_left.rstrip()
        return None


    def scan(self, lines, start):
        for i in range(start, len(lines)):
            if self.BARE_V_START.match(lines[i]): # "v Smith"
                left = self._resolve_anchor(lines, i) 
                if left: # e.g. "Jones"
                    indicies = [i]
                    proposed = [f"{left} {lines[i].lstrip()}"]

                    cursor = next_content_index(lines, i+1)
                    while cursor is not None and self.BARE_V_START.match(lines[cursor]):
                        indicies.append(cursor)
                        proposed.append(f"{left} {lines[cursor].lstrip()}")
                        cursor = next_content_index(lines, cursor+1)
                    
                    return StructuralMatch(line_indices=tuple(indicies), proposed=tuple(proposed))

        return None

                

# Groups of Heuristics
# Purpose: provides an easy way of iterating over a set of heuristics for later handling,
# so that there is no need to later list them in a cli or elsewhere.


# 1. AutomaticHeuristics: applied automatically without user input (all single line)
@dataclass(frozen=True)
class AutomaticHeuristics:
    heuristics: tuple[LineDefectHeuristic, ...]

    def __iter__(self) -> Iterator[LineDefectHeuristic]:
        return iter(self.heuristics)


# 2. UserMonitoredSingleLine: applied with user input (with or without suggestions provided)
# on single line
@dataclass(frozen=True) 
class UserMonitoredSingleLine:
    heuristics: tuple[LineDefectHeuristic, ...]

    def __iter__(self) -> Iterator[LineDefectHeuristic]:
        return iter(self.heuristics)

# 3. UserMonitoredMultiLine: applied across multiple lines (collapses etc.) with user input.
@dataclass(frozen=True)
class UserMonitoredMultiLine:
    heuristics: tuple[StructuralHeuristic, ...]

    def __iter__(self) -> Iterator[StructuralHeuristic]:
        return iter(self.heuristics)

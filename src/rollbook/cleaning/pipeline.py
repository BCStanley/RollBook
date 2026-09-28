from rollbook.cleaning.heuristics import *
from rollbook.config import ReporterMap
from importlib import resources
from rollbook.config import REPORTER_MAP_FILENAME, load_reporter_map
data_dir = resources.files("rollbook") / "data"
reporter_map = load_reporter_map(data_dir / REPORTER_MAP_FILENAME)

def build_automatic_heuristics(reporter_map: ReporterMap) -> AutomaticHeuristics:
    return AutomaticHeuristics(
        heuristics = (
            TraillingPunctNumbers(reporters=reporter_map), 
            PunctuationClean(),
            CollapseWhitespace(),
            EnsureTrailingComma(),
            NormalizeV(),
            AutoDigitLetter(),
            AutoCitation(reporters=reporter_map)
        )
    )

def build_user_monitored_single_line(reporter_map: ReporterMap) -> UserMonitoredSingleLine:
    return UserMonitoredSingleLine(
        heuristics = (
            AutoDigitLetter(),
            AutoCitation(reporters=reporter_map),
            LowercaseToken(),
            InternalCapital(),
            UnclosedBracket(),
            ResidualDigitLetter(auto_digit_letter=AutoDigitLetter(), auto_citation=AutoCitation(reporters=reporter_map))
        )
    )

def build_user_monitored_multiple_line() -> UserMonitoredMultiLine:
    return UserMonitoredMultiLine(
        heuristics = (
            WrapContinuation(),
            NameWrapContinuation(),
            ResolveDuplicateParties()
        )
    )


def apply_automatic_heuristics(line: str, heuristics: AutomaticHeuristics) -> str:
    fixed_line = line
    for heuristic in heuristics:
        line_defect: LineDefect | None = heuristic.check(fixed_line)
        if line_defect and line_defect.proposed is not None:
            fixed_line = line_defect.proposed 
        else:
            continue
    return fixed_line

def first_flagged_defect(line: str, heuristics: UserMonitoredSingleLine) -> LineDefect | None:
    for heuristic in heuristics:
        potential_defect = heuristic.check(line)
        if potential_defect:
            return potential_defect
    return None

def apply_structural_heuristics(lines: list[str], heuristics: UserMonitoredMultiLine, start: int) -> tuple[StructuralMatch, StructuralHeuristic] | None:
    best: tuple[StructuralMatch, StructuralHeuristic] | None = None
    for heuristic in heuristics:
        result = heuristic.scan(lines, start)
        if result is not None:
            if not best:
                best = (result, heuristic)
            elif result.line_indices[0] < best[0].line_indices[0]:
                best = (result, heuristic)
    return best

    


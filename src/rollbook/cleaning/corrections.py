import json
from dataclasses import dataclass, field, asdict
from typing import Literal
from pathlib import Path

class CorrectionError(Exception):
    pass

@dataclass(frozen=True)
class CorrectionRecord:
    line: int # an absolute line number
    initiator: Literal["heuristic", "user"]
    kind: Literal["rewrite", "merge", "party_expansion", "duplicate_block"]
    original: str
    proposed: str | None
    final: str | None
    reviewed: bool
    line_count: int = 1


@dataclass
class CorrectionHistory:
    records: list[CorrectionRecord] = field(default_factory=list)

    def append(self, record: CorrectionRecord) -> None:
        """Add a new record at the end of the log."""
        self.records.append(record)


    def last_edit(self) -> CorrectionRecord | None:
        """Return the last edit, or None if there isn't one."""
        if not self.records:
            return None
        return self.records[-1]

    def last_edit_location(self, pages: list[list[str]]) -> tuple[int, int] | None:
        """Translate last_edit()'s absolute line number into a page and line number."""
        # get the last edit
        last = self.last_edit()
        if not last:
            return None
        line_counter = 0
        for page_number, page in enumerate(pages):
            for line_number, line in enumerate(page):
                if line_counter == last.line:
                    return(page_number, line_number)
                line_counter += 1
        return None


    def save(self, path: Path) -> None:
        """Write the record as a JSON object."""
        with path.open("w", encoding="utf-8") as f:
            for record in self.records:
                f.write(json.dumps(asdict(record)) + "\n")

    @classmethod
    def load(cls, path: Path) -> "CorrectionHistory":
        """Read a JSON object to produce a CorrectionHistory object."""
        try: 
            with path.open("r", encoding="utf-8") as f:
                History = cls()
                for line in f:
                    record_dict = json.loads(line)
                    record = CorrectionRecord(
                            line = record_dict["line"],
                            initiator = record_dict["initiator"],
                            kind = record_dict["kind"],
                            original = record_dict["original"],
                            proposed = record_dict["proposed"],
                            final = record_dict["final"],
                            reviewed = record_dict["reviewed"],
                            line_count = record_dict["line_count"]
                    )
                    History.append(record)
        except FileNotFoundError as e:
            raise CorrectionError(f"Could not locate file {e}.") from e
        except (json.JSONDecodeError, KeyError) as e:
            raise CorrectionError(f"Error reading file {e}.") from e
        return History



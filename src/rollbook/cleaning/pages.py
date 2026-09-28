from pathlib import Path
from rollbook.cleaning.heuristics import PAGE_MARKER

def load_pages(path: Path) -> list[list[str]]:
    pages = []
    new_page = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == PAGE_MARKER:
            pages.append(new_page)
            new_page = []
        else:
            new_page.append(line)
    pages.append(new_page)
    return pages





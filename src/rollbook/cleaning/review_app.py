from pathlib import Path
from typing import Sequence

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from rollbook.cleaning import pipeline
from rollbook.cleaning.corrections import CorrectionError, CorrectionHistory, CorrectionRecord
from rollbook.cleaning.heuristics import PAGE_MARKER, StructuralHeuristic, StructuralMatch
from rollbook.cleaning.pages import load_lines


# --- pure helpers: document/page bookkeeping ---------------------------

def marker_positions(lines: Sequence[str]) -> list[int]:
    """Every raw index in `lines` that holds a PAGE_MARKER, in order."""
    return [i for i, line in enumerate(lines) if line == PAGE_MARKER]


def page_bounds(lines: Sequence[str], page_index: int) -> tuple[int, int]:
    """The (start, end) raw-index range -- end exclusive -- of `page_index`'s
    content within `lines`, computed fresh from wherever the markers
    currently are. There is no separate stored "pages" structure any more;
    a page is just a slice between two markers, worked out on demand, so it
    can never drift out of sync with `lines` itself after a structural edit
    changes how many lines there are.
    """
    markers = marker_positions(lines)
    start = 0 if page_index == 0 else markers[page_index - 1] + 1
    end = markers[page_index] if page_index < len(markers) else len(lines)
    return start, end


def total_pages(lines: Sequence[str]) -> int:
    return len(marker_positions(lines)) + 1


def content_line_number(lines: Sequence[str], raw_index: int) -> int:
    """Convert a raw index into `lines` (which may include PAGE_MARKER
    entries) into a content-only line number -- the position this line
    would have if every marker were removed. This is what
    CorrectionRecord.line has always meant ("absolute index, page markers
    excluded"), kept the same even though `lines` itself now carries the
    markers for the structural heuristics' benefit.
    """
    return sum(1 for line in lines[:raw_index] if line != PAGE_MARKER)


# --- pure helpers: single-line review (stage one, unchanged in spirit) --

def flagged_line_indices(page: list[str], heuristics) -> list[int]:
    """Every index in `page` where `pipeline.first_flagged_defect` finds
    something wrong, in line order. Pure and side-effect free -- knows
    nothing about pages, history, or the app -- so it's testable on its
    own without spinning up a ReviewApp at all.
    """
    return [
        index
        for index, line in enumerate(page)
        if pipeline.first_flagged_defect(line, heuristics) is not None
    ]


def already_reviewed_indices(base: int, page_length: int, records) -> set[int]:
    """Within-page indices that already have a reviewed=True CorrectionRecord
    (any kind, not just a guided-review one) -- so a page you've already been
    through isn't walked again from scratch on revisit. `base` is the
    content-only line number the page starts at; `records` is any iterable of
    CorrectionRecord. Pure -- also testable on its own.
    """
    return {
        record.line - base
        for record in records
        if record.reviewed and base <= record.line < base + page_length
    }


# --- pure helpers: structural review (stage two) ------------------------

def structural_already_reviewed(
    lines: Sequence[str],
    match: StructuralMatch,
    heuristic: StructuralHeuristic,
    records,
) -> bool:
    """True if this exact match was already *rejected* on an earlier visit.

    Only rejections need this guard: a confirmed match naturally stops
    reappearing once it's applied, because the pattern that triggered it is
    gone from `lines`. A rejected one doesn't change `lines` at all, so
    without this check the same rejected match would resurface every time
    the page was revisited.

    Deliberately does NOT match against confirmed records too (an earlier,
    broader version of this check did, and it was wrong): `(kind, starting
    content line)` is not a unique-enough key once the document has been
    mutated. Confirming a merge collapses several lines into one at that
    same starting position -- and if the newly-merged line itself picks up
    a further, genuinely new structural match (e.g. another numeric
    continuation now trailing it), that new match starts at the exact same
    content line the earlier, unrelated confirmed record was logged under.
    Checking confirmed records here would silently swallow that legitimate
    follow-up match. Confirmed via real-data execution: exactly this
    situation caused 5 real merge matches to be wrongly skipped before this
    was narrowed to rejections only.
    """
    start_line = content_line_number(lines, match.line_indices[0])
    return any(
        record.reviewed
        and record.final is None
        and record.kind == heuristic.kind
        and record.line == start_line
        for record in records
    )


def build_merge_record(
    lines: Sequence[str],
    match: StructuralMatch,
    heuristic: StructuralHeuristic,
    final_text: str | None,
) -> CorrectionRecord:
    """The single CorrectionRecord for a `merge`-kind match. `final_text`
    is the (possibly user-edited) text that was actually applied, or None
    if the match was rejected outright -- `original` is always the real
    lines that were there before, newline-joined per the line_count
    convention, `line_count` is how many original *content* lines this one
    record covers.

    That's deliberately `len(match.line_indices)`, not
    `max(match.line_indices) - match.line_indices[0] + 1` (the raw index
    span): a continuation match that bridges a page boundary has a PAGE_MARKER
    sitting inside that raw span without being part of the match (see the
    marker-skip guards in heuristics.py's scan() methods), and line_count is
    meant to count original lines this record covers -- not page markers it
    happened to pass over.
    """
    start_idx = match.line_indices[0]
    return CorrectionRecord(
        line=content_line_number(lines, start_idx),
        initiator="heuristic",
        kind=heuristic.kind,
        original="\n".join(lines[i] for i in match.line_indices),
        proposed=match.proposed[0] if match.proposed else None,
        final=final_text,
        reviewed=True,
        line_count=len(match.line_indices),
    )


def build_party_expansion_records(
    lines: Sequence[str],
    match: StructuralMatch,
    heuristic: StructuralHeuristic,
    confirmed: bool,
) -> list[CorrectionRecord]:
    """A `party_expansion` match is naturally one-to-one -- every line in
    it gets its own distinct replacement -- so it's logged as that many
    separate, ordinary line_count=1 records rather than forced into one
    record the way a merge is. `confirmed` is the single group-level
    decision; it's applied identically to every record in the group
    (final=the real proposal if confirmed, final=None if rejected), even
    though each record is otherwise independent.
    """
    proposals = match.proposed or ()
    return [
        CorrectionRecord(
            line=content_line_number(lines, index),
            initiator="heuristic",
            kind=heuristic.kind,
            original=lines[index],
            proposed=proposed,
            final=proposed if confirmed else None,
            reviewed=True,
            line_count=1,
        )
        for index, proposed in zip(match.line_indices, proposals)
    ]


def splice_matched_lines(
    lines: list[str], match: StructuralMatch, replacements: Sequence[str]
) -> list[str]:
    """Replace the lines at `match.line_indices` with `replacements`,
    mutating `lines` in place, while leaving anything else inside the raw
    index span untouched.

    This matters because `match.line_indices` is not guaranteed to be a
    contiguous run: a continuation match that bridges a page boundary has a
    PAGE_MARKER sitting between its matched indices, deliberately excluded
    from `line_indices` by the heuristic's own marker-skip guard (see
    heuristics.py) so the merged *text* never includes marker content. But
    that only protects the text -- it says nothing about how the caller
    should mutate the document. A naive `lines[start:end] = replacements`
    over the raw span silently deletes whatever sits in the gap along with
    the matched lines, which for a page-crossing match means silently
    deleting the page marker itself (confirmed against real data: this
    happened 7 times over the full document before this fix, collapsing 7
    pairs of pages into one and breaking page navigation for everything
    after them). This function instead walks the raw span index by index:
    a matched index is replaced by the next entry from `replacements` (with
    any run of matched indices beyond the first simply absorbed -- that's
    how an N-line merge collapses to a single line), and anything else
    (a marker, or in principle any other non-matched line) is carried over
    unchanged in its original position.

    `replacements` may have fewer entries than `match.line_indices` (a merge
    collapsing several lines to one) or the same number (a 1:1
    party_expansion); either way, returns the exact list of strings written
    in place of the old span, so a caller can work out how far the document
    just changed size without re-deriving it.
    """
    start_idx = match.line_indices[0]
    end_idx = max(match.line_indices) + 1
    matched = set(match.line_indices)
    remaining = list(replacements)
    spliced: list[str] = []
    for i in range(start_idx, end_idx):
        if i in matched:
            if remaining:
                spliced.append(remaining.pop(0))
        else:
            spliced.append(lines[i])
    spliced.extend(remaining)
    lines[start_idx:end_idx] = spliced
    return spliced


class ReviewApp(App):
    CSS = """
    #main {
        height: 1fr;
    }

    ListView {
        width: 2fr;
        height: 1fr;
    }

    #side-pane {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        border-left: solid $accent;
    }

    #instructions {
        height: auto;
    }

    #edit-line {
        height: 1;
        border: none;
    }

    ListItem.flagged Label {
        color: $warning;
    }

    ListItem.structural-match {
        background: $warning 25%;
    }

    ListItem.structural-match Label {
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("J", "next_page", "Next page"),
        Binding("K", "prev_page", "Prev page"),
        Binding("escape", "skip_guided", "Skip guided review", show=False),
        Binding("ctrl+r", "reject_structural", "Reject match", show=False),
        Binding("y", "confirm_structural_group", "Confirm group", show=False),
    ]

    def __init__(self, path: Path, history_path: Path | None = None) -> None:
        super().__init__()
        self.path: Path = path
        self.history_path: Path = history_path or path.with_suffix(".corrections.jsonl")

        raw_lines = load_lines(path)
        self.automatic_heuristics = pipeline.build_automatic_heuristics(pipeline.reporter_map)
        self.single_line_heuristics = pipeline.build_user_monitored_single_line(pipeline.reporter_map)
        self.multi_line_heuristics = pipeline.build_user_monitored_multiple_line()

        # One flat, marker-preserving document -- the single source of truth
        # for both stage one and stage two. "Page" is never stored; it's
        # always computed on demand from wherever the markers currently sit
        # (see page_bounds), so a structural edit that changes how many
        # lines exist can never leave a separate page structure out of sync.
        self.lines: list[str] = [
            line if line == PAGE_MARKER else pipeline.apply_automatic_heuristics(line, self.automatic_heuristics)
            for line in raw_lines
        ]

        self.history: CorrectionHistory = self._load_history()

        self.current_page: int = 0

        # `_editing_index` is a raw index into self.lines (not a page-relative
        # one) for whichever line the Input is currently editing -- covers
        # guided review, free editing, and structural merge review alike.
        self._editing_index: int | None = None

        # Stage-one guided single-line review, for whichever page is on
        # screen. `_guided_queue` holds within-page indices still to walk.
        self._guided_queue: list[int] = []
        self._guided_position: int = 0
        self._guided_current_proposed: str | None = None

        # Stage-two structural review, for whichever page is on screen.
        # `_structural_search_start` is a raw index into self.lines: where
        # the next call to apply_structural_heuristics should search from.
        # `_current_structural` is the match currently being shown, if any.
        self._structural_search_start: int = 0
        self._current_structural: tuple[StructuralMatch, StructuralHeuristic] | None = None

    # --- setup ------------------------------------------------------------

    def _load_history(self) -> CorrectionHistory:
        try:
            return CorrectionHistory.load(self.history_path)
        except CorrectionError as e:
            if isinstance(e.__cause__, FileNotFoundError):
                return CorrectionHistory()
            raise

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(*self._build_items(self.current_page))
            with Vertical(id="side-pane"):
                yield Static("", id="instructions")
        yield Input(id="edit-line")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "RollBook Review"
        self._update_subtitle()
        self.query_one(Input).display = False
        self.query_one(ListView).focus()
        await self._start_guided_review()

    def _update_subtitle(self) -> None:
        self.sub_title = f"{self.path.name} — page {self.current_page + 1} of {total_pages(self.lines)}"

    def _build_items(self, page_index: int) -> list[ListItem]:
        start, end = page_bounds(self.lines, page_index)
        page_lines = self.lines[start:end]
        flagged = set(flagged_line_indices(page_lines, self.single_line_heuristics))

        # The line(s) belonging to whichever structural match is currently
        # being shown, if any -- so the whole block lights up, not just the
        # single line the ListView cursor happens to sit on. Guarded to only
        # the lines actually within [start, end): a page-crossing match's
        # tail sitting on the *next* page has nothing to highlight here.
        structural: set[int] = set()
        if self._current_structural is not None:
            match, _ = self._current_structural
            structural = {i - start for i in match.line_indices if start <= i < end}

        items = []
        for index, line in enumerate(page_lines):
            item = ListItem(Label(line, markup=False))
            if index in flagged:
                item.add_class("flagged")
            if index in structural:
                item.add_class("structural-match")
            items.append(item)
        return items

    # --- page navigation ----------------------------------------------

    def action_cursor_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    async def action_next_page(self) -> None:
        if self.current_page < total_pages(self.lines) - 1:
            self._save_history()
            # Abandon any structural match still being shown on the page
            # we're leaving -- it was never resolved (no record logged),
            # so it'll simply be found again if this page is revisited.
            # Left set, its (now-stale) raw indices would otherwise get
            # checked against the *new* page's bounds in the very next
            # _build_items() call below.
            self._current_structural = None
            self.current_page += 1
            await self._refresh_page()
            await self._start_guided_review()

    async def action_prev_page(self) -> None:
        if self.current_page > 0:
            self._save_history()
            self._current_structural = None
            self.current_page -= 1
            await self._refresh_page()
            await self._start_guided_review()

    async def _refresh_page(self, *, restore_index: int | None = None) -> None:
        list_view = self.query_one(ListView)
        await list_view.clear()
        for item in self._build_items(self.current_page):
            await list_view.append(item)
        if restore_index is not None:
            list_view.index = restore_index
        self._update_subtitle()

    # --- guided single-line review (stage one) -------------------------

    async def _start_guided_review(self) -> None:
        """Build the queue of lines to walk the user through on the page
        that's now on screen: every line the single-line heuristics still
        flag, minus any line that already has a reviewed=True record in the
        history. Once this queue is exhausted, structural review begins
        for the same page -- see _start_structural_review.
        """
        start, end = page_bounds(self.lines, self.current_page)
        base = content_line_number(self.lines, start)
        page_length = end - start
        already_reviewed = already_reviewed_indices(base, page_length, self.history.records)
        page_lines = self.lines[start:end]

        self._guided_queue = [
            index
            for index in flagged_line_indices(page_lines, self.single_line_heuristics)
            if index not in already_reviewed
        ]
        self._guided_position = 0

        if self._guided_queue:
            self._show_instructions(
                "Guided review: stepping through every flagged line on this page.\n\n"
                "Press Enter to accept the fix shown (editing it first if you'd "
                "rather), or Escape to skip the rest and edit freely."
            )
            await self._advance_guided_review()
        else:
            await self._start_structural_review()

    async def _advance_guided_review(self) -> None:
        list_view = self.query_one(ListView)
        if self._guided_position >= len(self._guided_queue):
            # Guided review is genuinely finished for this page -- clear the
            # queue (not just advance past its end) so that every later check
            # of `self._guided_queue`'s truthiness (on_list_view_selected,
            # on_input_submitted's in_guided_review test, action_skip_guided's
            # branch choice) correctly sees "no guided review active" rather
            # than a stale, already-exhausted queue.
            self._guided_queue = []
            self._guided_position = 0
            await self._start_structural_review()
            return

        within_page_index = self._guided_queue[self._guided_position]
        list_view.index = within_page_index

        start, _ = page_bounds(self.lines, self.current_page)
        raw_index = start + within_page_index
        line = self.lines[raw_index]
        defect = pipeline.first_flagged_defect(line, self.single_line_heuristics)
        self._guided_current_proposed = defect.proposed if defect else None
        prefill = self._guided_current_proposed if self._guided_current_proposed is not None else line

        self._editing_index = raw_index
        edit_input = self.query_one(Input)
        edit_input.value = prefill
        edit_input.display = True
        edit_input.focus()

    # --- structural review (stage two) ---------------------------------

    async def _start_structural_review(self) -> None:
        start, _ = page_bounds(self.lines, self.current_page)
        self._structural_search_start = start
        await self._advance_structural_review()

    async def _advance_structural_review(self) -> None:
        """Find the next structural match that starts on the current page
        (per Ben's call: paced by page, even on the rare match whose
        content reaches onto the next one), skipping any that have already
        been resolved on an earlier visit. Stops -- and hands off to free
        editing -- once nothing left qualifies.

        Either way this lands on (a genuinely new match, or "nothing left"),
        it rebuilds the ListView before returning -- once, here, rather than
        leaving each caller to remember its own refresh. That single rebuild
        does two jobs at once: it picks up whatever the *previous* match's
        resolution just did to self.lines (a merge/expansion changes the
        text; a rejection doesn't touch it, but the item list still needs
        rebuilding to drop the old highlight), and it re-derives which
        item(s) get the "structural-match" highlight from the *new*
        self._current_structural, moving the ListView's cursor to the first
        matched line so the view scrolls there automatically instead of
        leaving the user to go find it.
        """
        _, page_end = page_bounds(self.lines, self.current_page)

        while True:
            result = pipeline.apply_structural_heuristics(
                self.lines, self.multi_line_heuristics, self._structural_search_start
            )
            if result is None or result[0].line_indices[0] >= page_end:
                self._current_structural = None
                await self._refresh_page()
                self._finish_structural_review()
                return

            match, heuristic = result
            if structural_already_reviewed(self.lines, match, heuristic, self.history.records):
                self._structural_search_start = max(match.line_indices) + 1
                continue

            self._current_structural = (match, heuristic)
            start, _ = page_bounds(self.lines, self.current_page)
            await self._refresh_page(restore_index=match.line_indices[0] - start)
            self._show_structural_match(match, heuristic)
            return

    def _finish_structural_review(self) -> None:
        self._show_instructions(
            "Structural review complete. Edit anything else you'd like, then move to the next page."
        )
        edit_input = self.query_one(Input)
        edit_input.value = ""
        edit_input.display = False
        self._editing_index = None
        self.query_one(ListView).focus()

    def _show_structural_match(self, match: StructuralMatch, heuristic: StructuralHeuristic) -> None:
        originals = [self.lines[i] for i in match.line_indices]
        _, page_end = page_bounds(self.lines, self.current_page)
        crosses_page = max(match.line_indices) >= page_end
        note = "\n\n(this reaches onto the next page)" if crosses_page else ""

        edit_input = self.query_one(Input)
        if heuristic.kind == "merge":
            proposed_text = match.proposed[0] if match.proposed else ""
            self._show_instructions(
                f"Structural match ({heuristic.name}):\n\n"
                + "\n".join(f"  {line}" for line in originals)
                + "\n\nProposed merge -- edit and press Enter to confirm, Ctrl+R to reject:"
                + note
            )
            edit_input.value = proposed_text
            edit_input.display = True
            edit_input.focus()
        else:  # party_expansion
            proposals = match.proposed or ()
            pairs = "\n".join(f"  {orig}  ->  {prop}" for orig, prop in zip(originals, proposals))
            self._show_instructions(
                f"Structural match ({heuristic.name}), {len(match.line_indices)} lines:\n\n"
                + pairs
                + "\n\nPress Y to confirm all, Ctrl+R to reject all."
                + note
            )
            edit_input.value = ""
            edit_input.display = False
            self.query_one(ListView).focus()

    async def _commit_structural_merge(self, final_text: str) -> None:
        assert self._current_structural is not None
        match, heuristic = self._current_structural

        record = build_merge_record(self.lines, match, heuristic, final_text)
        self.history.append(record)

        start_idx = match.line_indices[0]
        spliced = splice_matched_lines(self.lines, match, [final_text])

        self._current_structural = None
        self._structural_search_start = start_idx + len(spliced)

        edit_input = self.query_one(Input)
        edit_input.value = ""
        edit_input.display = False

        # _advance_structural_review does its own refresh (see its
        # docstring) -- it needs to run regardless, to pick either the next
        # match or "nothing left", so there's no separate refresh call
        # needed here first.
        await self._advance_structural_review()

    async def action_confirm_structural_group(self) -> None:
        if self._current_structural is None:
            return
        match, heuristic = self._current_structural
        if heuristic.kind != "party_expansion":
            return

        records = build_party_expansion_records(self.lines, match, heuristic, confirmed=True)
        for record in records:
            self.history.append(record)

        proposals = list(match.proposed or ())
        start_idx = match.line_indices[0]
        spliced = splice_matched_lines(self.lines, match, proposals)

        self._current_structural = None
        self._structural_search_start = start_idx + len(spliced)

        await self._advance_structural_review()

    async def action_reject_structural(self) -> None:
        if self._current_structural is None:
            return
        match, heuristic = self._current_structural

        if heuristic.kind == "merge":
            record = build_merge_record(self.lines, match, heuristic, final_text=None)
            self.history.append(record)
        else:
            for record in build_party_expansion_records(self.lines, match, heuristic, confirmed=False):
                self.history.append(record)

        # self.lines itself doesn't change on a rejection, but the
        # ListView's highlighting does need to move off this match --
        # _advance_structural_review's own refresh handles that.
        self._current_structural = None
        self._structural_search_start = max(match.line_indices) + 1

        edit_input = self.query_one(Input)
        edit_input.value = ""
        edit_input.display = False

        await self._advance_structural_review()

    async def action_skip_guided(self) -> None:
        if self._guided_queue:
            self._guided_queue = []
            self._editing_index = None
            edit_input = self.query_one(Input)
            edit_input.value = ""
            edit_input.display = False
            self.query_one(ListView).focus()
            self._show_instructions("Guided review skipped. Edit anything you'd like, then move to the next page.")
        elif self._current_structural is not None:
            self._current_structural = None
            edit_input = self.query_one(Input)
            edit_input.value = ""
            edit_input.display = False
            self.query_one(ListView).focus()
            self._show_instructions(
                "Structural review skipped. Edit anything you'd like, then move to the next page."
            )
            # Clears the abandoned match's "structural-match" highlight --
            # unlike the guided-review branch above, whose "flagged" class
            # is a property of each line's content, not of review progress,
            # so it needs no refresh to stay accurate.
            await self._refresh_page()

    def _show_instructions(self, text: str) -> None:
        self.query_one("#instructions", Static).update(text)

    # --- editing --------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._guided_queue or self._current_structural is not None:
            # A guided phase (single-line or structural) is driving the
            # Input right now; ignore a stray Selected event rather than
            # let it clobber the pre-filled value.
            return
        list_view = self.query_one(ListView)
        within_page_index = list_view.index
        if within_page_index is None:
            return
        start, _ = page_bounds(self.lines, self.current_page)
        raw_index = start + within_page_index
        self._editing_index = raw_index
        edit_input = self.query_one(Input)
        edit_input.value = self.lines[raw_index]
        edit_input.display = True
        edit_input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._current_structural is not None:
            await self._commit_structural_merge(event.value)
            return

        if self._editing_index is None:
            return

        edited_index = self._editing_index
        start, _ = page_bounds(self.lines, self.current_page)
        within_page_index = edited_index - start
        in_guided_review = bool(self._guided_queue) and self._guided_queue[self._guided_position] == within_page_index
        proposed = self._guided_current_proposed if in_guided_review else None

        self._commit_edit(edited_index, event.value, guided=in_guided_review, proposed=proposed)

        edit_input = self.query_one(Input)
        edit_input.value = ""
        edit_input.display = False

        await self._refresh_page(restore_index=within_page_index)

        if in_guided_review:
            self._guided_position += 1
            await self._advance_guided_review()
        else:
            self._editing_index = None
            self.query_one(ListView).focus()

    def _commit_edit(self, raw_index: int, new_text: str, *, guided: bool, proposed: str | None) -> None:
        """The single shared path every single-line edit goes through,
        whichever of the three ways it was made: guided-review
        approve/override, the post-guided free-edit pass, or plain
        ad-hoc navigation-and-edit. (Structural edits have their own
        path -- see _commit_structural_merge / action_confirm_structural_group
        / action_reject_structural -- since they can add or remove lines,
        which a single-line rewrite never does.)
        """
        original = self.lines[raw_index]

        if new_text == original and not guided:
            return

        record = CorrectionRecord(
            line=content_line_number(self.lines, raw_index),
            initiator="heuristic" if guided else "user",
            kind="rewrite",
            original=original,
            proposed=proposed,
            final=new_text,
            reviewed=True,
        )
        self.lines[raw_index] = new_text
        self.history.append(record)

    def _save_history(self) -> None:
        self.history.save(self.history_path)

    async def on_unmount(self) -> None:
        self._save_history()


if __name__ == "__main__":
    import sys

    ReviewApp(Path(sys.argv[1])).run()

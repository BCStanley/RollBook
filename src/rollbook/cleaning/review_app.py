from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from rollbook.cleaning import pipeline
from rollbook.cleaning.corrections import CorrectionError, CorrectionHistory, CorrectionRecord
from rollbook.cleaning.pages import load_pages


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
    absolute line index the page starts at; `records` is any iterable of
    CorrectionRecord. Pure -- also testable on its own.
    """
    return {
        record.line - base
        for record in records
        if record.reviewed and base <= record.line < base + page_length
    }


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
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("J", "next_page", "Next page"),
        Binding("K", "prev_page", "Prev page"),
        Binding("escape", "skip_guided", "Skip guided review", show=False),
    ]

    def __init__(self, path: Path, history_path: Path | None = None) -> None:
        super().__init__()
        self.path: Path = path
        self.history_path: Path = history_path or path.with_suffix(".corrections.jsonl")

        raw_pages = load_pages(path)
        self.automatic_heuristics = pipeline.build_automatic_heuristics(pipeline.reporter_map)
        self.single_line_heuristics = pipeline.build_user_monitored_single_line(pipeline.reporter_map)

        self.pages: list[list[str]] = [
            [pipeline.apply_automatic_heuristics(line, self.automatic_heuristics) for line in page]
            for page in raw_pages
        ]

        self.history: CorrectionHistory = self._load_history()

        self.current_page: int = 0
        self._editing_index: int | None = None

        # Guided-review state for whichever page is currently on screen.
        # _guided_queue holds the within-page indices still to walk through;
        # _guided_position is how far through that queue we are.
        # _guided_current_proposed carries the heuristic's own proposed fix
        # (if any) for whichever line is currently being shown, so it can be
        # recorded on the CorrectionRecord once the user submits.
        self._guided_queue: list[int] = []
        self._guided_position: int = 0
        self._guided_current_proposed: str | None = None

    # --- setup ------------------------------------------------------------

    def _load_history(self) -> CorrectionHistory:
        try:
            return CorrectionHistory.load(self.history_path)
        except CorrectionError as e:
            # corrections.py raises the same CorrectionError for "file
            # missing" and "file present but unreadable" -- distinguished
            # here only via the chained original exception (`raise ... from
            # e` on that side is what makes this possible at all). A brand
            # new document with no history file yet is the expected case, so
            # that one specifically starts a fresh history; anything else
            # (malformed JSON, a record missing a field) is a real problem
            # and should not be silently treated the same way.
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

    def on_mount(self) -> None:
        self.title = "RollBook Review"
        self._update_subtitle()
        self.query_one(Input).display = False
        self.query_one(ListView).focus()
        self._start_guided_review()

    def _update_subtitle(self) -> None:
        self.sub_title = f"{self.path.name} — page {self.current_page + 1} of {len(self.pages)}"

    def _build_items(self, page_index: int) -> list[ListItem]:
        flagged = set(flagged_line_indices(self.pages[page_index], self.single_line_heuristics))
        items = []
        for index, line in enumerate(self.pages[page_index]):
            item = ListItem(Label(line, markup=False))
            if index in flagged:
                item.add_class("flagged")
            items.append(item)
        return items

    # --- page navigation ----------------------------------------------

    def action_cursor_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    async def action_next_page(self) -> None:
        if self.current_page < len(self.pages) - 1:
            self._save_history()
            self.current_page += 1
            await self._refresh_page()
            self._start_guided_review()

    async def action_prev_page(self) -> None:
        if self.current_page > 0:
            self._save_history()
            self.current_page -= 1
            await self._refresh_page()
            self._start_guided_review()

    async def _refresh_page(self, *, restore_index: int | None = None) -> None:
        list_view = self.query_one(ListView)
        await list_view.clear()
        for item in self._build_items(self.current_page):
            await list_view.append(item)
        if restore_index is not None:
            list_view.index = restore_index
        self._update_subtitle()

    # --- guided single-line review -----------------------------------

    def _start_guided_review(self) -> None:
        """Build the queue of lines to walk the user through on the page
        that's now on screen: every line the single-line heuristics still
        flag, minus any line that already has a reviewed=True record in the
        history (so revisiting a page you've already been through doesn't
        make you walk through it all over again).
        """
        base = self._absolute_line_index(self.current_page, 0)
        page_length = len(self.pages[self.current_page])
        already_reviewed = already_reviewed_indices(base, page_length, self.history.records)

        self._guided_queue = [
            index
            for index in flagged_line_indices(self.pages[self.current_page], self.single_line_heuristics)
            if index not in already_reviewed
        ]
        self._guided_position = 0

        if self._guided_queue:
            self._show_instructions(
                "Guided review: stepping through every flagged line on this page.\n\n"
                "Press Enter to accept the fix shown (editing it first if you'd "
                "rather), or Escape to skip the rest and edit freely."
            )
            self._advance_guided_review()
        else:
            self._show_instructions("No flagged lines left on this page. Select any line to edit it freely.")

    def _advance_guided_review(self) -> None:
        list_view = self.query_one(ListView)
        if self._guided_position >= len(self._guided_queue):
            self._show_instructions(
                "Guided review complete. Edit anything else you'd like, then move to the next page."
            )
            self._guided_queue = []
            self._editing_index = None
            edit_input = self.query_one(Input)
            edit_input.value = ""
            edit_input.display = False
            list_view.focus()
            return

        index = self._guided_queue[self._guided_position]
        list_view.index = index

        line = self.pages[self.current_page][index]
        defect = pipeline.first_flagged_defect(line, self.single_line_heuristics)
        self._guided_current_proposed = defect.proposed if defect else None
        prefill = self._guided_current_proposed if self._guided_current_proposed is not None else line

        self._editing_index = index
        edit_input = self.query_one(Input)
        edit_input.value = prefill
        edit_input.display = True
        edit_input.focus()

    def action_skip_guided(self) -> None:
        if self._guided_queue:
            self._guided_queue = []
            self._editing_index = None
            edit_input = self.query_one(Input)
            edit_input.value = ""
            edit_input.display = False
            self.query_one(ListView).focus()
            self._show_instructions("Guided review skipped. Edit anything you'd like, then move to the next page.")

    def _show_instructions(self, text: str) -> None:
        self.query_one("#instructions", Static).update(text)

    # --- editing --------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._guided_queue:
            # Guided review is driving the Input right now; ignore a stray
            # Selected event rather than let it clobber the pre-filled value.
            return
        list_view = self.query_one(ListView)
        index = list_view.index
        if index is None:
            return
        self._editing_index = index
        edit_input = self.query_one(Input)
        edit_input.value = self.pages[self.current_page][index]
        edit_input.display = True
        edit_input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._editing_index is None:
            return

        edited_index = self._editing_index
        in_guided_review = bool(self._guided_queue) and self._guided_queue[self._guided_position] == edited_index
        proposed = self._guided_current_proposed if in_guided_review else None

        self._commit_edit(edited_index, event.value, guided=in_guided_review, proposed=proposed)

        edit_input = self.query_one(Input)
        edit_input.value = ""
        edit_input.display = False

        await self._refresh_page(restore_index=edited_index)

        if in_guided_review:
            self._guided_position += 1
            self._advance_guided_review()
        else:
            self._editing_index = None
            self.query_one(ListView).focus()

    def _commit_edit(self, index: int, new_text: str, *, guided: bool, proposed: str | None) -> None:
        """The single shared path every edit goes through, whichever of the
        three ways it was made: guided-review approve/override, the
        post-guided free-edit pass, or plain ad-hoc navigation-and-edit.
        """
        original = self.pages[self.current_page][index]
        self.pages[self.current_page][index] = new_text

        # A free edit where nothing actually changed (the user selected a
        # line and pressed Enter without touching it) has nothing to record.
        # A guided-review line always gets a record even when unchanged --
        # that's a "confirmed as reviewed" entry, not a no-op, per Ben's
        # decision that approving a proposal unchanged still logs.
        if new_text == original and not guided:
            return

        record = CorrectionRecord(
            line=self._absolute_line_index(self.current_page, index),
            initiator="heuristic" if guided else "user",
            kind="rewrite",
            original=original,
            proposed=proposed,
            final=new_text,
            reviewed=True,
        )
        self.history.append(record)

    def _absolute_line_index(self, page_index: int, line_index: int) -> int:
        return sum(len(page) for page in self.pages[:page_index]) + line_index

    def _save_history(self) -> None:
        self.history.save(self.history_path)

    async def on_unmount(self) -> None:
        self._save_history()


if __name__ == "__main__":
    import sys

    ReviewApp(Path(sys.argv[1])).run()

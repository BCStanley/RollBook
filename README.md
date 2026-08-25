# RollBook

RollBook turns scans of nineteenth-century case indexes into a structured, queryable database of the authorities they cite. It's a from-scratch, tested, installable rewrite of [`case_locator`](https://github.com/BCStanley/case_locator), following the architecture set out in the project's specification.

**Status: Phase 0 — scaffolding.** The package installs and the CLI is wired up; none of the pipeline systems have real logic behind them yet. See the roadmap below.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Usage

```bash
rollbook --help
```

Each pipeline stage is its own subcommand group — `ocr`, `clean`, `parse`, `canon`, `build-db`, `match`, `narrow`, `review`, `index`, `models` — corresponding one-to-one with a "system" in the architecture below. Run `rollbook <group> --help` for details on any of them.

## Architecture

The pipeline is a sequence of systems, each with a fixed input/output contract, so any one of them can be rewritten or improved without the others changing:

| System | Job | Input → Output |
|---|---|---|
| `ocr_io` | Adapter over a trained OCR model + model manifest/pull | scan → raw text |
| `cleaning` | Correct & normalize raw OCR output | raw text → clean lines |
| `parsing` | Split lines into structured case records | clean lines → case records |
| `canonical` | Abbreviation expansion, entity standardization, normalization | case record → case tokens |
| `candidatedb` | Build & query the SQLite candidate database | .txt authority lists → SQLite db |
| `matching` | Rule-based pass + fuzzy scoring fallback | tokens + db → ranked candidates |
| `narrow` | Rank/format candidates for human review | ranked candidates → review CSV |
| `review` | Ingest a hand-reviewed CSV (KEEP/DROP/MAYBE) | reviewed CSV → confirmed matches |
| `index` | Compile confirmed matches into the final index | confirmed matches → final database |

OCR models (one per book/typeface/edition, growing over time) aren't committed to this repository — they ship as GitHub Release assets, listed in an in-repo manifest and fetched on demand with `rollbook models pull <name>`.

## Roadmap

| Phase | Focus |
|---|---|
| 0 | Scaffolding — this phase |
| 1 | Domain models & config loader |
| 2 | `ocr_io` + `cleaning` |
| 3 | `parsing` |
| 4 | `canonical` |
| 5 | `candidatedb` |
| 6 | `matching` — target: recall ≥ 99%, precision ≈ 50% (top 10 candidates) against the golden match set |
| 7 | `narrow` + `review` + `index` |
| 8 | Docs & packaging polish |

Deferred beyond this rewrite: rebuilding the Escriptorum/Kraken OCR training pipeline itself, an interactive review UI in place of the CSV workflow, and embedding-based semantic matching.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

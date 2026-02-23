- Use `kinds_json` column with `json_each` for filtering and counting.
- This avoids the overhead of a many-to-many join table while fixing the "substring match" problem of `LIKE`.

- 2026-02-23 Scope reconciliation evidence (`git status --porcelain=v1`, `git diff --name-only`, `git diff --stat`, endpoint grep) captured before classification.
- `git diff --name-only` tracked files: `app/analysis_worker.py`, `app/kakaotalk_parser.py`, `app/main.py`, `app/static/index.html`, `app/storage.py`, `pyproject.toml`, `tests/test_api.py`, `tests/test_service.py`, `uv.lock`.
- `git status --porcelain=v1` additionally shows untracked: `app/note_kinds.py`, `tests/test_note_kinds.py`, `.sisyphus/`.
- Endpoint grep result: `/api/v1/notes/batch`, `/api/v1/import/urls-csv`, `/api/v1/search` occur in `app/main.py` and `tests/test_api.py` (Commit C scope markers).

| File path | Scope bucket | Rationale |
| --- | --- | --- |
| `app/note_kinds.py` | A | New note-kind domain logic (`KIND_ORDER`, URL classification, compute kinds). |
| `tests/test_note_kinds.py` | A | Direct tests for note-kind classification behavior. |
| `app/static/index.html` | B | UI kind filters/badges and social embed viewer (Instagram/Threads). |
| `app/analysis_worker.py` | D | Mostly refactor/formatting + minor analysis-path cleanup; not kind API or extra endpoints. |
| `pyproject.toml` | D | Dependency/tooling update (`python-multipart`). |
| `uv.lock` | D | Lockfile update for dependency/tooling change. |
| `app/kakaotalk_parser.py` | C (mixed C+D) | Adds `parse_urls_csv_bytes` for new import endpoint; also contains incidental formatting. |
| `app/main.py` | MIXED (A+C+D) | Contains kind API/filter/startup backfill (A), extra endpoints `/api/v1/import/urls-csv` + `/api/v1/notes/batch` + `/api/v1/search` rewrite (C), plus type/refactor/date parsing cleanup (D). |
| `app/storage.py` | MIXED (A+C+D) | Adds kind persistence/filter/count/backfill (A), batch metadata update path used by batch endpoint (C), plus broad typing/refactor adjustments (D). |
| `tests/test_api.py` | MIXED (A+B+C) | Includes kind filter/count tests (A), social embed markup test (B), and extra endpoint/search/batch tests (C). |
| `tests/test_service.py` | MIXED (A+C+D) | Adds note-kind/backfill tests (A), URL CSV + batch metadata tests (C), and typing/refactor edits (D). |

- Mixed-scope split requirements before commit:
  - `app/main.py`: split by endpoint/feature hunks into A(kind endpoints/filter/backfill), C(extra endpoints/search), D(type/date/refactor).
  - `app/storage.py`: split into A(kind schema/kinds_json/list/count/backfill), C(batch update + parser-linked flow support), D(generic typing/format-only refactor).
  - `tests/test_api.py`: split tests to follow implementation commits: A(kind tests), B(social embed UI test), C(extra endpoint/search/batch tests).
  - `tests/test_service.py`: split into A(kind/backfill tests), C(parse_urls_csv_bytes + batch metadata tests), D(refactor-only typing cleanup if any remains).
  - `app/kakaotalk_parser.py`: isolate `parse_urls_csv_bytes` in C; keep pure formatting-only lines in D only if needed.

# Note Kind Grouping/Filtering (Plain / YouTube / Instagram / Reels / Threads / Other)

## TL;DR
> **Summary**: Add multi-label “note kinds” derived from `sourceUrl` + URLs found in note text, persist them in SQLite for correct pagination, and expose filters + counts so the UI can “모아보기” by kind.
> **Deliverables**:
> - Backend: kind classifier + URL extractor; persisted `primary_kind` + `kinds_json`; `GET /api/v1/notes?kind=...`; `GET /api/v1/note-kinds`
> - Frontend: kind chips (평문/유튜브/인스타/릴스/스레드/기타) to filter notes; kind badges on cards
> - Tests: unittest coverage for classifier, persistence/backfill, and API filtering/counts
> **Effort**: Medium
> **Parallel**: YES - 2 waves
> **Critical Path**: Persist kinds in DB → API filter/counts → UI chips

## Context
### Original Request
- 모든 메모가 URL이 아니고 평문 텍스트 메모도 존재.
- 평문/유튜브링크/인스타링크/스레드링크/기타링크/인스타 릴스 링크 등 “메모 종류별로 모아보기” 기능 원함.

### Interview Summary
- Decision: `sourceUrl`뿐 아니라 `contentFull` 안의 URL도 스캔해서 종류 분류 (multi-label).

### Metis Review (gaps addressed)
- Defined `plain_text` semantics (origin-based via `sourceUrl` scheme) while still allowing additional kinds from `contentFull`.
- Defined `other_link` as non-exclusive (can co-exist with other kinds when multiple URLs exist).
- Counts endpoint supports same filters as `/api/v1/notes` (minus pagination) so UI can show “현재 필터 내 종류 분포”.
- Added guardrails: no network-based URL expansion; no post-processing filtering that breaks pagination.

## Work Objectives
### Core Objective
Users can filter note list by “kind” (평문/YouTube/Instagram/Instagram Reels/Threads/Other Link), even when the kind is derived from URLs inside `contentFull`.

### Deliverables
- SQLite schema additions (non-breaking) for persisted kinds
- Backend kind computation + backfill
- API updates + counts endpoint
- UI controls for kind filtering + display
- Automated tests + agent-executed QA scenarios

### Definition of Done (verifiable)
- `uv run python -m unittest discover -s tests` exits 0.
- `GET /api/v1/notes?kind=youtube` returns only items whose `kinds` includes `youtube`.
- UI at `/` shows kind filter chips; selecting “유튜브” triggers API call with `kind=youtube` and updates list.

### Must Have
- Multi-label classification (note can match multiple kinds)
- Server-side filtering (pagination-safe)
- Works for KakaoTalk imported memos (`kakaotalk://...`) + URL ingestion notes

### Must NOT Have (guardrails)
- No external network calls for classification (no expanding short links)
- No Python-side filtering after SQL query (must keep pagination/total correct)
- No massive refactor of UI architecture (keep changes localized to `app/static/index.html`)

## Verification Strategy
> ZERO HUMAN INTERVENTION — all verification is agent-executed.
- Test decision: tests-after (unittest)
- Evidence: each QA scenario writes an artifact under `.sisyphus/evidence/`

## Execution Strategy
### Parallel Execution Waves

Wave 1 (Backend foundations)
- Classifier + URL extractor module + unit tests
- SQLite schema + persistence + backfill + unit tests

Wave 2 (API + UI + integration)
- API: kind filter + counts endpoint + integration tests
- Frontend: kind chips + badges + Playwright QA scenarios

### Dependency Matrix (high level)
- Backend schema/persistence blocks API filter/counts.
- API filter/counts blocks UI chips.

## TODOs

- [x] 1. Define kind taxonomy + URL extraction rules (backend)

  **What to do**:
  - Add a stable enum-like set of kind IDs:
    - `plain_text`
    - `youtube`
    - `instagram_post`
    - `instagram_reel`
    - `threads`
    - `other_link`
  - Define deterministic classification rules:
    - **Primary kind** = based on `sourceUrl`:
      - `plain_text` if `sourceUrl` scheme is not `http/https` (ex: `kakaotalk://...`)
      - otherwise classify by host/path to one of `youtube/instagram_post/instagram_reel/threads/other_link`
    - **Contained kinds** = extract all `http(s)` URLs found in concatenated text:
      - scan fields: `contentFull`, `summaryShort`, `summaryLong` (and optionally `sourceUrl` as text)
      - for each URL, add kind based on host/path
      - if URL is http(s) but not recognized, add `other_link`
    - **Final kinds** = union of `{primaryKind} ∪ containedKinds` (unique, stable ordering).
  - Exact URL → kind matching rules (decision-complete):
    - Parse with `urllib.parse.urlparse` (backend) / `new URL()` (frontend tests only if needed)
    - Normalize: `host = hostname.lower()`, `path = pathname.lower()`
    - `youtube` if `host` in `{ "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be" }`
    - `instagram_reel` if (`host` endswith `"instagram.com"` or `host == "instagr.am"`) and (`"/reel/" in path` or `"/reels/" in path`)
    - `instagram_post` if (`host` endswith `"instagram.com"` or `host == "instagr.am"`) and (`"/p/" in path` or `"/tv/" in path`)
    - `threads` if `host` endswith `"threads.net"` and `"/post/" in path`
    - `other_link` if scheme is http/https and none of the above matched
  - Kind ordering in API response (stable):
    - Always return kinds in this order: `plain_text`, `youtube`, `instagram_post`, `instagram_reel`, `threads`, `other_link`
    - If a kind is not present, omit it.
  - URL extraction rules (no network):
    - regex match `https?://[^\s"'<>]+`
    - trim trailing punctuation: `).,!?]}`
    - cap work: max 50 URLs per note; max 50k chars scanned

  **Must NOT do**:
  - Don’t attempt to resolve redirects or expand short links.
  - Don’t introduce new kinds beyond the list above in v1.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: careful taxonomy + edge cases
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 2, 3 | Blocked By: none

  **References**:
  - UI precedent for URL scanning: `app/static/index.html` (`extractSocialLinks(note)`)
  - KakaoTalk plain memo sourceUrl scheme: `app/kakaotalk_parser.py` (`row_to_note`)

  **Acceptance Criteria**:
  - [ ] New module exists (e.g. `app/note_kinds.py`) exposing `extract_urls(text)`, `classify_url(url)`, `compute_note_kinds(note_dict)`.
  - [ ] `uv run python -m unittest discover -s tests` includes new unit tests for these functions.

  **QA Scenarios**:
  ```
  Scenario: Multi-label classification
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_service
    Expected:
      - Tests include a case where a kakaotalk note containing a YouTube URL yields kinds including both plain_text and youtube.
    Evidence: .sisyphus/evidence/task-1-kind-classifier.txt

  Scenario: URL extraction trimming
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_service
    Expected:
      - A URL with trailing ')' or '.' is still recognized and classified correctly.
    Evidence: .sisyphus/evidence/task-1-url-trim.txt
  ```

  **Commit**: YES | Message: `feat(kinds): add note kind taxonomy + URL extraction`
Verification actually run: uv run python -m unittest tests/test_note_kinds.py (verified URL trim, multi-label, and stable ordering).


- [x] 2. Add SQLite persistence for kinds (schema + write paths) + tests

  **What to do**:
  - Extend SQLite schema in `SQLiteStore._init_schema()` to ensure columns:
    - `primary_kind TEXT` (nullable allowed for existing rows; backfill will populate)
    - `kinds_json TEXT NOT NULL DEFAULT '[]'`
  - Update write paths to compute + store kinds:
    - `SQLiteStore.create_note(...)`: compute from the incoming note payload
    - `SQLiteStore.update_note(...)`: recompute when `sourceUrl/contentFull/summaryShort/summaryLong` change
    - (If batch update does not affect content/sourceUrl, it can skip recompute)
  - Update read paths to include in returned note dict:
    - `primaryKind` (string)
    - `kinds` (array of strings)

  **Must NOT do**:
  - Don’t change `source_url TEXT NOT NULL` constraint in this scope.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: schema evolution + back-compat
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 3, 4 | Blocked By: 1

  **References**:
  - Schema init + `_ensure_column`: `app/storage.py`
  - Notes table definition: `app/storage.py` (CREATE TABLE notes)
  - Existing JSON storage pattern: `tags_json`, `hashtags_json` in `app/storage.py`

  **Acceptance Criteria**:
  - [ ] Creating/updating a note writes `primary_kind` and `kinds_json`.
  - [ ] `get_note()` returns `primaryKind` and `kinds`.
  - [ ] Tests cover that a note updated to add a Threads URL gains `threads` in kinds.

  **QA Scenarios**:
  ```
  Scenario: Persisted kinds survive reload
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_service
    Expected:
      - Test creates a note, reads it back, asserts kinds fields exist and contain expected IDs.
    Evidence: .sisyphus/evidence/task-2-kinds-persist.txt

  Scenario: Update recomputes kinds
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_service
    Expected:
      - After update_note(contentFull=...) kinds_json changes accordingly.
    Evidence: .sisyphus/evidence/task-2-kinds-update.txt
  ```

  **Commit**: YES | Message: `feat(storage): persist note kinds in sqlite`
Verification actually run: uv run python -m unittest tests/test_service.py (verified persistence and update-time recomputation).


- [x] 3. Backfill existing notes’ kinds (startup-safe) + tests

  **What to do**:
  - Add `SQLiteStore.backfill_note_kinds(batch_size: int = 5000) -> dict`:
    - Select notes where `kinds_json` is missing/empty (NULL or '[]')
    - Compute kinds and update those rows
    - Return counts `{scanned, updated}`
  - Wire into app startup in `app/main.py` behind env flag:
    - `NOTE_NOMI_BACKFILL_KINDS_ON_STARTUP` default `true`
    - Log a single info line with `{updated}`
  - Add a unit test that creates notes without kinds_json (simulate legacy) and then runs backfill.

  **Must NOT do**:
  - Don’t block startup for extremely large DBs without a cap; include a max row limit (ex: 20k) per startup run.

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: migration-like behavior without migrations
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 4 | Blocked By: 2

  **References**:
  - Store init is created at import time and used in `app/main.py`.

  **Acceptance Criteria**:
  - [ ] Backfill runs only when env flag is enabled.
  - [ ] Backfill updates legacy notes (kinds_json empty) and leaves already-populated notes unchanged.

  **QA Scenarios**:
  ```
  Scenario: Backfill does not regress tests
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest discover -s tests
    Expected:
      - All tests pass.
    Evidence: .sisyphus/evidence/task-3-backfill-tests.txt
  ```

  **Commit**: YES | Message: `feat(kinds): add startup backfill for legacy notes`
Verification actually run: uv run python -m unittest tests/test_service.py (verified backfill repair behavior and idempotency).


- [x] 4. Add API support for kind filter on `/api/v1/notes` (pagination-safe) + tests

  **What to do**:
  - Extend `GET /api/v1/notes` in `app/main.py`:
    - Add query param `kind: str | None`
  - Extend `SQLiteStore.list_notes(...)` and `_build_notes_filter(...)` to accept `kind`.
  - Implement SQL filtering using persisted `kinds_json`:
    - Preferred: `EXISTS (SELECT 1 FROM json_each(notes.kinds_json) WHERE json_each.value = ?)`
    - Fallback: `kinds_json LIKE ?` with param `%"{kind}"%` only if JSON1 is unavailable
    - validate kind is one of allowed IDs; otherwise 400 `invalid_kind`
  - Add API test:
    - Create a KakaoTalk note containing YouTube URL
    - Assert `/api/v1/notes?kind=youtube` includes it
    - Assert `/api/v1/notes?kind=instagram_reel` excludes it

  **Must NOT do**:
  - Don’t compute kinds on the fly in list query.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: API contract + SQL filter correctness
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: 5 | Blocked By: 2, 3

  **References**:
  - Notes list endpoint: `app/main.py` (`@app.get("/api/v1/notes")`)
  - Filter builder: `app/storage.py` (`_build_notes_filter`)
  - Existing validation pattern for enums: `sort: Literal[...]` in `app/main.py`

  **Acceptance Criteria**:
  - [ ] `/api/v1/notes?kind=youtube` returns only notes whose `kinds` includes `youtube`.
  - [ ] `total` reflects filtered total (not just page length).

  **QA Scenarios**:
  ```
  Scenario: API kind filter
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_api
    Expected:
      - Integration test asserts kind filtering and totals.
    Evidence: .sisyphus/evidence/task-4-api-kind-filter.txt
  ```

  **Commit**: YES | Message: `feat(api): support kind filter for notes list`
Verification actually run: uv run python -m unittest tests/test_api.py (verified kind filtering and totals).


- [x] 5. Add `/api/v1/note-kinds` counts endpoint (respects same filters) + tests

  **What to do**:
  - Add endpoint `GET /api/v1/note-kinds` in `app/main.py`:
    - Accept same filter params as `/api/v1/notes` except `page/size/sort`.
    - Return `{items:[{kind,count}], totalNotes}`.
    - Counts are overlapping (multi-label); document in response.
  - Implement `SQLiteStore.count_note_kinds(...)`:
    - Reuse `_build_notes_filter(...)` without the `kind` clause (counts across all kinds)
    - Preferred: join `json_each(notes.kinds_json)` and `GROUP BY json_each.value`
    - Fallback: `SUM(CASE WHEN kinds_json LIKE '%"kind"%' THEN 1 ELSE 0 END)` only if JSON1 is unavailable
  - Add API test:
    - Insert fixture notes of each kind
    - Assert counts are correct

  **Must NOT do**:
  - Don’t fetch all notes into Python to compute counts.

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: shared filter semantics and SQL safety
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: 6 | Blocked By: 2, 3

  **References**:
  - Existing counts endpoint: `app/main.py` (`/api/v1/tags`) + `app/storage.py` (`list_tags`)

  **Acceptance Criteria**:
  - [ ] Endpoint returns a stable list of kinds with integer counts.
  - [ ] Counts change when filtering by category/tag/status/date.

  **QA Scenarios**:
  ```
  Scenario: Kind counts endpoint
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_api
    Expected:
      - Test asserts counts include multi-label overlaps when contentFull contains multiple URLs.
    Evidence: .sisyphus/evidence/task-5-kind-counts.txt
  ```

  **Commit**: YES | Message: `feat(api): add note kind counts endpoint`
Verification actually run: uv run python -m unittest tests/test_api.py (verified counts with multi-label overlaps).


- [x] 6. Frontend: add kind chips + kind badges (filter-driven) + (optional) Playwright QA

  **What to do**:
  - Implement kind chips (and counts) in `app/static/index.html` list page:
    - Chips: `전체`, `평문`, `유튜브`, `인스타`, `릴스`, `스레드`, `기타`
    - Selected chip calls `/api/v1/notes?...&kind=<id>` (except `전체`)
    - Fetch counts from `/api/v1/note-kinds` and show `(<count>)` when available
  - Render kind badges on each note card using `note.kinds` returned by API.
  - (Out-of-scope for kinds but shipped here) Note detail shows swipeable Instagram/Threads embeds when URLs are present.

  **Must NOT do**:
  - Don’t re-implement classification in JS for filtering (use API + returned `kinds`).

  **Recommended Agent Profile**:
  - Category: `visual-engineering` — Reason: UI controls + responsive behavior
  - Skills: [`playwright`] — Reason: agent-executed UI QA

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 4, 5

  **References**:
  - Current UI list view: `app/static/index.html` (`function App()`)
  - Existing tag filter chip UI: `app/static/index.html` (tag-filter)

  **Acceptance Criteria**:
  - [ ] Selecting each chip updates the note list and persists in state (no full reload required).
  - [ ] Note cards show kind badges that match API `kinds`.

  **QA Scenarios**:
  ```
  Scenario: UI kind chips use API kind filter
    Tool: Playwright
    Steps:
      1) Ensure deps: uv sync
      2) Start server: uv run uvicorn app.main:app --reload
      3) Open http://127.0.0.1:8000/
      4) Create 2 notes via API (or import CSV):
         - one KakaoTalk-like plain memo with a YouTube URL in content
         - one note without any URL
      5) Click chip "유튜브"
    Expected:
      - Network call includes `kind=youtube`
      - List shows only note(s) whose badges include "유튜브"
    Evidence: .sisyphus/evidence/task-6-ui-kind-youtube.png

  Scenario: Note detail renders social embed strip
    Tool: Playwright
    Steps:
      1) Open a note whose content includes an Instagram / Threads URL
      2) Scroll to "연결된 소셜 페이지"
    Expected:
      - Instagram/Threads embed container renders; horizontal swipe scroll is possible
    Evidence: .sisyphus/evidence/task-6-social-embeds.png
  ```

  **Commit**: YES | Message: `feat(ui): add note kind filter chips + badges`
Verification actually run: Playwright blocked (Chrome missing at /opt/google/chrome/chrome); fallback API verification confirmed filtered counts (all=86, plain_text=8, youtube=8, etc.).


- [x] 7. Scope reconciliation: confirm which non-kind changes to keep

  **What to do**:
  - Run `git status --porcelain=v1` and `git diff --name-only`.
  - Identify changes not required for “note kind 모아보기 + social embed view” and classify into:
    - Keep in this branch (commit separately)
    - Revert/undo in this branch
  - Expected non-kind changes currently present (verify):
    - `app/main.py`: adds `PATCH /api/v1/notes/batch`, `POST /api/v1/import/urls-csv`, refactors `/api/v1/search` to use `store.list_notes(q=..., q_scope=...)`
    - `app/kakaotalk_parser.py`: adds `parse_urls_csv_bytes()`
    - `app/analysis_worker.py`: formatting/refactor around codex confidence parsing
    - `pyproject.toml`, `uv.lock`: dependency/tooling changes (verify exactly what)

  **Must NOT do**:
  - Don’t silently ship scope creep in the same commit as kinds/UI work.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: risk management + release hygiene
  - Skills: [`git-master`] — Reason: clean, atomic commit strategy

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: 9 | Blocked By: none

  **Acceptance Criteria**:
  - [ ] A written decision exists in the PR/commit history: keep vs revert for each non-kind change.

  **QA Scenarios**:
  ```
  Scenario: Audit diffs and classify scope
    Tool: Bash
    Steps:
      1) Run: git status --porcelain=v1
      2) Run: git diff --name-only
    Expected:
      - A definitive list of files to commit (kinds scope) vs separate/revert (non-kinds scope).
    Evidence: .sisyphus/evidence/task-7-scope-audit.txt
  ```

  **Commit**: NO
Verification actually run: git status --porcelain=v1 and git diff --name-only audited; scope reconciliation documented in .sisyphus/notepads/note-kind-views/decisions.md.


- [x] 8. Update plan checkboxes + QA evidence log

  **What to do**:
  - For each completed TODO (1–6), ensure checkboxes are `[x]` and add a one-line note under each task with the verification command(s) actually run.
  - Add references to produced artifacts under `.sisyphus/evidence/`.

  **Recommended Agent Profile**:
  - Category: `writing`
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: 9 | Blocked By: none

  **Acceptance Criteria**:
  - [ ] This plan file reflects reality (no stale unchecked work).

  **QA Scenarios**:
  ```
  Scenario: Plan reflects executed work
    Tool: Bash
    Steps:
      1) Run: test -f .sisyphus/plans/note-kind-views.md
    Expected:
      - Plan TODO statuses match actual repository state.
    Evidence: .sisyphus/evidence/task-8-plan-updated.txt
  ```

  **Commit**: NO
Verification actually run: Plan updated with verification logs from notepads; TODO 8 marked complete.


- [x] 9. Refactor “extra” API endpoints out of `app/main.py` (to enable separate commits)

  **What to do**:
  - Create a new module `app/extra_routes.py` that holds ONLY the non-kind endpoints currently mixed into `app/main.py`:
    - `PATCH /api/v1/notes/batch`
    - `POST /api/v1/import/urls-csv`
    - `GET /api/v1/search`
  - Implementation shape (decision-complete):
    - In `app/extra_routes.py`, define `router = APIRouter()`.
    - Move the following into that module (and adjust imports accordingly):
      - `NoteBatchPatchRequest`
      - helper `_snippet(...)`
      - the 3 endpoints listed above
    - In `app/main.py`, remove those definitions and add:
      - `from app.extra_routes import router as extra_router`
      - `app.include_router(extra_router)`
  - Keep kinds/backfill/export fixes in `app/main.py`.

  **Must NOT do**:
  - Don’t change any endpoint paths, response schemas, or query param names.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: safe refactor with API surface stability
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 10 | Blocked By: 7

  **References**:
  - Current endpoints live in: `app/main.py`

  **Acceptance Criteria**:
  - [ ] `uv run python -m unittest discover -s tests` exits 0 after refactor.
  - [ ] Grep shows the 3 endpoints are defined in `app/extra_routes.py` and not in `app/main.py`.

  **QA Scenarios**:
  ```
  Scenario: API routes unchanged after refactor
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest tests.test_api
    Expected:
      - Existing API tests still pass (no route/path changes).
    Evidence: .sisyphus/evidence/task-9-extra-routes-tests.txt
  ```

  **Commit**: YES | Message: `refactor(api): extract extra endpoints into module`
  Verification actually run: uv run python -m unittest tests/test_api.py (routes moved to app/extra_routes.py; tests OK).


- [x] 10. Final automated verification (pre-commit gate)

  **What to do**:
  - Run the full unit test suite.
  - Run `biome check` on `app/static/index.html` (if biome is available in the environment).

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: 11 | Blocked By: 9

  **Acceptance Criteria**:
  - [ ] `uv run python -m unittest discover -s tests` exits 0.

  **QA Scenarios**:
  ```
  Scenario: Full test pass
    Tool: Bash
    Steps:
      1) Run: uv run python -m unittest discover -s tests
    Expected:
      - Exit code 0
    Evidence: .sisyphus/evidence/task-10-tests.txt
  ```

  **Commit**: NO
  Verification actually run: uv run python -m unittest discover -s tests (OK); biome check app/static/index.html (OK).


- [x] 11. Create commits (separate scopes)

  **What to do**:
  - Commit A (kinds backend + API):
    - Message: `feat(kinds): persist and filter notes by kind`
    - Files (expected): `app/note_kinds.py`, `app/storage.py`, `app/main.py`, `tests/test_note_kinds.py`, `tests/test_api.py`, `tests/test_service.py`
  - Commit B (UI + social embeds):
    - Message: `feat(ui): add kind chips and social embeds`
    - Files (expected): `app/static/index.html`
  - Commit C (extra endpoints):
    - Message: `feat(api): add urls-csv import and batch patch`
    - Files (expected): `app/extra_routes.py`, `app/kakaotalk_parser.py`
  - Commit D (deps/tooling/refactors):
    - Message: `chore: update deps and misc refactors`
    - Files (expected): `pyproject.toml`, `uv.lock`, `app/analysis_worker.py`
  - Do NOT commit `.sisyphus/`.

  **Must NOT do**:
  - Don’t mix unrelated file groups across commits.
  - Don’t amend commits.

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: [`git-master`]

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: F1-F4 | Blocked By: 10

  **Acceptance Criteria**:
  - [ ] `git status` shows a clean tree (except untracked `.sisyphus/`).
  - [ ] `git log -5 --oneline` shows the 3–4 new commit messages in order.

  **QA Scenarios**:
  ```
  Scenario: Verify commit separation
    Tool: Bash
    Steps:
      1) Run: git show --name-only --oneline -1
    Expected:
      - Last commit contains only files appropriate for that commit scope.
    Evidence: .sisyphus/evidence/task-11-commit-files.txt
  ```

  **Commit**: YES | Message: (as above)
  Verification actually run: git log shows 4 local commits (6b3f2c6, ff2a20c, bdee605, 34e31ee); git status clean except untracked .sisyphus/.


## Final Verification Wave (4 parallel agents, ALL must APPROVE)
- [x] F1. Plan Compliance Audit — oracle

  **What to do**:
  - Oracle reviews `.sisyphus/plans/note-kind-views.md` plus `git diff --stat`.
  - Confirms:
    - kinds taxonomy matches implementation
    - server-side filtering/counting is pagination-safe
    - commits follow the plan’s separation

  **Acceptance Criteria**:
  - [x] Oracle verdict is “APPROVE” with 0 critical issues.

  **Evidence**: `.sisyphus/evidence/f1-oracle.txt`

- [x] F2. Code Quality Review — unspecified-high

  **What to do**:
  - Review changed Python + frontend code for:
    - correctness, edge cases, error handling
    - API schema consistency
    - no accidental breaking changes

  **Acceptance Criteria**:
  - [x] Reviewer verdict “APPROVE” or “APPROVE WITH NITS” (no functional issues).

  **Evidence**: `.sisyphus/evidence/f2-quality.txt`

- [x] F3. Real QA (agent-executed) — unspecified-high (+ playwright)

  **What to do**:
  - Run:
    - `uv run python -m unittest discover -s tests`
  - If Playwright is available, execute the UI scenarios from TODO 6 and save screenshots.
  - If Playwright is not available, perform API-level verification:
    - create notes with mixed kinds
    - call `/api/v1/notes?kind=...` and `/api/v1/note-kinds`

  **Acceptance Criteria**:
  - [x] UI or API verification demonstrates kind filtering works end-to-end.

  **Evidence**: `.sisyphus/evidence/f3-qa.txt`

- [x] F4. Scope Fidelity Check — deep

  **What to do**:
  - Validate all shipped changes map to one of:
    - kinds feature
    - social embeds
    - explicitly accepted “extra endpoints” (kept separately)
  - Confirm no secrets or env files are included.

  **Acceptance Criteria**:
  - [x] No unacknowledged scope creep.

  **Evidence**: `.sisyphus/evidence/f4-scope.txt`

## Commit Strategy
- Prefer 1 commit per TODO (1–6). If tasks are tiny, squash into fewer commits but keep messages scoped.

## Success Criteria
- Users can reliably “모아보기” by kind via UI chips.
- API filtering/counts are consistent with persisted `kinds_json` and do not break pagination.
- All automated tests pass.

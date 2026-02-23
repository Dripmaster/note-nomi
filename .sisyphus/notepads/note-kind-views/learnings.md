- SQLite `json_each` is the preferred way to query JSON arrays over `LIKE` for correctness.
- For small datasets, O(N) table scans for JSON parsing are acceptable in SQLite.
- Counting elements in a JSON array across rows is best done by joining with `json_each`.
2026-02-23
- Added `app/note_kinds.py` with three plan-facing helpers: `extract_urls`, `classify_url`, and `compute_note_kinds`.
- URL extraction is capped to 50k scanned characters and 50 matches, with regex `https?://[^\s\"'<>]+` and trailing punctuation trim set `).,!?]}`.
- Classification is deterministic via `urlparse` hostname/path rules and returns only v1 IDs: `plain_text`, `youtube`, `instagram_post`, `instagram_reel`, `threads`, `other_link`.
- `compute_note_kinds` scans `sourceUrl`, `contentFull`, `summaryShort`, `summaryLong`; primary kind remains origin-based (`plain_text` for non-http/https source URLs) and can co-exist with contained link kinds.
- Added `tests/test_note_kinds.py` coverage for URL trim behavior, KakaoTalk + YouTube multi-label, Instagram post/reel split, Threads detection, other-link fallback, and stable output ordering.

2026-02-23
- Added SQLite note-kind persistence in app/storage.py: schema now ensures notes.primary_kind and notes.kinds_json columns.
- create_note and update_note now compute kinds with compute_note_kinds from source/content/summary fields and persist kinds_json via json.dumps(..., ensure_ascii=False).
- _row_to_note now returns primaryKind and kinds from stored columns, with fallback recomputation when columns are missing, NULL, or invalid JSON for backward compatibility.
- Added tests/test_service.py coverage for create-time persistence and update-time recomputation (including add/remove of embedded YouTube kind).

2026-02-23
- Added `SQLiteStore.backfill_note_kinds(batch_size=5000, max_rows=20000)` to repair legacy rows where `kinds_json` is `NULL`, empty string, or `[]`, with capped batched updates and `{scanned, updated}` return counts.
- Startup now runs a one-shot kinds backfill in `app/main.py` when `NOTE_NOMI_BACKFILL_KINDS_ON_STARTUP` is truthy (default enabled) and logs one info line with the updated row count.
- Added service tests that simulate legacy rows via direct SQL updates (`kinds_json=''` and `kinds_json='[]'`) to verify repair behavior and idempotency for already-populated rows.

- 2026-02-23T11:28:38: Added kind chips with existing .tag-filter/.tag UI and wired selectedKind state into /api/v1/notes kind query filtering.
- 2026-02-23T11:28:38: Note list now shows kind badges from note.kinds with Korean labels (평문/유튜브/인스타/릴스/스레드/기타) without client-side kind inference.
- 2026-02-23T11:28:38: Playwright MCP interaction was blocked because Chrome is missing at /opt/google/chrome/chrome in this environment; fallback API verification showed filtered counts (all=86, plain_text=8, youtube=8, instagram_post=0, instagram_reel=0, threads=0, other_link=78).
2026-02-23: Updated plan checkboxes and added verification logs for TODOs 1-8 based on notepad evidence.

2026-02-23
- Refactored extra endpoints into `app/extra_routes.py` and avoided circular imports by introducing `app/app_state.py` for shared `config`, `store`, and `job_runner` singletons; `app/main.py` and `app/extra_routes.py` now both import from `app.app_state` instead of importing each other.

2026-02-23
- Scope fidelity deep check (`cb7bf7a..HEAD`) maps cleanly to four allowed buckets at commit granularity: kinds feature, social embeds, accepted extra endpoints, and deps/tooling refactors; no unacknowledged scope creep detected.
- Dependency delta in this range is limited to `python-multipart>=0.0.22` (+ lockfile), consistent with multipart upload support for URLs CSV import.
- Secret-pattern scan over all range-changed files returned no credential leaks; `.sisyphus/` remains untracked (`?? .sisyphus/`).
- 2026-02-23 F3 QA: `kind=youtube` filtering is pagination-aware; default page can miss newly imported youtube notes even when filter is correct, so QA should verify with larger `size` or direct note detail lookup.
- 2026-02-23 F3 QA: when Playwright launch fails due missing Chrome, fallback API checks (`/api/v1/notes?kind=...`, `/api/v1/note-kinds`, note detail endpoints) plus home markup probes provide sufficient verification coverage.
- 2026-02-23 F3 rerun: validated fallback fixture with KakaoTalk import rows for `youtube` and `instagram_post+threads`; confirmed `primaryKind=plain_text` remains while `kinds` carries contained-link union, and `note-kinds?q=watch` returns stable `{kind,count}` item shape.

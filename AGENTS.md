# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

note-nomi is a lightweight AI-powered note/bookmark web app (Korean UI). Python 3.13 + FastAPI backend with embedded SQLite, React 18 frontend served as a single static HTML file (CDN-loaded, no build step).

### Running the app

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Browser: `http://localhost:8000`

### Testing

```bash
uv run python -m unittest tests/test_service.py tests/test_api.py
```

Tests use in-memory/temp SQLite databases; no external services required.

### Linting

No project-level linter configured. Use `uv tool run ruff check .` for ad-hoc lint checks.

### Key caveats

- The `.env` file is already present (copied from `.env.example`). Default config uses `heuristic` LLM provider, which needs no API keys.
- The `data/` directory must exist for the SQLite database file. It is auto-created by the app on startup if missing.
- The `ResourceWarning: unclosed database` warnings in test output are cosmetic and do not indicate test failure.
- Frontend is a single `app/static/index.html` file with no build step. Changes are reflected on browser refresh.
- The `pyproject.toml` `tool.uv.dev-dependencies` deprecation warning is harmless.

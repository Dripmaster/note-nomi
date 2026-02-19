# Implementation starter (FastAPI)

## Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Scope
- API skeleton: `app/main.py`
- Analysis worker skeleton: `app/analysis_worker.py`

## Notes
- Current storage is in-memory for MVP scaffolding only.
- Replace in-memory stores with PostgreSQL + queue worker.
- Replace worker stubs with production fetch/extract/LLM adapters.

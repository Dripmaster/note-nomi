# Implementation starter (FastAPI + SQLite service layer)

## Run API
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Run tests (stdlib)
```bash
python -m unittest tests/test_service.py
```

## Scope
- API skeleton: `app/main.py`
- Analysis worker skeleton: `app/analysis_worker.py`
- Storage/service layer: `app/storage.py`, `app/service.py`

## Notes
- FastAPI route layer is in-memory scaffold for endpoint shape validation.
- `app/storage.py` provides SQLite persistence for incremental backend migration.
- Replace worker stubs with production fetch/extract/LLM adapters.

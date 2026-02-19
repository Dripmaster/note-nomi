# Implementation starter (FastAPI + SQLite service layer)

## Run API
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Run tests
```bash
python -m unittest tests/test_service.py
python -m unittest tests/test_api.py
```

## Delivered scope (1~7 완료)
1. FastAPI route ↔ SQLite service/store 연동
2. Ingestion job/item 상태 추적 + retry
3. 내용 분석 실패 코드(`fetch_failed`, `extract_failed`, `partial_done`) 반영
4. SQLite FTS 기반 검색 및 scope 필터
5. NotebookLM zip export + download endpoint
6. 카테고리/태그 집계 API
7. 서비스/API 테스트 확장

## Notes
- 현재 분석(fetch/extract/LLM)은 스텁 기반이므로 production adapter 교체가 필요합니다.
- Job 처리는 현재 요청 시 즉시 처리(synchronous)이며, 추후 큐 워커로 교체 예정입니다.

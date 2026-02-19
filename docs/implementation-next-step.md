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
- 현재 분석은 `heuristic` 또는 `internal_codex` provider를 사용할 수 있으며, 내부 Codex(`/chat/completions` 호환) 연동을 지원합니다.
- Job 처리는 API 요청에서 백그라운드 스레드로 분리되어 비동기로 진행됩니다. 운영 환경에서는 별도 워커/큐로 확장하는 것을 권장합니다.

- 노트 목록/검색 페이지네이션 + 정렬/기간/태그 필터가 반영되었습니다.
- 카테고리 ID 기반 수정 엔드포인트(`PATCH /categories/{id}`)를 제공합니다.

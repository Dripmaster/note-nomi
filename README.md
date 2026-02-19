# note-nomi

가벼운 AI 노트 웹 프로젝트 기획 + 구현 스타터 저장소입니다.

## 문서
- MVP 화면 와이어프레임 + DB 스키마 SQL + API 명세 초안: `docs/mvp-wireframe-schema-api.md`
- FastAPI/SQLite 구현 스타터 안내: `docs/implementation-next-step.md`

## 빠른 실행
```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## 환경변수
- `NOTE_NOMI_DB_PATH`: SQLite 파일 경로
- `NOTE_NOMI_HTTP_TIMEOUT_SEC`: 원문 수집 HTTP 타임아웃(초)
- `NOTE_NOMI_HTTP_MAX_BYTES`: 원문 수집 최대 바이트
- `NOTE_NOMI_DEFAULT_CATEGORY`: 카테고리 자동분류 실패 시 기본값
- `NOTE_NOMI_EXPORT_TTL_HOURS`: export 다운로드 URL 만료 시간
- `NOTE_NOMI_LLM_PROVIDER`: `heuristic` 또는 `internal_codex`
- `NOTE_NOMI_LLM_BASE_URL`: 내부 Codex 호환 API base URL
- `NOTE_NOMI_LLM_API_KEY`: 내부 Codex API 키
- `NOTE_NOMI_LLM_MODEL`: 모델명 (기본 `gpt-5.2-codex`)
- `NOTE_NOMI_LLM_TIMEOUT_SEC`: LLM API 호출 타임아웃

## 테스트
```bash
python -m unittest tests/test_service.py
python -m unittest tests/test_api.py
```


## 구현 상태 메모
- Ingestion은 백그라운드 처리(비동기)로 동작합니다.
- 검색 API는 `snippet` 필드를 포함합니다.
- 카테고리 생성/이름변경/병합 API를 제공합니다.
- Export는 `date_range` 대상 타입을 지원합니다.

- 노트/검색 API는 페이지네이션(`page`,`size`)과 정렬/필터를 지원합니다.

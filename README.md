# note-nomi

가벼운 AI 노트 웹 프로젝트 기획 + 구현 스타터 저장소입니다.

## 문서
- MVP 화면 와이어프레임 + DB 스키마 SQL + API 명세 초안: `docs/mvp-wireframe-schema-api.md`
- FastAPI/SQLite 구현 스타터 안내: `docs/implementation-next-step.md`

## 빠른 실행
```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

`uv`는 `.python-version`(3.13) 기준으로 실행됩니다.

(기존 방식) `pip install -r requirements.txt` 후 `uvicorn app.main:app --reload`로도 실행 가능합니다.

브라우저에서 `http://127.0.0.1:8000` 접속 시 React 기반 간단한 프론트엔드를 확인할 수 있습니다.

## 환경변수
- `NOTE_NOMI_DB_PATH`: SQLite 파일 경로
- `NOTE_NOMI_HTTP_TIMEOUT_SEC`: 원문 수집 HTTP 타임아웃(초)
- `NOTE_NOMI_HTTP_MAX_BYTES`: 원문 수집 최대 바이트
- `NOTE_NOMI_DEFAULT_CATEGORY`: 카테고리 자동분류 실패 시 기본값
- `NOTE_NOMI_EXPORT_TTL_HOURS`: export 다운로드 URL 만료 시간
- `NOTE_NOMI_LLM_PROVIDER`: `heuristic` 또는 `codex_cli`
- `NOTE_NOMI_CODEX_CLI_COMMAND`: 로컬 Codex CLI 실행 파일명(예: `codex`)
- `NOTE_NOMI_CODEX_CLI_ARGS`: Codex CLI 인자(예: `run --json`)
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
- 노트 전문보기: 목록에서 노트 클릭 시 `#/notes/{id}` 상세 페이지(메타데이터 + 요약/본문 탭)로 이동합니다.
- 인스타그램: 인스타 URL은 브라우저 User-Agent로 재시도하며, 응답 HTML에 `og:description`/`og:title`이 있으면 캡션으로 저장합니다. 수집 실패 시 안내 메시지를 표시합니다. **Playwright 브라우저 자동화**: `uv sync --extra instagram-browser` 후 `playwright install chromium`(또는 Chrome 프로필 사용 시 `playwright install` 불필요), `.env`에 `NOTE_NOMI_INSTAGRAM_BROWSER=playwright` 및 필요 시 `NOTE_NOMI_BROWSER_USER_DATA_DIR`(Chrome 프로필 경로) 설정 시 인스타 전용 브라우저 fetch 사용. 자세한 내용은 `docs/instagram-browser-automation.md` 참고.

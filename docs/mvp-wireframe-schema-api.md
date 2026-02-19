# Note Nomi MVP 기획 확장안

## 1) MVP 화면 와이어프레임 (페이지 구성)

> 목표: URL 리스트를 입력하면 자동 분석(본문 추출 + 요약 + 제목/태그/해시태그 + 카테고리화) 후, 검색/관리/NotebookLM 연동까지 가능한 최소 기능 제품.

---

### A. 공통 레이아웃

```
+--------------------------------------------------------------------------------+
| Logo | 전체 검색 (제목/요약/태그/본문)                      | 사용자 메뉴      |
+--------------------------------------------------------------------------------+
| 사이드바                                | 메인 콘텐츠 영역                 |
| - 대시보드                              |                                  |
| - 수집 Inbox                            |                                  |
| - 노트 목록                             |                                  |
| - 카테고리                              |                                  |
| - 태그/해시태그                         |                                  |
| - NotebookLM Export                     |                                  |
+--------------------------------------------------------------------------------+
```

- 상단 전역 검색바: 본문 포함 통합 검색
- 사이드바는 필터 역할 겸용 (카테고리/태그 빠른 이동)

---

### B. 페이지 1: 수집 Inbox (`/inbox`)

```
[페이지 타이틀] URL 수집 Inbox

[URL 입력 텍스트영역]
- 한 줄에 하나의 URL
- 붙여넣기 / CSV 업로드

[옵션]
( ) 자동 카테고리 추천 사용
( ) 요약 길이: 짧게 / 표준
( ) 본문 전체 저장 (기본 ON)

[분석 시작] 버튼

--------------------------------------------------
처리 큐 상태
- queued: 12
- processing: 3
- done: 25
- failed: 2

[테이블]
URL | 상태 | 추출 제목 | 에러 메시지 | 재시도
```

**핵심 UX 포인트**
- 긴 작업은 비동기로 처리하고 상태를 명확히 보여줌
- 실패 항목은 즉시 재시도 가능

---

### C. 페이지 2: 노트 목록 (`/notes`)

```
[필터 바]
카테고리 드롭다운 | 태그 멀티셀렉트 | 날짜 | 상태 | 정렬

[노트 카드/테이블 목록]
- AI 제목
- 원본 URL 도메인
- 요약 2~3줄
- 태그 + 해시태그
- 카테고리 배지
- 생성일
```

**목록 액션**
- 다중 선택 후: 카테고리 이동 / 태그 편집 / export
- 카드 클릭 시 상세 페이지 이동

---

### D. 페이지 3: 노트 상세 (`/notes/:id`)

```
좌측: 메타데이터 패널
- 원본 URL
- 수집 시간
- 카테고리 (수정 가능)
- 태그/해시태그 (수정 가능)

우측: 본문/요약 탭
[탭] 요약(짧게) | 요약(표준) | 본문 전체 | 원문 메모

- AI 제목 (수정 가능)
- 자동 생성 태그 (수정 가능)
- 본문 전체 저장 데이터 표시 (읽기/복사)
```

**핵심 UX 포인트**
- “본문 전체 저장”을 실제로 확인/활용 가능해야 함
- AI 결과는 전부 수동 수정 가능

---

### E. 페이지 4: 카테고리 관리 (`/categories`)

```
카테고리 목록
- 이름 / 색상 / 노트 수 / 최근 업데이트

[추가] [수정] [병합]
```

**권장 기능(초기 포함 가능)**
- 카테고리 병합: 유사 카테고리 정리

---

### F. 페이지 5: 검색 결과 (`/search?q=`)

```
검색어: "LLM agent"

결과 탭:
- 전체
- 제목/요약 일치
- 태그/해시태그 일치
- 본문 전체 일치

[결과 리스트]
- 하이라이트(본문 문맥 2~3줄)
```

**MVP 검색 전략**
- 1차: 텍스트 검색(제목/요약/태그/본문)
- 2차: 의미 검색(벡터)

---

### G. 페이지 6: NotebookLM Export (`/export`)

```
[대상 선택]
( ) 선택 노트
( ) 카테고리 단위
( ) 기간 단위

[포맷]
- Markdown (.md 묶음 zip)
- Text bundle (.txt 묶음 zip)

[포함 옵션]
[x] AI 제목
[x] 요약(짧게/표준)
[x] 태그/해시태그
[x] 본문 전체
[x] 원본 URL

[Export 생성]
```

---

## 2) DB 스키마 SQL 초안 (본문 전체 저장 포함)

> PostgreSQL 기준. MVP에서 바로 사용할 수 있는 형태.

```sql
-- 1) 카테고리
CREATE TABLE categories (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  color VARCHAR(20),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2) 노트
CREATE TABLE notes (
  id BIGSERIAL PRIMARY KEY,

  -- 원본 정보
  source_url TEXT NOT NULL,
  source_domain VARCHAR(255),
  fetched_title TEXT,

  -- 본문 저장 (요구사항 반영: 본문 전체 저장)
  content_full TEXT NOT NULL,
  content_excerpt TEXT,

  -- AI 생성물
  ai_title TEXT,
  summary_short TEXT,
  summary_long TEXT,

  -- 분류
  category_id BIGINT REFERENCES categories(id) ON DELETE SET NULL,

  -- 상태 관리
  status VARCHAR(20) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
  error_message TEXT,

  -- 메타
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  analyzed_at TIMESTAMPTZ
);

CREATE INDEX idx_notes_status ON notes(status);
CREATE INDEX idx_notes_category_id ON notes(category_id);
CREATE INDEX idx_notes_created_at ON notes(created_at DESC);

-- 3) 태그
CREATE TABLE tags (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  type VARCHAR(20) NOT NULL DEFAULT 'tag'
    CHECK (type IN ('tag', 'hashtag')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(name, type)
);

-- 4) 노트-태그 N:M
CREATE TABLE note_tags (
  note_id BIGINT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  tag_id BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (note_id, tag_id)
);

CREATE INDEX idx_note_tags_tag_id ON note_tags(tag_id);

-- 5) 원본 수집 요청(배치)
CREATE TABLE ingestion_jobs (
  id BIGSERIAL PRIMARY KEY,
  requested_count INT NOT NULL DEFAULT 0,
  queued_count INT NOT NULL DEFAULT 0,
  processing_count INT NOT NULL DEFAULT 0,
  done_count INT NOT NULL DEFAULT 0,
  failed_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6) 작업-노트 연결
CREATE TABLE ingestion_job_items (
  id BIGSERIAL PRIMARY KEY,
  job_id BIGINT NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
  note_id BIGINT REFERENCES notes(id) ON DELETE SET NULL,
  source_url TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ingestion_job_items_job_id ON ingestion_job_items(job_id);
CREATE INDEX idx_ingestion_job_items_status ON ingestion_job_items(status);
```

### 검색(본문 포함) 인덱스 제안

```sql
-- 단순 통합 검색용 tsvector 컬럼 (MVP)
ALTER TABLE notes
ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('simple', coalesce(ai_title, '')), 'A') ||
  setweight(to_tsvector('simple', coalesce(summary_short, '')), 'B') ||
  setweight(to_tsvector('simple', coalesce(summary_long, '')), 'B') ||
  setweight(to_tsvector('simple', coalesce(content_full, '')), 'C')
) STORED;

CREATE INDEX idx_notes_search_tsv ON notes USING GIN (search_tsv);
```

---

## 3) API 명세 초안 (MVP)

기본 prefix: `/api/v1`

### 3-1. 수집/분석

#### `POST /ingestions`
- URL 리스트 배치 등록
- 요청:

```json
{
  "urls": [
    "https://example.com/a",
    "https://example.com/b"
  ],
  "options": {
    "summaryLength": "standard",
    "autoCategory": true,
    "storeFullContent": true
  }
}
```

- 응답:

```json
{
  "jobId": 101,
  "requestedCount": 2,
  "status": "queued"
}
```

#### `GET /ingestions/{jobId}`
- 배치 진행 상태 조회
- 응답:

```json
{
  "jobId": 101,
  "counts": {
    "queued": 0,
    "processing": 1,
    "done": 1,
    "failed": 0
  },
  "items": [
    {
      "sourceUrl": "https://example.com/a",
      "status": "done",
      "noteId": 5001
    }
  ]
}
```

#### `POST /ingestions/{jobId}/retry`
- 실패 항목 재시도

---

### 3-2. 노트

#### `GET /notes`
- 목록 조회 + 필터
- 쿼리 파라미터:
  - `categoryId`, `tag`, `q`, `status`, `from`, `to`, `page`, `size`, `sort`

#### `GET /notes/{id}`
- 노트 상세 조회 (본문 전체 포함)
- 응답 예시:

```json
{
  "id": 5001,
  "sourceUrl": "https://example.com/a",
  "fetchedTitle": "Original Title",
  "aiTitle": "AI가 생성한 제목",
  "summaryShort": "짧은 요약...",
  "summaryLong": "표준 요약...",
  "contentFull": "...본문 전체...",
  "tags": [
    { "name": "LLM", "type": "tag" },
    { "name": "#agent", "type": "hashtag" }
  ],
  "category": { "id": 1, "name": "AI" },
  "status": "done"
}
```

#### `PATCH /notes/{id}`
- 수동 수정
- 수정 가능 필드:
  - `aiTitle`, `summaryShort`, `summaryLong`, `contentFull`, `categoryId`, `tags`

#### `DELETE /notes/{id}`
- 노트 삭제

---

### 3-3. 카테고리/태그

#### `GET /categories`
#### `POST /categories`
#### `PATCH /categories/{id}`
#### `POST /categories/merge`

#### `GET /tags`
- 자주 쓰는 태그/해시태그 목록 조회

---

### 3-4. 검색

#### `GET /search`
- 쿼리 파라미터:
  - `q` (필수)
  - `scope` = `all | title_summary | tags | full_content`
  - `page`, `size`

- 동작:
  - MVP: Postgres full-text (`search_tsv`) + 태그 조인 검색

---

### 3-5. NotebookLM Export

#### `POST /exports/notebooklm`
- 요청:

```json
{
  "target": {
    "type": "category",
    "categoryId": 1
  },
  "format": "markdown_zip",
  "include": {
    "aiTitle": true,
    "summaryShort": true,
    "summaryLong": true,
    "tags": true,
    "contentFull": true,
    "sourceUrl": true
  }
}
```

- 응답:

```json
{
  "exportId": "exp_20250101_001",
  "downloadUrl": "/api/v1/exports/exp_20250101_001/download",
  "expiresAt": "2025-01-01T12:00:00Z"
}
```

---

## 4) 개발 우선순위 (실행 순서)

1. `POST /ingestions` + 배치 상태 조회
2. `GET /notes`, `GET /notes/{id}` + 본문 전체 저장/조회
3. `PATCH /notes/{id}` (수정 UX 확보)
4. 통합 검색(`q`) + 카테고리/태그 필터
5. NotebookLM export

---

## 5) 요구사항 반영 체크리스트

- [x] URL 리스트 입력 후 자동 분석
- [x] 요약/제목/태깅/해시태깅
- [x] 카테고리별 관리
- [x] 검색 기능
- [x] NotebookLM 연동용 export
- [x] **본문 전체 저장** (DB/조회/API/Export 전부 반영)

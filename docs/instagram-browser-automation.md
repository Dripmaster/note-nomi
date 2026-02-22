# 인스타그램 수집: 브라우저 자동화 연동

## 요약

**로그인된 브라우저가 있으면 브라우저 자동화로 인스타 글 수집이 가능하다.**  
일반 HTTP GET으로는 인스타가 차단하거나 빈 껍데기 HTML만 주지만, 실제 브라우저(Chrome 등)를 띄워서 해당 URL로 이동한 뒤 DOM에서 캡션을 읽으면 된다. 이때 **이미 로그인된 프로필(또는 저장된 쿠키)**을 쓰면 비공개/로그인 필요 콘텐츠까지 접근할 수 있다.

## 동작 방식

1. **브라우저 컨텍스트**
   - **옵션 A**: 사용자가 평소 쓰는 Chrome 프로필 경로를 지정 → 그 프로필로 Playwright가 브라우저를 띄움 → 이미 로그인된 인스타 세션 사용.
   - **옵션 B**: 별도 프로필에 한 번 로그인해 두고, 그 프로필만 수집 전용으로 사용.

2. **자동화 흐름**
   - 인스타 URL이 들어오면 일반 fetch 대신 **Playwright**로 해당 URL 이동.
   - 페이지 로드 대기(네트워크 유휴 또는 캡션 영역 선택자 등장).
   - DOM에서 캡션 텍스트 선택자로 추출(예: `article` 내 캡션, 또는 인스타가 쓰는 data 속성).
   - 추출한 텍스트를 기존 파이프라인(`analyze_with_llm` 등)에 넘겨 노트로 저장.

3. **도구 선택**
   - **Playwright (Python)**  
     - `playwright` 패키지 + `playwright install chromium` (또는 기존 Chrome 연결).  
     - Python 서버와 같은 프로세스/머신에서 실행하기 좋고, 프로필 경로 지정이 쉬움.
   - Puppeteer/Chrome DevTools Protocol은 주로 Node 환경에서 사용.

## 연동 시 고려사항

| 항목 | 설명 |
|------|------|
| 의존성 | `playwright` 선택 의존(optional). 인스타 전용이면 인스타 URL일 때만 Playwright 경로 사용. |
| 리소스 | 브라우저 프로세스 메모리/CPU 사용. 동시 수집 개수 제한(예: 1~2개) 권장. |
| 프로필/쿠키 | 로그인 세션 유지용 프로필 경로 또는 쿠키 파일을 설정에서 지정. |
| 선택자 | 인스타 DOM 구조 변경 시 캡션 선택자 수정 필요. (공식 API가 아니므로 유지보수 포인트.) |
| 헤드리스 | 서버에서는 `headless=True`로 실행. 디버깅 시에만 `headless=False`로 화면 보기. |

## 구현 상태 (Playwright 경로)

- `app/analysis_worker.py`의 `fetch_html` (또는 인스타 전용 `fetch_instagram_via_browser`)에서:
  - `NOTE_NOMI_INSTAGRAM_BROWSER=playwright` 같은 설정이 있고
  - URL이 인스타일 때만
  - Playwright로 Chromium/Chrome 실행 → `context = browser.new_context(storage_state="path/to/profile.json")` 또는 `user_data_dir` 지정 → `page.goto(url)` → `page.wait_for_selector("article")` → `page.inner_text("...")` 로 캡션 추출 → HTML이 아닌 **이미 추출한 텍스트**를 반환.
- 기존 `process_url`은 “HTML 문자열”을 기대하므로, 인스타 브라우저 경로에서는 “가짜 HTML” 하나만 만들어서 본문만 넣어 주면 된다. 예: `content = extract_main_content(html)` 대신 인스타면 `content = fetched_caption_text` 로 치환.

정리하면, **로그인된 브라우저(또는 그 세션)가 있으면 브라우저 자동화 툴로 인스타 수집 가능하다.**  
**구현 완료.** 사용 방법: `uv sync --extra instagram-browser`, `playwright install chromium`, `.env`에 `NOTE_NOMI_INSTAGRAM_BROWSER=playwright` 설정.

### 로그인 방식 (둘 중 하나)

- **아이디/비밀번호**: `NOTE_NOMI_INSTAGRAM_USERNAME`, `NOTE_NOMI_INSTAGRAM_PASSWORD` 설정 시 로그인 페이지에서 자동 입력 후 세션을 `data/instagram_session.json`(또는 DB와 같은 디렉터리)에 저장해 재사용. 프로필 경로 없이 동작. 2FA/체크포인트 시에는 세션 저장이 안 될 수 있음.
- **Chrome 프로필**: `NOTE_NOMI_BROWSER_USER_DATA_DIR`에 Chrome 사용자 데이터 폴더 경로 지정 시 해당 프로필의 로그인 세션 사용. 아이디/비밀번호가 있으면 credentials 우선.

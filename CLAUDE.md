# 미즈메디병원 업무 메일 자동화

## 대화 지침

- 사용자에게는 **항상 존댓말**로 대화한다. (모든 세션에서 유지)
- 사용자를 부를 때는 **"Tai님"** 이라고 한다. ("사장님" 등 다른 호칭 금지)

## 프로젝트 목표

매일 아침 자동으로 실행되어, 새로 수신된 업무 메일을 읽어서 다음을 수행하는
파이프라인을 만든다.

1. 메일을 **업무 / 광고성 / 스팸**으로 분류
2. 하루치 **요약 리포트** 생성
3. 회신이 필요한 메일은 **회신 초안** 작성
4. **카카오톡으로 짧은 알림** 발송 (요약 + 처리할 일 안내)

## 절대 원칙 (타협 불가)

1. **메일을 자동 발송하지 않는다.** 이 자동화는 회신 *초안*만 만든다 (Gmail
   임시보관함 + 리포트 문서). 최종 확인과 실제 전송은 반드시 사람이 Gmail 에서
   직접 한다. **`gmail.send` 스코프는 요청하지 않고, send 를 호출하는 코드도
   만들지 않는다.** 현재 스코프: `gmail.readonly`(읽기) + `gmail.compose`(초안).
   ⚠️ `gmail.compose` 는 기술적으로는 발송도 가능한 넓은 권한이다 — 아래
   "보안 참고: 권한 범위 확장" 참고.
2. **비밀번호·API 키를 코드에 하드코딩하지 않는다.** 모든 비밀값은 `.env`
   파일 또는 `credentials/` 폴더의 파일에서 읽는다. `.env`와 `credentials/`는
   git에 올리지 않는다.
3. **인증 파일은 전부 `credentials/` 안에 둔다.** 이 폴더는 `.gitignore`로
   통째로 제외되어 있다.

## `credentials/` 폴더

- 용도: Gmail OAuth 관련 파일 전용 보관소.
  - `client_secret_*.json` — Google Cloud Console에서 발급받은 OAuth
    클라이언트(데스크톱 앱) 정보. **직접 커밋 금지.** 코드는 이 파일에서
    client_id / client_secret을 읽는다 (`.env`에 넣지 않는다).
  - `token.json` — 최초 로그인 후 자동 생성되는 사용자 토큰(액세스/리프레시).
    자동 생성물이며 커밋 금지. **스코프가 확장되면(예: compose 추가) 이 파일은
    무효가 되어 재인증이 필요하다.** 코드가 자동 감지해서 브라우저 로그인을
    다시 띄운다.
  - `kakao_token.json` — 카카오 토큰 캐시. 자동 생성물, 커밋 금지.
- 이 폴더 전체가 `.gitignore`에 등록되어 있다. 어떤 파일도 git에 올리지 않는다.
- 새 PC에서 셋업할 때는 이 폴더 내용을 안전한 경로(암호화 저장소 등)로 직접
  옮긴다. 저장소에는 절대 포함하지 않는다.

## 보안 참고: 권한 범위 확장 (2026-09-02)

회신 초안을 Gmail 임시보관함에 실제로 만들기 위해 OAuth 스코프에
`https://www.googleapis.com/auth/gmail.compose` 를 추가했다.

- **넓어진 권한**: `gmail.compose` 는 초안 생성/조회/수정/삭제뿐 아니라
  **메일 발송 권한까지 포함**한다. 즉 이 토큰이 유출되면 이론상 이 계정으로
  메일을 보낼 수 있다. (이전 `gmail.readonly` 는 읽기만 가능했다.)
- **완화 장치**:
  - 코드에는 발송(`messages.send`, `drafts.send`) 을 호출하는 함수가 **하나도
    없다.** `src/gmail_draft.py` 에 초안 생성만 있다. 앞으로도 추가하지 않는다.
  - 초안은 `GMAIL_DRAFT_ACCOUNT`(기본 `tai.roh@mizmedi.com`) 로 로그인한
    경우에만 생성된다. 로그인 계정이 다르면 거부한다(엉뚱한 메일함 방지).
  - 토큰은 여전히 `credentials/token.json` 한 곳에만 있고 git 제외다.
- **취소 방법**: 권한을 되돌리려면 <https://myaccount.google.com/permissions>
  에서 이 앱 접근을 삭제하고, `credentials/token.json` 을 지운 뒤, 필요하면
  `src/gmail_auth.py` 의 `SCOPES` 에서 `gmail.compose` 를 빼고 재인증한다.

## 도메인 별칭 구조 (혼동 방지용 기록)

`mizmedi.com` 과 `dearone.co.kr.test-google-a.com` 은 **같은 Google Workspace
계정의 도메인 별칭**이다 — 메일함은 물리적으로 1개. `test-google-a.com` 은
Gmail 도메인 목록에 추가 등록한 순수 수신용 주소로, 아마란스10 자동전달이
그 주소로 온다. **로그인·Admin Console 관리·OAuth 인증은 항상
`tai.roh@mizmedi.com` 하나로 통일.** 코드에서 계정을 다루는 모든 곳(재인증
안내, `GMAIL_DRAFT_ACCOUNT` 검증 등)은 이 정본 주소 기준이다.

## 환경변수 (`.env`)

`.env.example`을 복사해서 `.env`를 만들고 값을 채운다.

| 키 | 설명 |
|---|---|
| `TARGET_GMAIL_ADDRESS` | 받은편지함을 조회할 대상 Gmail 주소 (리포트 머리말 표시용, `tai.roh@mizmedi.com`) |
| `GMAIL_DRAFT_ACCOUNT` | 회신 초안을 만들 계정 (기본 `tai.roh@mizmedi.com`). 재인증 시 이 계정으로 로그인해야 함. **인증된 계정 정보(`getProfile`) 기준으로 비교** — 메일 헤더(To/Delivered-To 등)는 보지 않으므로 도메인 별칭과 무관하게 안전함 |
| `GMAIL_QUERY` | 조회 쿼리 (기본 `in:inbox`) |
| `KAKAO_REST_API_KEY` | 카카오 REST API 키 |
| `KAKAO_CLIENT_SECRET` | 콘솔에서 Client Secret 활성화 시 필수 (KOE010 방지) |
| `KAKAO_REDIRECT_URI` | 카카오 로그인 Redirect URI (이후 단계) |
| `KAKAO_REFRESH_TOKEN` | 카카오 리프레시 토큰 (이후 단계) |
| `KAKAO_TARGET` | 알림 대상 (이후 단계) |
| `ANTHROPIC_API_KEY` | 메일 분류용 Claude API 키 (아래 "분류 로직" 참고) |
| `CLASSIFIER_MODEL` | 분류에 쓸 모델 (선택, 기본 `claude-sonnet-4-6`) |
| `REPORT_DIR` | 요약 리포트 저장 폴더 (기본 `reports`) |
| `LOG_LEVEL` | 로그 레벨 (기본 `INFO`) |

Gmail 클라이언트 ID / 보안비밀번호는 `.env`에 넣지 않는다 — `credentials/`
안의 JSON에서 직접 읽는다.

## 폴더 구조

```
mizmedi-mail-automation/
├── CLAUDE.md              # 이 문서
├── .env.example           # 환경변수 템플릿
├── .env                   # 실제 환경변수 (git 제외)
├── .gitignore
├── requirements.txt
├── credentials/           # 인증 파일 전용 (git 제외 전체)
│   ├── client_secret_*.json
│   ├── token.json         # Gmail 토큰, 최초 로그인 후 자동 생성
│   └── kakao_token.json   # 카카오 access/refresh 토큰 캐시, 자동 생성
├── src/
│   ├── config.py          # .env + credentials 경로 로딩
│   ├── gmail_auth.py      # Gmail OAuth 인증 (readonly + compose) / 서비스 객체
│   ├── mail_fetcher.py    # 새 메일 가져오기 + 본문 조회 + 처리 기록
│   ├── gmail_draft.py     # 회신 초안을 Gmail 임시보관함에 생성 (발송 없음)
│   ├── classifier.py      # 규칙 + LLM 분류
│   ├── reply_drafter.py   # 회신 필요 판단 + 초안 텍스트 + 임시보관함 초안 생성
│   ├── report.py          # 마크다운 요약 리포트 + 요약 JSON 생성/저장
│   ├── kakao_notify.py    # 카카오 "나에게 보내기" + 토큰 갱신
│   └── run_state.py       # "오늘 성공했는지" 표식 (data/last_success.json)
├── scripts/
│   ├── run_daily.py          # ★ 메인 파이프라인 (스케줄러가 실행할 대상)
│   ├── test_gmail_auth.py    # Gmail 인증 확인용 (받은편지함 개수 출력)
│   ├── test_classify.py      # 새 메일 가져와 분류 결과 표 출력
│   ├── run_pipeline.py       # 개발용: 가져오기→분류→리포트 (카카오·기록 없음)
│   ├── kakao_auth.py         # 카카오 로그인 최초 1회 인증 (토큰 발급)
│   └── test_kakao_notify.py  # 리포트 요약을 카카오톡으로 전송 테스트
├── launchd/
│   └── com.mizmedi.mail-automation.plist  # 07~22시 매 정시 실행 스케줄 정의
├── reports/               # 생성된 요약 리포트 (git 제외)
│   ├── YYYY-MM-DD-mail-report.md
│   └── YYYY-MM-DD-mail-report.summary.json  # 알림용 요약 수치
├── logs/                  # 스케줄 실행 로그 (git 제외)
│   ├── YYYY-MM-DD.log         # run_daily 출력 (날짜별)
│   └── launchd.err.log        # 쉘/launchd 레벨 오류
└── data/                  # 처리 산출물 (git 제외)
    ├── processed_ids.json # 처리 완료한 메일 ID 목록
    └── last_success.json  # 그날 파이프라인 성공 표식 (정시 중복 실행 방지)
```

## 분류 로직 (`src/classifier.py`)

메일 한 통을 **업무 / 광고성 / 스팸 / 기타** 중 하나로 분류한다. 규칙 → LLM
2단계로 분류하고, "업무" 메일에는 핵심 요약을 추가로 붙인다.

### 1단계 — 규칙 기반 필터 (`classify_by_rules`)

빠르고 비용이 없으며, **명확히 광고성일 때만** 확정한다.

- **키워드**: 제목·스니펫에 `광고`, `(광고)`, `수신거부`, `unsubscribe`,
  `뉴스레터`, `newsletter`, `프로모션`, `특가` 등이 있으면 → `광고성`
- **발신자 패턴**: `newsletter@`, `noreply@`, `mailer@`, `marketing@`,
  `@mail.`, `@news.` 등 광고성 발송 패턴이면 → `광고성`
- 목록은 `AD_KEYWORDS`, `AD_SENDER_PATTERNS` 상수에서 관리한다.

규칙에 걸리지 않으면 2단계로 넘어간다.

### 2단계 — LLM 분류 (`classify_by_llm`)

- Anthropic API를 호출한다. 모델은 `CLASSIFIER_MODEL`(기본 `claude-sonnet-4-6`).
- 시스템 프롬프트로 4개 분류 기준을 주고, 발신자·제목·수신시각·본문 요약을
  전달한다.
- 응답은 `{"category": ..., "reason": ...}` JSON 한 줄로 받아 파싱한다.
  (파싱 실패·API 오류 시 `기타` + 오류 사유로 처리하고 파이프라인은 계속 진행)
- 결과에는 분류 **이유 한 줄**이 함께 담긴다.

### 3단계 — 업무 메일 핵심 요약 (`summarize_work_mail`)

- **"업무" 로 분류된 메일에 대해서만** Claude API를 한 번 더 호출한다.
- 분류 이유(`reason`)와는 **별개**로, "이 메일이 무슨 내용인지" 자체를
  한국어 1~2문장(50자 안팎)으로 요약한다. 발신자 이름·소속은 빼고 핵심
  용건 위주.
- 결과는 `Classification.summary` 에 담긴다. 카카오 알림에서 사용한다.
  (리포트 `.md` 형식은 바꾸지 않음 — 요약은 알림 전용)
- 실패하거나 `ANTHROPIC_API_KEY` 가 없으면 `summary = None` (에러 아님).

### `ANTHROPIC_API_KEY` 가 필요한 이유

규칙만으로는 "거래처가 보낸 실제 업무 메일"과 "회사가 보낸 홍보 메일"처럼
문맥으로만 구분되는 경우를 판별할 수 없다. 애매한 메일을 사람 대신 읽고
판단하기 위해 Claude API를 쓰며, 그 호출에 API 키가 필요하다. 키가 없으면
2단계는 건너뛰고 해당 메일은 `기타`로 남는다(에러 아님).

### 처리 기록

`fetch_new_messages()` 는 `data/processed_ids.json` 에 기록된 ID를 제외하고
가져온다. 후속 처리가 끝난 뒤 호출자가 `mark_processed()` 로 명시적으로 기록해야
한다 (가져오기 단계에서 자동 기록하지 않음 — 중간에 실패해도 메일을 잃지 않도록).

## 요약 리포트 (`src/report.py`)

분류 결과를 마크다운 리포트로 만든다.

- **저장 위치**: `REPORT_DIR/<YYYY-MM-DD>-mail-report.md` (예:
  `reports/2026-09-01-mail-report.md`). 같은 날 다시 실행하면 덮어쓴다.
- **구성**
  1. 머리말 — 생성 시각, 대상 계정, 가져온 새 메일 수
  2. **전체 통계** 표 — 업무/광고성/스팸/기타 건수 + 합계
  3. **카테고리별 목록** — 각 메일의 발신자 / 제목 / 수신 시각 / 분류 이유
     (+ 방식: rule / llm). 업무 메일에는 "회신 필요/불필요 + 이유" 도 표시.
  4. **회신 초안 섹션** — 회신이 필요한 업무 메일의 초안만 모아서 표시.
- 리포트는 `reports/` 폴더에만 저장된다. `reports/` 는 git 에서 제외된다.

### 요약 JSON (`summarize()` → `<날짜>-mail-report.summary.json`)

카카오 알림 등이 읽는 기계용 요약. 다음을 담는다.

- `date`, `total`, `counts`(카테고리별 건수)
- `reply_drafts`(초안 텍스트 건수), `drafts_created`(임시보관함 생성 성공),
  `drafts_failed`(생성 실패)
- `work_mails` — **업무 메일 목록**, 우선순위 정렬:
  ① 회신 필요 메일 먼저 ② 그다음 최근 수신 먼저.
  각 항목: `sender`, `subject`, `summary`(3단계 핵심 요약, 없으면 `null`),
  `needs_reply`, `received_at`.

## 회신 필요 판단 & 초안 (`src/reply_drafter.py`)

**"업무"로 분류된 메일에 대해서만** 실행한다. Claude API를 한 번 호출해
세 가지를 함께 받는다.

- `needs_reply` (true/false) — 수신자가 이 메일에 회신해야 하는가
- `reason` — 그렇게 판단한 이유 한 줄
- `draft` — `needs_reply=true` 일 때만, 정중한 업무용 한국어 회신 초안

**회신 필요 판단 기준** (시스템 프롬프트에 명시)

- 회신 필요: 질문·문의, 확인/승인 요청, 일정 조율, 자료 요청, 답변을 기다리는 제안
- 회신 불필요: 단순 공지·안내, 자동 발송 알림, 참고용 공유, 이미 종결된 대화

**초안 작성 규칙**

- 정중하고 간결한 업무용 한국어.
- 구체 정보(날짜·담당자·금액 등)를 모르면 `[일정]`, `[담당자]` 같은 대괄호
  자리표시자를 남기고, 서명은 `[보내는 사람]`.
- 본문은 `mail_fetcher.fetch_body()` 로 해당 메일만 개별 조회해서 전달한다
  (스니펫보다 정확한 초안을 위해). 조회 실패 시 스니펫으로 진행.

**Gmail 임시보관함 초안 생성 (`src/gmail_draft.py`)**

- `assess_reply(mail, service, make_gmail_draft=True)` 이고 초안 텍스트가 있으면
  `create_reply_draft()` 로 임시보관함에 **실제 초안 메일**을 만든다.
  - 받는사람: 원본 메일의 발신자(`From`)
  - 제목: `Re: 원본제목` (이미 `Re:` 로 시작하면 그대로)
  - 스레드: 원본 `Message-ID` → `In-Reply-To`/`References`, 원본 `threadId` 로
    같은 대화에 묶음
  - `drafts.create` 만 호출한다. **`drafts.send` / `messages.send` 는 없다.**
- 로그인 계정이 `GMAIL_DRAFT_ACCOUNT` 와 다르면 `GmailDraftError` 로 거부
  (프로세스당 1회 확인). → 엉뚱한 메일함에 초안이 쌓이는 것을 방지.
- 초안 생성 성공/실패는 `ReplyAssessment.draft_created` / `draft_id` /
  `draft_error` 에 담기고, 로그·리포트·카카오 문구에 모두 반영된다.
- 초안 생성이 실패해도 파이프라인은 계속된다 (리포트에 텍스트는 남음).
- `make_gmail_draft` 기본값은 `False`. `run_daily` 만 `True`(단, `--no-mark`
  테스트 모드에서는 `False`). `run_pipeline` / `test_kakao_notify` 는 `False`.

**보안 원칙 (절대 원칙과 연결)**

- 초안은 **Gmail 임시보관함 + 리포트 문서** 두 곳에만 존재한다 (이중 기록).
  **발송은 절대 하지 않는다.** 최종 확인·전송은 사람이 Gmail 에서 직접.
- 리포트의 회신 초안 섹션 상단에 "발송되지 않음, 사람이 Gmail 에서 최종 확인"
  경고를 항상 포함한다. 각 초안에는 임시보관함 생성 성공/실패도 표시한다.
- `ANTHROPIC_API_KEY` 가 없으면 회신 판단/초안 단계는 건너뛴다(에러 아님).

## 카카오톡 알림 (`src/kakao_notify.py`)

리포트의 **핵심 수치만** 짧게 내 카카오톡으로 보낸다. (메일 발송과 무관한,
사람에게 주는 알림)

### 사전 준비 (카카오 개발자 콘솔, 최초 1회)

- 내 애플리케이션 > **카카오 로그인 활성화** ON
- **Redirect URI** 에 `.env` 의 `KAKAO_REDIRECT_URI` 와 **똑같은 값** 등록
  (현재 `http://localhost:8888/callback`)
- 카카오 로그인 > 동의항목 > **카카오톡 메시지 전송(`talk_message`)** 사용 설정

### 인증 흐름 (`scripts/kakao_auth.py`, 최초 1회)

1. `KAKAO_REST_API_KEY` + `KAKAO_REDIRECT_URI` + `scope=talk_message` 로
   인증 URL을 만들어 브라우저를 연다.
2. 로컬 HTTP 서버(`KAKAO_REDIRECT_URI` 의 host:port)가 리디렉션으로 돌아온
   `authorization code` 를 받는다.
3. `code` 를 `https://kauth.kakao.com/oauth/token` 에 보내 **access token /
   refresh token** 을 발급받는다. (콘솔에서 Client Secret 을 켰다면
   `KAKAO_CLIENT_SECRET` 을 토큰 발급·갱신 요청에 함께 보낸다 — 없으면 KOE010)
4. 토큰을 `credentials/kakao_token.json` 에 캐시한다.
5. refresh token 을 화면에 출력한다. **사람이 직접** `.env` 의
   `KAKAO_REFRESH_TOKEN` 자리에 붙여넣는다. (스크립트는 `.env` 를 덮어쓰지 않음)

### 토큰 갱신 방식 (`get_access_token`)

- `credentials/kakao_token.json` 에 `access_token` 과 만료시각을 저장.
- access token 이 유효하면 그대로 사용.
- 만료됐으면(또는 전송 시 401) refresh token 으로
  `grant_type=refresh_token` 갱신 → 새 access token 을 캐시에 저장.
- refresh token 우선순위: `kakao_token.json` → 없으면 `.env` 의
  `KAKAO_REFRESH_TOKEN` (부트스트랩).
- 카카오는 refresh token 만료가 임박했을 때만 **새 refresh token** 을 함께
  준다. 그 경우 캐시에 저장하고, `.env` 값과 다르면
  "`.env` 를 직접 교체하라"는 안내를 출력한다 (자동으로 덮어쓰지 않음).
- refresh 까지 실패하면 `scripts/kakao_auth.py` 재실행 안내.

### 메시지 내용 (`format_summary_message`)

`reports/<날짜>-mail-report.summary.json` 을 읽어 만든다. 텍스트 템플릿
(`object_type: text`)으로 `talk/memo/default/send` 호출.

**구성**

```
📮 미즈메디 메일 리포트 (2026-09-02)
새 메일 9건 · 업무 3 / 광고성 4 / 스팸 0 / 기타 2
회신 초안 2건 → 임시보관함 저장 완료

[업무]
· 이서연 - 9월 15일 회의 일정 조율 요청
· 김종암 - 모니터 구매 현황 회신 요청
…외 1건은 리포트 참고
```

- 3번째 줄(회신 초안)은 상태에 따라 달라진다 (`_draft_line`):
  - `회신 초안 0건`
  - `회신 초안 N건 → 임시보관함 저장 완료`
  - `회신 초안 N건 → 저장 X / 실패 Y ⚠️`
  - `회신 초안 N건 → 임시보관함 저장 실패 Y건 ⚠️`
- 머리말 3줄(날짜 · 건수 요약 · 회신 초안 상태) 다음에 `[업무]` 블록.
- `[업무]` 블록은 `work_mails`(우선순위 정렬됨)를 `· 발신자 - 요약` 형태로 나열.
  - 발신자는 표시이름만 추출(`_short_sender`), 요약이 없으면 제목으로 대체.
  - 한 줄 최대 `WORK_LINE_MAX`(58자), 넘으면 `…` 로 자름.

**글자수 처리 (카카오 text 템플릿 200자 제한)**

- 상수: `KAKAO_TEXT_LIMIT=200`, `MAX_WORK_LINES=3`.
- 업무 줄을 하나씩 추가하되, **"이 줄 + 남은 건수용 `…외 N건은 리포트 참고`
  꼬리말" 까지 넣어도 200자 이내인지** 매번 검사한다. 초과하면 그 줄부터
  중단하고 꼬리말로 대체.
- 최대 3줄까지만 시도하고, 못 담은 나머지는 `…외 N건은 리포트 참고` 로 표시.
- 마지막에 한 번 더 `KAKAO_TEXT_LIMIT` 로 하드 컷(`…`). `send_to_me()` 에도
  200자 컷이 있어 이중 안전장치.
- 따라서 업무 메일이 아무리 많아도 **글자수 초과로 전송 실패하는 일은 없다.**

### 테스트 (`scripts/test_kakao_notify.py`)

- 오늘 요약 JSON 이 있으면 그걸 읽어 전송. 없으면 `--run-pipeline` 으로 즉석 생성.
- `--dry-run` 은 전송 없이 메시지만 출력.

## 전체 파이프라인 (`scripts/run_daily.py`)

스케줄러가 **오전 7시~밤 10시 매 정시**에 실행하는 메인 스크립트.
각 단계의 진행 상황·실패 지점을 `logging` 으로 출력한다.

**하루 1회 성공 모델** — 스케줄러가 매시간 부르지만, 실제로 일하는 건
그날 첫 성공까지의 실행뿐이다.

- **0단계 (성공 표식 확인)**: `run_state.succeeded_today()` — `data/last_success.json`
  의 `date` 가 오늘이면 **아무것도 안 하고 즉시 종료(exit 0)**.
- 파이프라인이 끝까지 성공하면 `run_state.mark_success_today()` 로 표식을 남긴다.
  그 뒤 정시 실행들은 전부 0단계에서 빠진다.
- 따라서 카카오 리포트 알림은 **하루 1건**만 온다.

| 단계 | 하는 일 | 연결되는 파일 / 함수 |
|---|---|---|
| **[1/5]** | Gmail 인증 + 새 메일 조회 | `gmail_auth.get_gmail_service()` → `mail_fetcher.fetch_new_messages()` |
| **[2/5]** | 분류 (+ 업무 메일 핵심 요약) + 회신 판단/초안 + **임시보관함 초안 생성** | `classifier.classify()` (내부 `summarize_work_mail`) → 업무면 `reply_drafter.assess_reply(make_gmail_draft=True)` → `gmail_draft.create_reply_draft()` |
| **[3/5]** | 마크다운 리포트 + 요약 JSON 저장 | `report.build_report()` / `save_report()` / `save_summary()` / `summarize()` |
| **[4/5]** | 카카오톡 리포트 알림 발송 | `kakao_notify.format_summary_message()` → `send_to_me()` |
| **[5/5]** | 처리한 메일 ID 기록 | `mail_fetcher.mark_processed()` → `data/processed_ids.json` |

- 어느 단계든 실패하면 **그 실행은 실패로 끝나고(exit 1) 다음 정시에 재시도**한다.
  성공 표식을 남기지 않으므로 다음 실행이 처음부터 다시 시도한다.
  ([2/5]의 메일 1건 단위 오류는 예외 — 그 메일만 `기타` 처리하고 계속.)
- **실패 시 알림 정책**
  - `now.hour < FINAL_RUN_HOUR`(22): 로그만 남기고 **조용히 종료. 알림 없음.**
  - `now.hour >= 22` 인데 그날 성공 표식이 없음: 카카오로
    `⚠️ 오늘 메일함 확인에 실패했습니다. 맥북을 열어 확인해 주세요.` **1건** 발송.
- 새 메일이 0건이면 [2/5]·[3/5]·[5/5] 를 건너뛰고 카카오로 "새 메일 없음" 한 줄만
  보낸 뒤 **성공으로 간주**(표식 남김). 기존 리포트 파일은 덮어쓰지 않는다.
- 옵션: `--limit N`(기본 50), `--no-notify`(카카오 전부 생략),
  `--no-mark`(처리 기록·성공 표식 생략 **+ 기존 표식 무시 + 실패 알림 안 보냄
  + 임시보관함 초안도 안 만듦** = 부작용 없는 테스트 실행).

### 산출물

- `reports/<날짜>-mail-report.md` — 사람이 읽는 리포트 (회신 초안 포함)
- `reports/<날짜>-mail-report.summary.json` — 알림/재사용용 요약 수치
- `data/processed_ids.json` — 처리 완료한 메일 ID (다음 실행에서 제외)
- `data/last_success.json` — `{date, completed_at, mails_processed}`. 그날 성공 표식.

### 문제 생겼을 때 어디를 보나

- 로그: `logs/<YYYY-MM-DD>.log` (그날 실행 전부 append). 매시간 "이미 완료됨"
  줄이 반복되다가, 실제 실행 1건이 보인다.
- **[1/5] 실패** → Gmail 토큰 만료/스코프 부족. `credentials/token.json` 삭제 후
  `scripts/test_gmail_auth.py` 재실행 (`tai.roh@mizmedi.com` 로 로그인).
- **[2/5] 특정 메일만 '기타'/오류** → `ANTHROPIC_API_KEY` 확인, `classifier.py`
  / `reply_drafter.py` 예외 로그 확인 (`LOG_LEVEL=DEBUG` 로 트레이스백).
- **[2/5] "초안 생성 실패"** → 로그의 `draft_error` 확인.
  - `로그인 계정(...)이 초안 대상 계정과 다릅니다` → `credentials/token.json`
    삭제 후 `GMAIL_DRAFT_ACCOUNT` 계정으로 재인증.
  - 그 외 API 오류 → 리포트에 텍스트는 남아 있으므로 Gmail 에서 수동 작성.
- **[3/5] 실패** → `report.py`, 디스크 권한, `REPORT_DIR`.
- **[4/5] 실패** → 카카오 토큰. `KAKAO_CLIENT_SECRET` 확인,
  `scripts/test_kakao_notify.py --dry-run`, refresh 실패면 `scripts/kakao_auth.py` 재인증.
- **[5/5] 실패** → `data/` 폴더 권한.
- **하루 종일 재시도만 하고 리포트가 안 옴** → `logs/<날짜>.log` 에서 반복되는
  실패 지점 확인. 22시 실패 알림 카카오가 왔는지도 확인.
- 강제 재실행: `data/last_success.json` (+ 필요시 `data/processed_ids.json`) 삭제
  → 다음 정시(또는 `launchctl start`)에 처음부터 다시 실행.

## 스케줄러 (macOS launchd)

**오전 7:00 ~ 밤 10:00, 매 정시(1시간 간격)** 에 `scripts/run_daily.py` 를 실행한다.
정의 파일: [`launchd/com.mizmedi.mail-automation.plist`](launchd/com.mizmedi.mail-automation.plist)

- `StartCalendarInterval` 에 7,8,9,…,22시를 개별 `<dict>` 로 나열(16개).
- plist 는 `/bin/sh -c` 로 프로젝트 폴더에서 `.venv/bin/python -m scripts.run_daily`
  를 실행하고, 출력을 `logs/<YYYY-MM-DD>.log` 에 append 한다.
- 쉘/launchd 레벨 오류는 `logs/launchd.err.log` 에 기록된다.
- **왜 매시간인가**: 오전 7시에 맥북이 닫혀 있거나 오프라인이면 그 실행은
  실패한다. 매시간 재시도해서, 맥북을 열고 인터넷이 되는 첫 시각에 성공하도록
  한다. 성공하면 그날은 더 안 돈다 (위 "하루 1회 성공 모델").
- plist 안의 절대경로는 `/Users/tai/Projects/mizmedi-mail-automation` 기준이다.
  프로젝트를 옮기면 plist 의 경로 3곳을 모두 수정하고 다시 등록해야 한다.

### 등록 (최초 1회)

```bash
cd /Users/tai/Projects/mizmedi-mail-automation
mkdir -p ~/Library/LaunchAgents logs
cp launchd/com.mizmedi.mail-automation.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mizmedi.mail-automation.plist

# 등록 확인 (목록에 com.mizmedi.mail-automation 이 보이면 성공)
launchctl list | grep mizmedi

# (선택) 정시까지 안 기다리고 지금 즉시 한 번 실행해 테스트
launchctl start com.mizmedi.mail-automation
tail -f logs/$(date +%Y-%m-%d).log
```

### 해제 / 중지

```bash
# 일시 중지 (다시 load 하면 살아남)
launchctl unload ~/Library/LaunchAgents/com.mizmedi.mail-automation.plist

# 완전 제거
launchctl unload ~/Library/LaunchAgents/com.mizmedi.mail-automation.plist
rm ~/Library/LaunchAgents/com.mizmedi.mail-automation.plist
```

### 실행 시간대 변경

1. `launchctl unload ~/Library/LaunchAgents/com.mizmedi.mail-automation.plist`
2. `launchd/com.mizmedi.mail-automation.plist` 의 `StartCalendarInterval` `<array>`
   에서 `<dict>` 를 추가/삭제해 정시 목록을 바꾼다.
3. 밤 실패 알림 시각도 바꾸려면 `src/config.py` 의 `FINAL_RUN_HOUR` 를 같이 수정
   (기본 22 = 마지막 정시와 동일하게 유지).
4. `cp ... ~/Library/LaunchAgents/` 로 다시 복사 → `launchctl load ...`

### 컴퓨터가 꺼져 있거나 잠자기였을 때

- **정시에 Mac 이 꺼져 있었으면**: 그 정시 실행들은 놓친다. Mac 을 켜서
  LaunchAgent 가 로드되면 launchd 가 놓친 실행을 **1회로 합쳐서** 실행한다
  (여러 정시를 놓쳤어도 부팅 직후 1회). 그 1회가 성공하면 그날 끝.
- **정시에 Mac 이 잠자기였으면**: launchd 는 이 작업 때문에 Mac 을 깨우지
  않는다. Mac 이 깨어난 **직후 1회** 실행한다.
- 낮 동안 언제든 맥북을 열어 인터넷에 연결되면, 다음(또는 놓친) 정시 실행이
  성공하면서 그날 리포트 알림이 온다.
- 늦게 실행돼도 안전: `processed_ids.json` 중복 방지, 0건이면 리포트 유지.
- 정시에 반드시 깨워 돌리고 싶으면 launchd 만으로는 부족하고
  `pmset repeat wake ...` 예약 기상을 별도로 걸어야 한다 (현재 미설정).

## 알려진 제한사항

- **맥북이 꺼져 있거나 오프라인이면 아무 알림도 오지 않는다.** 이 자동화는
  Tai님의 맥북에서만 돈다(launchd). 하루 종일(7~22시) 맥북을 한 번도 안 켜거나
  인터넷이 안 되면:
  - 리포트 알림도 안 오고,
  - **밤 10시 "확인 실패" 알림조차 오지 않는다** (그 알림도 맥북에서 보내기
    때문). "알림이 안 왔다 = 문제없다" 가 **아니다.** 며칠 알림이 없으면
    맥북을 열어 직접 확인해야 한다.
- **아마란스10에서 직접 답장한 메일**: 병원 내부 메일 시스템(아마란스10)에서
  사람이 직접 답장을 보낸 경우, 그 발신 이력은 자동화용 Gmail 계정에서 보이지
  않는다. 원본 메일이 받은편지함에 남아 있으면 **다음 날 아침에도 같은 메일에
  회신 초안이 중복 제안될 수 있다.** → 처리한 메일은 받은편지함에서 보관
  (archive)하거나, `data/processed_ids.json` 에 해당 ID 를 수동 추가해 제외.
- **하루 첫 성공 이후 도착한 메일은 다음 날 처리된다.** "하루 1회 성공 모델"
  때문에, 예: 오전 7시 실행이 성공한 뒤 오전 10시에 온 급한 메일은 그날
  리포트에 안 들어가고 다음 날 아침 리포트에 잡힌다. 급한 건은 사람이 직접
  메일함을 봐야 한다.
- **본문 일부만 참고**: 분류·핵심 요약은 스니펫, 회신 초안은 본문 앞부분(최대
  4000자)만 본다. 첨부파일 내용·이미지·아주 긴 스레드 뒷부분은 반영 안 됨.
- **분류·회신 판단은 LLM 추정치**: 오분류나 "회신 필요/불필요" 오판이 있을 수
  있다. 리포트는 검토용 초안이며 최종 판단은 사람이 한다.
- **`GMAIL_QUERY` 기본값 `in:inbox`**: 받은편지함에 있는 한 이미 읽은 메일도
  대상이 된다. "어제 이후"로 좁히려면 `.env` 에 `GMAIL_QUERY=newer_than:2d` 등을 설정.
- **자동 발송 없음(설계상 원칙)**: 회신은 초안까지만. 실제 전송은 사람이 직접.

## 개발 순서 (로드맵)

- [x] **0. 셋업** — 폴더 구조, CLAUDE.md, `.env.example`, `.gitignore`,
  Gmail 인증 테스트 스크립트
- [x] **1. 메일 읽기** — `src/mail_fetcher.py`. `GMAIL_QUERY` 기준 신규 메일의
  발신자/제목/스니펫/수신시각 추출, `data/processed_ids.json` 로 중복 방지.
- [x] **2. 분류** — `src/classifier.py`. 규칙 기반 + `claude-sonnet-4-6` LLM
  으로 업무/광고성/스팸/기타 + 이유 한 줄. (회신 필요 여부 판단은 3단계에서)
- [x] **3. 요약 / 초안** — `src/report.py` + `src/reply_drafter.py`.
  마크다운 요약 리포트(`reports/<날짜>-mail-report.md`) 생성, 회신 필요 업무
  메일은 리포트 안에 회신 초안 포함. 전체 실행: `scripts/run_pipeline.py`.
- [x] **4. 카카오 알림** — `src/kakao_notify.py`. "나에게 보내기" API로 리포트
  요약 전송. OAuth 인증 `scripts/kakao_auth.py`, 테스트 `scripts/test_kakao_notify.py`.
- [x] **5. 통합** — `scripts/run_daily.py`. 1~4를 하나로 연결, 단계별 로그 +
  단계별 에러 격리. (위 "전체 파이프라인" 표 참고)
- [~] **6. 스케줄러 등록** — `launchd/com.mizmedi.mail-automation.plist` 작성 완료.
  **오전 7시~밤 10시 매 정시** `scripts/run_daily.py` 실행, 하루 1회 성공 모델
  (`src/run_state.py`), 22시 실패 시에만 카카오 경고.
  **`launchctl load` 등록은 Tai님이 직접 수행** (위 "스케줄러" 섹션 명령어 참고).

각 단계는 완료 후 사용자 확인을 받고 다음으로 넘어간다.

### 그 외 변경 이력

- **2026-09-02 — Gmail 스코프 확장**: `gmail.compose` 추가, 회신 초안을 Gmail
  임시보관함에 실제 생성 (`src/gmail_draft.py`). 발송 코드는 없음. 스코프가
  바뀌었으므로 **재인증 필요** (아래 "실행 방법" 첫 블록).
- **2026-09-02 — 스케줄 변경**: 08:00 1회 → 07~22시 매 정시 + 하루 1회 성공 모델.

## 실행 방법

```bash
# 최초 1회
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ── Gmail 재인증 (스코프 확장 후 필수) ──────────────────────────
#   1) 기존 토큰 삭제
rm -f credentials/token.json
#   2) 인증 스크립트 실행 → 브라우저에서 tai.roh@mizmedi.com 으로 로그인
#      → "메일 작성/전송, 임시보관함..." 권한 동의
.venv/bin/python -m scripts.test_gmail_auth
#   3) 출력된 계정이 tai.roh@mizmedi.com 인지 확인

# 메일 가져오기 + 분류 테스트
.venv/bin/python -m scripts.test_classify --limit 15

# 전체 파이프라인 (가져오기 → 분류 → 회신 초안 → 리포트 생성)
.venv/bin/python -m scripts.run_pipeline --limit 30
# 처리 완료로 기록까지 하려면:
.venv/bin/python -m scripts.run_pipeline --limit 30 --mark-processed

# 카카오 최초 1회 인증 (refresh token 발급 → .env 에 직접 붙여넣기)
.venv/bin/python -m scripts.kakao_auth

# 카카오 알림 테스트 (오늘 리포트 요약을 카카오톡으로 전송)
.venv/bin/python -m scripts.test_kakao_notify --dry-run   # 전송 없이 확인
.venv/bin/python -m scripts.test_kakao_notify

# ★ 메인 파이프라인 (스케줄러가 매 정시 실행) — 0단계 성공 표식 확인 → 1~5단계
.venv/bin/python -m scripts.run_daily
.venv/bin/python -m scripts.run_daily --no-mark --no-notify   # 부작용 없는 테스트
# 강제 재실행: 성공 표식 삭제 후 실행
rm -f data/last_success.json && .venv/bin/python -m scripts.run_daily
```

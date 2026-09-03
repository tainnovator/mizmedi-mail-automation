"""
Gmail API 인증 헬퍼.

credentials/ 안의 OAuth 클라이언트 JSON을 사용해 사용자 인증을 하고,
인증된 Gmail API 서비스 객체를 돌려준다.

- 최초 실행 시 브라우저가 열리고 Google 로그인/동의를 진행한다.
- 발급된 토큰은 credentials/token.json 에 저장되어 다음부터는 재사용된다.
- 스코프:
    gmail.readonly  — 받은편지함 메일 읽기
    gmail.compose   — 임시보관함(초안) 생성/조회/수정/삭제
  발송(send) 은 요청하지 않으며, send 를 호출하는 코드도 만들지 않는다.
  스코프가 확장되면 기존 token.json 은 무효가 되어 재인증이 필요하다.
"""

from __future__ import annotations

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import TOKEN_PATH, get_client_secret_path

# 읽기 + 초안(임시보관함) 작성. 발송(gmail.send) 은 절대 요청하지 않는다.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def _run_auth_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(
        str(get_client_secret_path()), SCOPES
    )
    # redirect_uris 가 http://localhost 이므로 로컬 서버 방식 사용
    return flow.run_local_server(port=0)


def get_credentials() -> Credentials:
    """저장된 토큰을 재사용하거나, 없으면 새로 인증 플로우를 실행한다."""
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        try:
            # scopes 인자를 주지 않아야 토큰 파일에 실제로 부여된 스코프가 로드된다.
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        except ValueError:
            creds = None

    # 저장된 토큰이 현재 필요한 스코프를 모두 포함하지 않으면(스코프 확장 등)
    # 재인증이 필요하다.
    if creds and not creds.has_scopes(SCOPES):
        creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = _run_auth_flow()
    else:
        creds = _run_auth_flow()

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service():
    """인증된 Gmail API v1 서비스 객체를 반환한다."""
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)

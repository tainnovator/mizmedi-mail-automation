"""
Gmail API 인증 헬퍼.

credentials/ 안의 OAuth 클라이언트 JSON을 사용해 사용자 인증을 하고,
인증된 Gmail API 서비스 객체를 돌려준다.

- 최초 실행 시 브라우저가 열리고 Google 로그인/동의를 진행한다.
- 발급된 토큰은 credentials/token.json 에 저장되어 다음부터는 재사용된다.
- 이 자동화는 메일을 읽기만 하므로 읽기 전용(readonly) 스코프만 요청한다.
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import TOKEN_PATH, get_client_secret_path

# 읽기 전용. 절대 발송/수정 권한을 요청하지 않는다.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_credentials() -> Credentials:
    """저장된 토큰을 재사용하거나, 없으면 새로 인증 플로우를 실행한다."""
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(get_client_secret_path()), SCOPES
        )
        # redirect_uris 가 http://localhost 이므로 로컬 서버 방식 사용
        creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service():
    """인증된 Gmail API v1 서비스 객체를 반환한다."""
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)

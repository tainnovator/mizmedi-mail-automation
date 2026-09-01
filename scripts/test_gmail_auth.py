"""
Gmail 인증 확인용 테스트 스크립트.

하는 일:
  1. credentials/ 안의 OAuth 클라이언트 JSON으로 Google 로그인
  2. 인증된 계정 이메일 주소 출력
  3. 받은편지함(INBOX) 메일 총 개수 / 안 읽은 개수 출력

실행:
  .venv/bin/python -m scripts.test_gmail_auth
  (프로젝트 루트에서 실행)

이 스크립트는 메일을 읽지도, 발송하지도 않는다. 개수만 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 루트에서 -m 없이 실행해도 import 되도록 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gmail_auth import get_gmail_service  # noqa: E402


def main() -> int:
    print("Gmail 인증을 시작합니다...")
    print("(최초 실행이면 브라우저가 열립니다. 로그인 후 권한을 허용해주세요.)\n")

    service = get_gmail_service()

    profile = service.users().getProfile(userId="me").execute()
    print(f"인증 성공: {profile.get('emailAddress')}")
    print(f"전체 메시지 수 (계정 기준): {profile.get('messagesTotal')}")
    print(f"전체 스레드 수 (계정 기준): {profile.get('threadsTotal')}\n")

    inbox = service.users().labels().get(userId="me", id="INBOX").execute()
    print("받은편지함(INBOX):")
    print(f"  - 총 메일 수     : {inbox.get('messagesTotal')}")
    print(f"  - 안 읽은 메일 수 : {inbox.get('messagesUnread')}")

    print("\n인증 및 Gmail API 호출이 정상 동작합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

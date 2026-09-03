"""
Gmail 임시보관함(초안) 생성.

- `gmail.compose` 스코프로 `drafts.create` 를 호출해 회신 초안을 만든다.
- **발송(send) 은 하지 않는다.** 이 모듈에는 send 관련 함수가 없고, 앞으로도
  만들지 않는다. 최종 확인과 전송은 사람이 Gmail 에서 직접 한다.
- 초안은 `GMAIL_DRAFT_ACCOUNT`(기본 tai.roh@mizmedi.com) 의 임시보관함에
  생성된다. 로그인 계정이 이 값과 다르면 오배치 방지를 위해 생성을 거부한다.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

from .config import GMAIL_DRAFT_ACCOUNT
from .mail_fetcher import MailMessage


class GmailDraftError(RuntimeError):
    pass


_account_check: str | None = None  # None=미확인, "ok"=일치, 그 외=불일치 메시지


def _verify_account(service) -> None:
    """로그인 계정이 초안 대상 계정과 같은지 프로세스당 1회 확인한다."""
    global _account_check
    if _account_check == "ok":
        return
    if _account_check is not None:
        raise GmailDraftError(_account_check)

    email = (
        service.users().getProfile(userId="me").execute().get("emailAddress", "")
    )
    if GMAIL_DRAFT_ACCOUNT and email.lower() != GMAIL_DRAFT_ACCOUNT.lower():
        _account_check = (
            f"로그인 계정({email or '미상'})이 초안 대상 계정"
            f"({GMAIL_DRAFT_ACCOUNT})과 다릅니다. "
            f"{GMAIL_DRAFT_ACCOUNT} 로 재인증하세요 (credentials/token.json 삭제 후 재실행)."
        )
        raise GmailDraftError(_account_check)
    _account_check = "ok"


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}" if s else "Re:"


def create_reply_draft(service, mail: MailMessage, body_text: str) -> str:
    """
    mail 의 발신자에게 보내는 회신 초안을 임시보관함에 만든다.

      받는사람 : 원본 메일의 발신자 (From)
      제목     : "Re: 원본제목"
      스레드   : 원본과 같은 스레드로 묶음 (가능한 경우)

    성공하면 생성된 draft id 를 반환한다. 실패하면 예외를 올린다.
    """
    _verify_account(service)

    msg = EmailMessage()
    msg["To"] = mail.sender
    msg["Subject"] = reply_subject(mail.subject)
    if mail.message_id_header:
        msg["In-Reply-To"] = mail.message_id_header
        msg["References"] = mail.message_id_header
    msg.set_content(body_text)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    message_body: dict = {"raw": raw}
    if mail.thread_id:
        message_body["threadId"] = mail.thread_id

    created = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": message_body})
        .execute()
    )
    return created.get("id", "")

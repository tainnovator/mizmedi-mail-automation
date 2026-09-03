"""
받은편지함에서 아직 처리하지 않은 새 메일을 가져오는 모듈.

- 대상 계정의 받은편지함(INBOX)에서 `GMAIL_QUERY` 조건에 맞는 메일 목록을 조회한다.
- 이미 처리한 메일은 다시 가져오지 않는다 (`processed_log.processed_ids()` 참조).
- 각 메일에서 발신자 / 제목 / 스니펫 / 수신 시각 / Message-ID 를 추출한다.
- `fetch_body()` 로 특정 메일의 본문 전체를 개별 조회할 수 있다 (초안 작성용).

읽기 전용이다. 메일을 읽음 처리하거나 수정하거나 발송하지 않는다.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import GMAIL_QUERY
from .gmail_auth import get_gmail_service
from .processed_log import processed_ids


@dataclass
class MailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime  # 로컬 타임존
    message_id_header: str = ""  # 원본 메일의 Message-ID 헤더 (회신 스레딩용)

    @property
    def received_str(self) -> str:
        return self.received_at.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 메일 조회
# ---------------------------------------------------------------------------
def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_message(msg: dict) -> MailMessage:
    headers = msg.get("payload", {}).get("headers", [])
    internal_ms = int(msg.get("internalDate", "0"))
    received = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc).astimezone()
    return MailMessage(
        id=msg["id"],
        thread_id=msg.get("threadId", ""),
        sender=_header(headers, "From"),
        subject=_header(headers, "Subject") or "(제목 없음)",
        snippet=msg.get("snippet", "").strip(),
        received_at=received,
        message_id_header=_header(headers, "Message-ID"),
    )


def fetch_new_messages(
    max_results: int = 50,
    service=None,
) -> list[MailMessage]:
    """
    받은편지함에서 아직 처리하지 않은 새 메일을 가져온다.

    처리 기록에는 손대지 않는다. 분류/초안 등 후속 처리가 끝난 뒤
    호출자가 processed_log.record() 로 명시적으로 기록해야 한다.
    """
    service = service or get_gmail_service()
    processed = processed_ids()

    query = f"in:inbox {GMAIL_QUERY}".strip() if "in:inbox" not in GMAIL_QUERY else GMAIL_QUERY

    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    refs = resp.get("messages", [])

    messages: list[MailMessage] = []
    for ref in refs:
        if ref["id"] in processed:
            continue
        full = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date", "Message-ID"],
            )
            .execute()
        )
        messages.append(_parse_message(full))

    messages.sort(key=lambda m: m.received_at, reverse=True)
    return messages


# ---------------------------------------------------------------------------
# 본문 가져오기 (회신 초안 작성 등, 필요한 메일만 개별 호출)
# ---------------------------------------------------------------------------
def _decode_b64url(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _walk_parts(part: dict, out: dict[str, str]) -> None:
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")
    if data and mime in ("text/plain", "text/html") and mime not in out:
        out[mime] = _decode_b64url(data)
    for sub in part.get("parts", []) or []:
        _walk_parts(sub, out)


def fetch_body(message_id: str, service=None, max_chars: int = 4000) -> str:
    """지정한 메일의 본문 텍스트를 가져온다. text/plain 우선, 없으면 HTML에서 태그 제거."""
    service = service or get_gmail_service()
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    found: dict[str, str] = {}
    _walk_parts(msg.get("payload", {}), found)

    text = found.get("text/plain", "")
    if not text and found.get("text/html"):
        text = re.sub(r"<[^>]+>", " ", found["text/html"])
    if not text:
        text = msg.get("snippet", "")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]

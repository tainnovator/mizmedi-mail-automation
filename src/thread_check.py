"""
"이미 직접 회신했는지" 확인.

회신 초안을 만들기 전에, 해당 스레드에 원본 메일 수신 시각 이후로 내가 보낸
(SENT 라벨) 메시지가 있는지 확인한다. 있으면 사용자가 정시 체크 전에 직접
답장을 보낸 것으로 보고 초안 생성을 건너뛴다.

읽기 전용이다 (gmail.readonly 로 충분). threads().get(format="minimal") 은
메시지별 labelIds 와 internalDate 만 돌려주므로 가볍다.
"""

from __future__ import annotations

from datetime import datetime, timezone


def has_sent_reply_after(service, thread_id: str, after: datetime) -> bool:
    """thread_id 스레드에 `after` 시각 이후의 SENT 메시지가 있으면 True."""
    if not thread_id:
        return False

    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="minimal")
        .execute()
    )
    for msg in thread.get("messages", []):
        if "SENT" not in msg.get("labelIds", []):
            continue
        internal_ms = int(msg.get("internalDate", "0"))
        sent_at = datetime.fromtimestamp(
            internal_ms / 1000, tz=timezone.utc
        ).astimezone()
        if sent_at > after:
            return True
    return False

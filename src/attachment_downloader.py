"""
첨부파일 규칙 매칭 + 다운로드.

check_and_download_attachments() 하나로 노출한다:
  1. "첨부파일이 있는 최근 메일"을 넓게 가져온다 (config.ATTACHMENT_GMAIL_QUERY).
  2. 각 메일을 attachment_rules.match() 로 판정한다
     (발신자+제목 둘 다 맞으면 confirmed, 하나만 맞으면 partial/미확인).
  3. confirmed 메일의 첨부파일 중 허용 확장자(ALLOWED_ATTACHMENT_EXTENSIONS)만,
     아직 저장하지 않은 것만(data/attachment_log.json 로 dedup) 다운로드한다.
  4. ATTACHMENT_DOWNLOAD_ROOT/{업체 폴더}/{업체명}_{YYYYMM}_{원본파일명} 으로 저장한다.

이 모듈은 run_daily.py 파이프라인과 독립적이다. processed_ids.json 을 보지도
건드리지도 않는다 — 첨부파일 체크는 언제든 별도로 즉시 실행할 수 있어야 하기
때문이다. 나중에 run_daily.py 에 합칠 때도 check_and_download_attachments() 를
그대로 import 해서 쓸 수 있다.

읽기 전용 Gmail 권한(gmail.readonly)만으로 동작한다. 새 스코프가 필요 없다.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .attachment_rules import AttachmentRule, load_rules, match
from .config import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    ATTACHMENT_DOWNLOAD_ROOT,
    ATTACHMENT_GMAIL_QUERY,
    ATTACHMENT_LOG_PATH,
)
from .gmail_auth import get_gmail_service


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------
@dataclass
class CandidateMail:
    id: str
    sender: str
    subject: str
    received_at: datetime


@dataclass
class AttachmentOutcome:
    mail: CandidateMail
    status: str  # "downloaded" | "duplicate" | "unmatched_ext" | "partial" | "none"
    vendor: str | None = None
    filename: str | None = None
    saved_path: str | None = None
    detail: str = ""


@dataclass
class AttachmentCheckResult:
    checked: int = 0
    downloaded: int = 0
    partial: int = 0
    dry_run: bool = False
    outcomes: list[AttachmentOutcome] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 메일 조회 (processed_log 와 무관하게 독립적으로 조회)
# ---------------------------------------------------------------------------
def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _fetch_candidates(service, query: str, max_results: int) -> list[CandidateMail]:
    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    refs = resp.get("messages", [])

    candidates: list[CandidateMail] = []
    for ref in refs:
        full = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = full.get("payload", {}).get("headers", [])
        internal_ms = int(full.get("internalDate", "0"))
        received = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc).astimezone()
        candidates.append(
            CandidateMail(
                id=full["id"],
                sender=_header(headers, "From"),
                subject=_header(headers, "Subject") or "(제목 없음)",
                received_at=received,
            )
        )

    candidates.sort(key=lambda m: m.received_at, reverse=True)
    return candidates


def _list_attachment_parts(payload: dict) -> list[dict]:
    """파일명 + attachmentId 가 있는 첨부파일 파트만 재귀적으로 모은다."""
    found: list[dict] = []

    def walk(part: dict) -> None:
        filename = part.get("filename", "")
        body = part.get("body", {})
        if filename and body.get("attachmentId"):
            found.append(part)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return found


# ---------------------------------------------------------------------------
# 중복 방지 로그 (data/attachment_log.json)
# ---------------------------------------------------------------------------
def _load_log() -> dict:
    if not ATTACHMENT_LOG_PATH.exists():
        return {}
    try:
        return json.loads(ATTACHMENT_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_log(log: dict) -> None:
    ATTACHMENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ATTACHMENT_LOG_PATH.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log_key(message_id: str, attachment_id: str) -> str:
    return f"{message_id}:{attachment_id}"


# ---------------------------------------------------------------------------
# 파일명 / 저장 경로
# ---------------------------------------------------------------------------
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(name: str) -> str:
    return _UNSAFE_CHARS.sub("_", name).strip() or "attachment"


def _target_path(folder: str, vendor: str, yyyymm: str, original_filename: str) -> Path:
    """저장할 경로를 정한다. 같은 이름 파일이 이미 있으면(로그에 없는 예외 상황
    포함) 번호를 붙여 덮어쓰지 않는다."""
    safe_name = _safe_filename(original_filename)
    base = ATTACHMENT_DOWNLOAD_ROOT / folder
    filename = f"{vendor}_{yyyymm}_{safe_name}"
    candidate = base / filename
    if not candidate.exists():
        return candidate

    stem, dot, ext = filename.rpartition(".")
    n = 2
    while True:
        alt_name = f"{stem}_{n}.{ext}" if dot else f"{filename}_{n}"
        alt = base / alt_name
        if not alt.exists():
            return alt
        n += 1


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def check_and_download_attachments(
    service=None,
    rules: list[AttachmentRule] | None = None,
    query: str | None = None,
    max_results: int = 50,
    dry_run: bool = False,
) -> AttachmentCheckResult:
    """
    첨부파일 대상 메일을 확인하고, 확정 매칭된 것만 다운로드한다.

    dry_run=True 면 실제 파일 저장/로그 기록 없이 판정 결과만 돌려준다
    (시연 전 미리보기, 테스트용).
    """
    service = service or get_gmail_service()
    rules = rules if rules is not None else load_rules()
    query = query if query is not None else ATTACHMENT_GMAIL_QUERY

    candidates = _fetch_candidates(service, query, max_results)
    log = _load_log()
    result = AttachmentCheckResult(checked=len(candidates), dry_run=dry_run)

    for mail in candidates:
        rule_match = match(mail.sender, mail.subject, rules)

        if rule_match.status == "none":
            result.outcomes.append(AttachmentOutcome(mail=mail, status="none"))
            continue

        if rule_match.status == "partial":
            result.partial += 1
            which = []
            if rule_match.sender_matched:
                which.append("발신자만 일치")
            if rule_match.subject_matched:
                which.append("제목만 일치")
            result.outcomes.append(
                AttachmentOutcome(
                    mail=mail,
                    status="partial",
                    vendor=rule_match.rule.vendor if rule_match.rule else None,
                    detail=", ".join(which),
                )
            )
            continue

        # confirmed
        rule = rule_match.rule
        assert rule is not None
        yyyymm = mail.received_at.strftime("%Y%m")

        full = (
            service.users()
            .messages()
            .get(userId="me", id=mail.id, format="full")
            .execute()
        )
        attachment_parts = _list_attachment_parts(full.get("payload", {}))

        if not attachment_parts:
            result.outcomes.append(
                AttachmentOutcome(
                    mail=mail, status="none", vendor=rule.vendor, detail="첨부파일 없음"
                )
            )
            continue

        for part in attachment_parts:
            filename = part.get("filename", "")
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
                result.outcomes.append(
                    AttachmentOutcome(
                        mail=mail,
                        status="unmatched_ext",
                        vendor=rule.vendor,
                        filename=filename,
                        detail=f"대상 형식 아님(.{ext})",
                    )
                )
                continue

            attachment_id = part["body"]["attachmentId"]
            key = _log_key(mail.id, attachment_id)
            if key in log:
                result.outcomes.append(
                    AttachmentOutcome(
                        mail=mail, status="duplicate", vendor=rule.vendor, filename=filename
                    )
                )
                continue

            target = _target_path(rule.folder, rule.vendor, yyyymm, filename)

            if not dry_run:
                data = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=mail.id, id=attachment_id)
                    .execute()
                )
                content = base64.urlsafe_b64decode(data["data"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

                log[key] = {
                    "vendor": rule.vendor,
                    "message_id": mail.id,
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "saved_path": str(target),
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                }

            result.downloaded += 1
            result.outcomes.append(
                AttachmentOutcome(
                    mail=mail,
                    status="downloaded",
                    vendor=rule.vendor,
                    filename=filename,
                    saved_path=str(target),
                )
            )

    if not dry_run:
        _save_log(log)

    return result

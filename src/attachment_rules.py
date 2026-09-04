"""
첨부파일 자동 저장 규칙 (config/attachment_rules.json).

업체/발신자별로 "이 발신자한테서, 이런 제목의 메일이 오면 첨부파일을 저장한다"
규칙을 정의한다. 발신자 이메일과 제목 키워드가 **둘 다** 맞아야 확정 매칭이고,
하나만 맞으면 partial(미확인)로 남겨서 다운로드는 하지 않는다 (오매칭 방지).

규칙 파일 형식 (config/attachment_rules.json):
  [
    {
      "vendor": "시연용",
      "sender_emails": ["example@example.com"],
      "subject_keywords": ["거래명세표"],
      "folder": "시연용"
    },
    ...
  ]

config/attachment_rules.json 은 실제 이메일 주소가 들어가므로 git 제외 대상이다.
구조 참고용으로 config/attachment_rules.example.json 을 커밋해둔다. 나중에 실제
업체 규칙을 추가할 땐 이 파일에 항목만 추가하면 된다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import ATTACHMENT_RULES_PATH

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class AttachmentRule:
    vendor: str
    sender_emails: list[str]  # 소문자로 정규화됨
    subject_keywords: list[str]
    folder: str


@dataclass
class RuleMatch:
    status: str  # "confirmed" | "partial" | "none"
    rule: AttachmentRule | None = None
    sender_matched: bool = False
    subject_matched: bool = False


def _extract_email(sender_header: str) -> str:
    """'이름 <email>' 또는 'email' 형태에서 이메일 주소만 뽑아 소문자로 돌려준다."""
    found = _EMAIL_RE.search(sender_header or "")
    return found.group(0).lower() if found else ""


def load_rules() -> list[AttachmentRule]:
    if not ATTACHMENT_RULES_PATH.exists():
        raise FileNotFoundError(
            f"{ATTACHMENT_RULES_PATH} 가 없습니다. "
            "config/attachment_rules.example.json 을 참고해 "
            "config/attachment_rules.json 을 만들어주세요."
        )
    raw = json.loads(ATTACHMENT_RULES_PATH.read_text(encoding="utf-8"))
    rules: list[AttachmentRule] = []
    for item in raw:
        rules.append(
            AttachmentRule(
                vendor=item["vendor"],
                sender_emails=[e.lower() for e in item.get("sender_emails", [])],
                subject_keywords=list(item.get("subject_keywords", [])),
                folder=item.get("folder", item["vendor"]),
            )
        )
    return rules


def match(
    sender_header: str,
    subject: str,
    rules: list[AttachmentRule] | None = None,
) -> RuleMatch:
    """
    메일 하나(발신자 헤더, 제목)를 규칙들과 비교한다.

    - 어떤 규칙이든 발신자 AND 제목 키워드가 모두 맞으면 곧바로 confirmed 로 반환.
    - confirmed 가 없는데 발신자만 맞거나 제목만 맞는 규칙이 있으면 partial(미확인).
    - 아무 규칙과도 안 겹치면 none.
    """
    rules = rules if rules is not None else load_rules()
    sender_email = _extract_email(sender_header)
    subject_lower = (subject or "").lower()

    best_partial: RuleMatch | None = None

    for rule in rules:
        sender_matched = bool(sender_email) and sender_email in rule.sender_emails
        subject_matched = any(kw.lower() in subject_lower for kw in rule.subject_keywords)

        if sender_matched and subject_matched:
            return RuleMatch(
                status="confirmed", rule=rule, sender_matched=True, subject_matched=True
            )

        if (sender_matched or subject_matched) and best_partial is None:
            best_partial = RuleMatch(
                status="partial",
                rule=rule,
                sender_matched=sender_matched,
                subject_matched=subject_matched,
            )

    return best_partial or RuleMatch(status="none")

"""
메일 분류 로직.

2단계로 동작한다.

  1) 규칙 기반 필터 (rule)
     - 제목/스니펫에 "광고", "(광고)", "수신거부", "unsubscribe" 등
       광고성 신호 단어가 있으면 -> "광고성"
     - 발신자가 알려진 광고성 발송 패턴(newsletter@, noreply@, @mail. 등)이면
       -> "광고성"
     규칙으로 명확히 광고성이라고 판단되는 경우에만 확정한다.

  2) LLM 분류 (llm)
     - 규칙으로 판단이 안 되는 메일은 Anthropic API(claude-sonnet-4-6)를 호출해
       "업무" / "광고성" / "스팸" / "기타" 중 하나로 분류한다.
     - 분류 이유도 한 줄로 함께 받는다.
     - ANTHROPIC_API_KEY 가 없으면 LLM 단계는 건너뛰고 "기타"로 둔다.

  3) 핵심 요약 (업무 메일 한정)
     - "업무" 로 분류된 메일에 대해서만, "이 메일이 무슨 내용인지" 자체를
       1~2문장으로 요약한다 (분류 이유와는 별개). 카카오 알림에서 쓴다.
     - 실패하거나 키가 없으면 summary 는 None 으로 둔다 (파이프라인은 계속).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import ANTHROPIC_API_KEY, CLASSIFIER_MODEL
from .mail_fetcher import MailMessage

CATEGORIES = ("업무", "광고성", "스팸", "기타")

# 광고성 신호 단어 (제목/스니펫에서 검사, 소문자 비교)
AD_KEYWORDS = (
    "광고",
    "(광고)",
    "[광고]",
    "수신거부",
    "무료수신거부",
    "무료거부",
    "unsubscribe",
    "opt-out",
    "newsletter",
    "뉴스레터",
    "프로모션",
    "할인쿠폰",
    "이벤트 안내",
    "특가",
)

# 광고성 발신자 패턴 (발신자 문자열에서 검사, 소문자 비교)
AD_SENDER_PATTERNS = (
    "newsletter@",
    "no-reply@",
    "noreply@",
    "donotreply@",
    "do-not-reply@",
    "mailer@",
    "marketing@",
    "promo@",
    "notification@",
    "news@",
    "@mail.",
    "@email.",
    "@e.",
    "@news.",
    "@newsletter.",
    "@marketing.",
    "@mkt.",
    "@t.",
)


@dataclass
class Classification:
    category: str  # CATEGORIES 중 하나
    reason: str  # 한 줄 이유
    method: str  # "rule" | "llm" | "llm-error" | "no-api-key"
    summary: str | None = None  # "업무" 메일의 1~2문장 핵심 요약 (그 외에는 None)


# ---------------------------------------------------------------------------
# 1단계: 규칙 기반
# ---------------------------------------------------------------------------
def classify_by_rules(mail: MailMessage) -> Classification | None:
    text = f"{mail.subject}\n{mail.snippet}".lower()
    sender = mail.sender.lower()

    for kw in AD_KEYWORDS:
        if kw.lower() in text:
            return Classification(
                category="광고성",
                reason=f'제목/본문에 광고성 단어 "{kw}" 포함',
                method="rule",
            )

    for pat in AD_SENDER_PATTERNS:
        if pat in sender:
            return Classification(
                category="광고성",
                reason=f'발신자가 광고성 발송 패턴 "{pat}" 에 해당',
                method="rule",
            )

    return None


# ---------------------------------------------------------------------------
# 2단계: LLM
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "너는 병원 직원의 업무 메일함을 정리하는 분류기다. "
    "메일 한 통의 발신자·제목·본문 요약을 보고 다음 4가지 중 하나로 분류한다.\n"
    "- 업무: 실제 업무 관련 메일 (거래처, 내부 공지, 회의, 계약, 문의 응대 등)\n"
    "- 광고성: 마케팅·홍보·뉴스레터·프로모션 등 정보성이지만 업무는 아닌 메일\n"
    "- 스팸: 피싱, 사기, 악성, 명백히 원치 않는 대량 발송\n"
    "- 기타: 위 어디에도 뚜렷하게 속하지 않는 경우\n\n"
    '반드시 아래 JSON 형식 한 줄로만 답한다. 다른 텍스트는 절대 쓰지 않는다.\n'
    '{"category": "업무|광고성|스팸|기타", "reason": "한국어 한 문장 이유"}'
)


def _build_user_prompt(mail: MailMessage) -> str:
    return (
        f"발신자: {mail.sender}\n"
        f"제목: {mail.subject}\n"
        f"수신시각: {mail.received_str}\n"
        f"본문 요약: {mail.snippet}"
    )


def _parse_llm_json(raw: str) -> tuple[str, str]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    category = str(data.get("category", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if category not in CATEGORIES:
        category = "기타"
    return category, reason or "이유 없음"


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def classify_by_llm(mail: MailMessage) -> Classification:
    if not ANTHROPIC_API_KEY:
        return Classification(
            category="기타",
            reason="ANTHROPIC_API_KEY 미설정으로 LLM 분류 건너뜀",
            method="no-api-key",
        )

    try:
        resp = _get_client().messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(mail)}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        category, reason = _parse_llm_json(raw)
        return Classification(category=category, reason=reason, method="llm")
    except Exception as e:  # noqa: BLE001 - 분류 실패해도 파이프라인은 계속
        return Classification(
            category="기타",
            reason=f"LLM 분류 오류: {type(e).__name__}",
            method="llm-error",
        )


# ---------------------------------------------------------------------------
# 3단계: 업무 메일 핵심 요약
# ---------------------------------------------------------------------------
_SUMMARY_SYSTEM_PROMPT = (
    "너는 병원 직원의 업무 메일을 짧게 요약하는 비서다. "
    "발신자·제목·본문 요약을 보고, 이 메일이 '무슨 내용인지'를 한국어 1~2문장으로 요약한다. "
    "분류하거나 평가하지 말고 내용만 요약한다. "
    "발신자 이름·소속은 반복하지 말고, 요청·공유·문의 등 핵심 용건 위주로 쓴다. "
    "따옴표·머리말·불릿 없이 요약 문장만 출력한다. 50자 이내로 간결하게."
)


def _one_line(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_work_mail(mail: MailMessage) -> str | None:
    """'업무' 메일의 핵심 내용을 1~2문장으로 요약한다. 실패 시 None."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        resp = _get_client().messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=200,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(mail)}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        return _one_line(raw) or None
    except Exception:  # noqa: BLE001 - 요약 실패해도 파이프라인은 계속
        return None


# ---------------------------------------------------------------------------
# 통합 진입점
# ---------------------------------------------------------------------------
def classify(mail: MailMessage) -> Classification:
    rule_result = classify_by_rules(mail)
    result = rule_result if rule_result is not None else classify_by_llm(mail)
    if result.category == "업무":
        result.summary = summarize_work_mail(mail)
    return result

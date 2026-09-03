"""
회신 필요 여부 판단 + 회신 초안 작성.

"업무"로 분류된 메일에 대해서만 호출한다.

  - 안전장치: 먼저 thread_check.has_sent_reply_after() 로 "이미 직접 회신했는지"
    확인한다. 그렇다면 LLM 호출·초안 생성을 건너뛰고 already_replied=True 로 리턴.
  - Claude API를 한 번 호출해 다음을 함께 받는다.
      needs_reply : 이 메일에 수신자가 회신해야 하는가 (true/false)
      reason      : 그렇게 판단한 이유 한 줄
      draft       : needs_reply 가 true 일 때만, 정중한 업무용 한국어 회신 초안
  - 본문은 mail_fetcher.fetch_body() 로 개별 조회해서 함께 전달한다.
  - draft 가 있으면 (make_gmail_draft=True 인 경우) Gmail 임시보관함에도
    실제 초안 메일을 만든다 (gmail_draft.create_reply_draft).

중요: 이 초안은 **발송되지 않는다.** 임시보관함에만 저장되고, 리포트 문서에도
텍스트로 남는다(이중 기록). 최종 확인과 전송은 사람이 Gmail 에서 직접 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import ANTHROPIC_API_KEY, DRAFTER_MODEL
from .gmail_draft import create_reply_draft
from .mail_fetcher import MailMessage, fetch_body
from .thread_check import has_sent_reply_after


@dataclass
class ReplyAssessment:
    needs_reply: bool
    reason: str
    draft: str | None  # needs_reply=True 일 때만 채워짐
    method: str  # "llm" | "no-api-key" | "llm-error" | "already-replied"
    # Gmail 임시보관함 초안 생성 결과
    draft_id: str | None = None  # 생성 성공 시 draft id
    draft_created: bool = False
    draft_error: str | None = None  # 생성 실패 시 사유
    already_replied: bool = False  # 스레드에 수신 이후 내가 보낸 메시지가 있음

    @property
    def reply_status(self) -> str:
        """processed_log / 리포트 / 카카오에서 쓰는 단일 상태 문자열."""
        if self.already_replied:
            return "already_replied"
        if self.draft_created:
            return "draft_created"
        if self.draft and self.draft_error:
            return "draft_failed"
        if self.needs_reply:
            return "needs_reply"  # 초안 텍스트는 있으나 생성 시도 안 함(테스트 등)
        return "no_reply_needed"


_SYSTEM_PROMPT = (
    "너는 미즈메디병원 직원의 업무 메일 회신을 돕는 비서다. "
    "받은 업무 메일 한 통을 보고, 수신자(병원 직원)가 이 메일에 회신해야 하는지 판단한다.\n\n"
    "회신이 필요한 경우 예시: 질문·문의, 확인/승인 요청, 일정 조율, 자료 요청, "
    "답변을 기다리는 제안. 회신이 불필요한 경우 예시: 단순 공지·안내, 자동 발송 알림, "
    "참고용 공유, 이미 종결된 대화.\n\n"
    "회신이 필요하면 정중하고 간결한 업무용 한국어 회신 초안을 작성한다. "
    "구체 정보(날짜, 담당자명, 금액 등)를 모르면 [일정], [담당자], [금액] 같은 "
    "대괄호 자리표시자를 남긴다. 서명은 '[보내는 사람]' 으로 둔다.\n\n"
    "반드시 아래 JSON 형식으로만 답한다. 다른 텍스트는 쓰지 않는다.\n"
    '{"needs_reply": true 또는 false, "reason": "판단 이유 한 문장", '
    '"draft": "회신 초안 전문 (needs_reply=false 이면 빈 문자열)"}'
)


def _build_user_prompt(mail: MailMessage, body: str) -> str:
    return (
        f"발신자: {mail.sender}\n"
        f"제목: {mail.subject}\n"
        f"수신시각: {mail.received_str}\n"
        f"본문:\n{body or mail.snippet}"
    )


def _parse_json(raw: str) -> tuple[bool, str, str]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    needs = bool(data.get("needs_reply", False))
    reason = str(data.get("reason", "")).strip() or "이유 없음"
    draft = str(data.get("draft", "")).strip()
    return needs, reason, draft


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def assess_reply(
    mail: MailMessage,
    service=None,
    make_gmail_draft: bool = False,
    check_already_replied: bool = True,
) -> ReplyAssessment:
    if not ANTHROPIC_API_KEY:
        return ReplyAssessment(
            needs_reply=False,
            reason="ANTHROPIC_API_KEY 미설정으로 회신 판단 건너뜀",
            draft=None,
            method="no-api-key",
        )

    if service is None and (make_gmail_draft or check_already_replied):
        from .gmail_auth import get_gmail_service

        service = get_gmail_service()

    # 안전장치: 이미 사용자가 직접 회신했으면 LLM 호출·초안 생성을 건너뛴다.
    if check_already_replied and service is not None:
        try:
            if has_sent_reply_after(service, mail.thread_id, mail.received_at):
                return ReplyAssessment(
                    needs_reply=False,
                    reason="스레드에 수신 이후 보낸 메시지가 있어 이미 직접 회신한 것으로 판단",
                    draft=None,
                    method="already-replied",
                    already_replied=True,
                )
        except Exception:  # noqa: BLE001 - 확인 실패 시 안전하게 정상 경로로 진행
            pass

    try:
        body = fetch_body(mail.id, service=service)
    except Exception:  # noqa: BLE001 - 본문 조회 실패 시 스니펫으로 진행
        body = mail.snippet

    try:
        resp = _get_client().messages.create(
            model=DRAFTER_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(mail, body)}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        needs, reason, draft = _parse_json(raw)
    except Exception as e:  # noqa: BLE001
        return ReplyAssessment(
            needs_reply=False,
            reason=f"회신 판단 오류: {type(e).__name__}",
            draft=None,
            method="llm-error",
        )

    assessment = ReplyAssessment(
        needs_reply=needs,
        reason=reason,
        draft=draft if (needs and draft) else None,
        method="llm",
    )

    # Gmail 임시보관함에 실제 초안 생성 (발송 아님)
    if assessment.draft and make_gmail_draft:
        try:
            assessment.draft_id = create_reply_draft(
                service, mail, assessment.draft
            )
            assessment.draft_created = True
        except Exception as e:  # noqa: BLE001 - 초안 저장 실패해도 파이프라인은 계속
            assessment.draft_error = f"{type(e).__name__}: {e}"

    return assessment

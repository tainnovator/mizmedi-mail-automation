"""
분류 결과로 마크다운 요약 리포트를 생성/저장한다.

리포트 구성
  1. 전체 통계 (업무/광고성/스팸/기타 건수)
  2. 카테고리별 메일 목록 (발신자, 제목, 수신 시각, 분류 이유)
  3. 회신 초안 섹션 ("업무" 중 회신 필요 메일만)

저장 위치: REPORT_DIR/<날짜>-mail-report.md  (예: reports/2026-09-01-mail-report.md)

회신 초안은 리포트 문서 안에만 존재한다. 별도 저장·발송은 하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

from .classifier import CATEGORIES, Classification
from .config import REPORT_PATH, TARGET_GMAIL_ADDRESS
from .mail_fetcher import MailMessage
from .reply_drafter import ReplyAssessment


@dataclass
class MailResult:
    mail: MailMessage
    classification: Classification
    reply: ReplyAssessment | None = None  # "업무" 인 경우에만


def _stats_table(results: list[MailResult]) -> str:
    counts = {c: 0 for c in CATEGORIES}
    for r in results:
        counts[r.classification.category] = counts.get(r.classification.category, 0) + 1
    lines = ["| 분류 | 건수 |", "|---|---|"]
    for c in CATEGORIES:
        lines.append(f"| {c} | {counts[c]} |")
    lines.append(f"| **합계** | **{len(results)}** |")
    return "\n".join(lines)


def _category_section(category: str, results: list[MailResult]) -> str:
    items = [r for r in results if r.classification.category == category]
    out = [f"## {category} ({len(items)}건)", ""]
    if not items:
        out.append("_해당 없음_")
        out.append("")
        return "\n".join(out)

    for i, r in enumerate(items, 1):
        m, c = r.mail, r.classification
        out.append(f"### {i}. {m.subject}")
        out.append(f"- 발신자: {m.sender}")
        out.append(f"- 수신 시각: {m.received_str}")
        out.append(f"- 분류 이유: {c.reason} _(방식: {c.method})_")
        if r.reply is not None:
            if r.reply.already_replied:
                out.append(f"- 회신: ✅ 이미 직접 회신 완료 (초안 생략) — {r.reply.reason}")
            else:
                mark = "필요" if r.reply.needs_reply else "불필요"
                out.append(f"- 회신 {mark}: {r.reply.reason}")
        out.append("")
    return "\n".join(out)


def _draft_section(results: list[MailResult]) -> str:
    drafts = [
        r
        for r in results
        if r.reply is not None and r.reply.needs_reply and r.reply.draft
    ]
    out = ["## 회신 초안", ""]
    out.append(
        "> ⚠️ 아래 초안은 **발송되지 않습니다.** Gmail 임시보관함에 초안으로 저장되며, "
        "이 문서에도 텍스트로 남습니다(이중 기록). 최종 확인과 전송은 반드시 사람이 "
        "Gmail 에서 직접 합니다."
    )
    out.append("")
    if not drafts:
        out.append("_회신이 필요한 업무 메일이 없습니다._")
        out.append("")
        return "\n".join(out)

    for i, r in enumerate(drafts, 1):
        m = r.mail
        out.append(f"### {i}. {m.subject}")
        out.append(f"- 수신자(회신 대상): {m.sender}")
        out.append(f"- 회신 필요 이유: {r.reply.reason}")
        if r.reply.draft_created:
            out.append(
                f"- Gmail 임시보관함: ✅ 초안 생성됨 (draft id: `{r.reply.draft_id}`)"
            )
        elif r.reply.draft_error:
            out.append(f"- Gmail 임시보관함: ❌ 생성 실패 — {r.reply.draft_error}")
        else:
            out.append("- Gmail 임시보관함: (생성 시도 안 함)")
        out.append("")
        out.append("```text")
        out.append(r.reply.draft or "")
        out.append("```")
        out.append("")
    return "\n".join(out)


def build_report(results: list[MailResult], report_date: date_cls | None = None) -> str:
    report_date = report_date or date_cls.today()
    parts = [
        f"# 메일 요약 리포트 — {report_date.isoformat()}",
        "",
        f"- 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 대상 계정: {TARGET_GMAIL_ADDRESS or '(미설정)'}",
        f"- 오늘 처리한 메일: {len(results)}건 (매시간 체크로 누적)",
        "",
        "## 전체 통계",
        "",
        _stats_table(results),
        "",
    ]
    for category in CATEGORIES:
        parts.append(_category_section(category, results))
    parts.append(_draft_section(results))
    return "\n".join(parts).rstrip() + "\n"


def results_from_entries(entries: list[dict]) -> list["MailResult"]:
    """
    processed_log 의 entry dict 목록을 MailResult 목록으로 되살린다.
    (리포트를 그날 처리분 누적으로 재생성할 때 사용)
    """
    out: list[MailResult] = []
    for e in entries:
        try:
            recv = datetime.fromisoformat(e["received_at"])
        except (KeyError, ValueError, TypeError):
            recv = datetime.now()
        mail = MailMessage(
            id=e.get("id", ""),
            thread_id=e.get("thread_id", ""),
            sender=e.get("sender", ""),
            subject=e.get("subject", "(제목 없음)"),
            snippet="",
            received_at=recv,
            message_id_header="",
        )
        clf = Classification(
            category=e.get("category", "기타"),
            reason=e.get("classify_reason", ""),
            method=e.get("classify_method", "llm"),
            summary=e.get("summary"),
        )
        reply = None
        status = e.get("reply_status")
        if e.get("category") == "업무" and status not in (None, "not_applicable"):
            reply = ReplyAssessment(
                needs_reply=bool(e.get("needs_reply")),
                reason=e.get("reply_reason", ""),
                draft=e.get("draft_text"),
                method=e.get("reply_method", "llm"),
                draft_id=e.get("draft_id"),
                draft_created=(status == "draft_created"),
                draft_error=e.get("draft_error"),
                already_replied=(status == "already_replied"),
            )
        out.append(MailResult(mail=mail, classification=clf, reply=reply))

    out.sort(key=lambda r: r.mail.received_at, reverse=True)
    return out


def summarize(results: list[MailResult], report_date: date_cls | None = None) -> dict:
    """리포트의 핵심 수치만 담은 요약 dict. 카카오 알림 등에서 재사용한다."""
    report_date = report_date or date_cls.today()
    counts = {c: 0 for c in CATEGORIES}
    for r in results:
        counts[r.classification.category] = counts.get(r.classification.category, 0) + 1
    draft_count = sum(
        1 for r in results if r.reply and r.reply.needs_reply and r.reply.draft
    )
    drafts_created = sum(
        1 for r in results if r.reply and r.reply.draft_created
    )
    drafts_failed = sum(
        1 for r in results if r.reply and r.reply.draft and r.reply.draft_error
    )
    already_replied = sum(
        1 for r in results if r.reply and r.reply.already_replied
    )

    # 업무 메일: 우선순위 = 회신 필요(초안) 먼저, 그다음 이미 답장 완료, 최근 수신 먼저
    def _rank(r: MailResult) -> int:
        if r.reply and (r.reply.draft_created or r.reply.draft_error):
            return 0
        if r.reply and r.reply.already_replied:
            return 1
        return 2

    work = [r for r in results if r.classification.category == "업무"]
    work.sort(key=lambda r: (_rank(r), -r.mail.received_at.timestamp()))
    work_mails = [
        {
            "sender": r.mail.sender,
            "subject": r.mail.subject,
            "summary": r.classification.summary,
            "needs_reply": bool(r.reply and r.reply.needs_reply),
            "reply_status": r.reply.reply_status if r.reply else "not_applicable",
            "received_at": r.mail.received_str,
        }
        for r in work
    ]

    return {
        "date": report_date.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "counts": counts,
        "reply_drafts": draft_count,
        "drafts_created": drafts_created,
        "drafts_failed": drafts_failed,
        "already_replied": already_replied,
        "work_mails": work_mails,
    }


def summary_path(report_date: date_cls | None = None) -> Path:
    report_date = report_date or date_cls.today()
    return REPORT_PATH / f"{report_date.isoformat()}-mail-report.summary.json"


def save_report(content: str, report_date: date_cls | None = None) -> Path:
    report_date = report_date or date_cls.today()
    REPORT_PATH.mkdir(parents=True, exist_ok=True)
    path = REPORT_PATH / f"{report_date.isoformat()}-mail-report.md"
    path.write_text(content, encoding="utf-8")
    return path


def save_summary(results: list[MailResult], report_date: date_cls | None = None) -> Path:
    """카카오 알림 등이 읽을 수 있도록 요약 수치를 JSON 으로 저장한다."""
    report_date = report_date or date_cls.today()
    REPORT_PATH.mkdir(parents=True, exist_ok=True)
    path = summary_path(report_date)
    data = summarize(results, report_date)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_summary(report_date: date_cls | None = None) -> dict:
    """저장된 요약 JSON 을 읽는다. 없으면 FileNotFoundError."""
    path = summary_path(report_date)
    return json.loads(path.read_text(encoding="utf-8"))

"""
개발용 부분 실행: 메일 가져오기 -> 분류 -> (업무 메일) 회신 판단/초안 -> 리포트 생성.

카카오 알림·처리 기록은 하지 않는다 (리포트/초안만 빠르게 확인하고 싶을 때).
매일 실행하는 전체 파이프라인은 scripts/run_daily.py 를 쓴다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.run_pipeline
  .venv/bin/python -m scripts.run_pipeline --limit 30
  .venv/bin/python -m scripts.run_pipeline --mark-processed   # 처리 완료로 기록
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.classifier import classify  # noqa: E402
from src.gmail_auth import get_gmail_service  # noqa: E402
from src.mail_fetcher import fetch_new_messages, mark_processed  # noqa: E402
from src.report import (  # noqa: E402
    MailResult,
    build_report,
    save_report,
    save_summary,
)
from src.reply_drafter import assess_reply  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="메일 자동화 파이프라인 (리포트까지)")
    parser.add_argument("--limit", type=int, default=30, help="가져올 최대 메일 수")
    parser.add_argument(
        "--mark-processed",
        action="store_true",
        help="처리한 메일을 완료로 기록 (다음 실행부터 제외)",
    )
    args = parser.parse_args()

    service = get_gmail_service()

    print("1) 새 메일 가져오는 중...")
    mails = fetch_new_messages(max_results=args.limit, service=service)
    print(f"   -> {len(mails)}건")

    if not mails:
        print("처리할 새 메일이 없습니다. 종료합니다.")
        return 0

    print("2) 분류 중...")
    results: list[MailResult] = []
    for m in mails:
        c = classify(m)
        r = None
        if c.category == "업무":
            r = assess_reply(m, service=service)
        results.append(MailResult(mail=m, classification=c, reply=r))
        reply_note = ""
        if r is not None:
            reply_note = "  [회신 필요]" if r.needs_reply else "  [회신 불필요]"
        print(f"   - {c.category:<4} | {m.subject[:40]}{reply_note}")

    print("3) 리포트 생성 중...")
    today = date.today()
    content = build_report(results, report_date=today)
    path = save_report(content, report_date=today)
    save_summary(results, report_date=today)
    print(f"   -> 저장: {path}")

    draft_count = sum(
        1 for r in results if r.reply and r.reply.needs_reply and r.reply.draft
    )
    print(f"\n완료. 메일 {len(results)}건, 회신 초안 {draft_count}건.")

    if args.mark_processed:
        mark_processed([r.mail.id for r in results])
        print(f"{len(results)}건을 처리 완료로 기록했습니다.")
    else:
        print("(처리 기록은 저장하지 않았습니다. --mark-processed 로 저장 가능)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

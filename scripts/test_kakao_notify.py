"""
카카오톡 알림 단독 테스트.

동작
  - 오늘 날짜의 리포트 요약(reports/<날짜>-mail-report.summary.json)을 읽는다.
  - 없으면 안내 후, --run-pipeline 옵션이 있으면 즉석에서 파이프라인을 돌려
    요약을 만든다.
  - 요약을 짧은 메시지로 만들어 "나에게 보내기" 로 카카오톡 전송한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.test_kakao_notify
  .venv/bin/python -m scripts.test_kakao_notify --run-pipeline   # 요약 없으면 새로 생성
  .venv/bin/python -m scripts.test_kakao_notify --dry-run        # 전송 안 하고 메시지만 출력

사전: scripts/kakao_auth.py 로 최초 인증 완료 + .env 에 KAKAO_REFRESH_TOKEN 입력.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kakao_notify import KakaoError, format_summary_message, send_to_me  # noqa: E402
from src.report import load_summary  # noqa: E402


def _build_summary_via_pipeline() -> dict:
    from src.classifier import classify
    from src.gmail_auth import get_gmail_service
    from src.mail_fetcher import fetch_new_messages
    from src.report import (
        MailResult,
        build_report,
        save_report,
        save_summary,
        summarize,
    )
    from src.reply_drafter import assess_reply

    service = get_gmail_service()
    mails = fetch_new_messages(max_results=30, service=service)
    results: list[MailResult] = []
    for m in mails:
        c = classify(m)
        r = assess_reply(m, service=service) if c.category == "업무" else None
        results.append(MailResult(mail=m, classification=c, reply=r))

    today = date.today()
    save_report(build_report(results, report_date=today), report_date=today)
    save_summary(results, report_date=today)
    return summarize(results, report_date=today)


def main() -> int:
    parser = argparse.ArgumentParser(description="카카오톡 알림 테스트")
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="오늘 요약이 없으면 파이프라인을 돌려 새로 생성",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="전송하지 않고 메시지 내용만 출력"
    )
    args = parser.parse_args()

    try:
        summary = load_summary()
        print(f"오늘 리포트 요약을 찾았습니다: {summary['date']}")
    except FileNotFoundError:
        if not args.run_pipeline:
            print(
                "오늘 날짜의 리포트 요약이 없습니다.\n"
                "  - 먼저 `.venv/bin/python -m scripts.run_pipeline` 를 실행하거나\n"
                "  - 이 스크립트에 --run-pipeline 을 붙여 실행하세요."
            )
            return 1
        print("오늘 요약이 없어 파이프라인을 실행합니다...\n")
        summary = _build_summary_via_pipeline()

    message = format_summary_message(summary)
    print("\n--- 보낼 메시지 ---")
    print(message)
    print("------------------\n")

    if args.dry_run:
        print("(--dry-run: 전송하지 않았습니다.)")
        return 0

    try:
        send_to_me(message)
    except KakaoError as e:
        print(f"전송 실패: {e}")
        return 1

    print("카카오톡으로 전송했습니다. 휴대폰에서 확인해 보세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

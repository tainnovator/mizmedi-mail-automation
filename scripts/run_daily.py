"""
미즈메디병원 업무 메일 자동화 - 매일 실행되는 메인 파이프라인.

단계
  [1/5] 새 메일 가져오기        (실패 시 중단)
  [2/5] 분류 + 회신 초안 작성    (메일 단위 실패는 건너뛰고 계속)
  [3/5] 리포트 생성 (초안 포함)  (실패 시 알림·기록 건너뛰고 중단)
  [4/5] 카카오톡 알림 발송       (실패해도 계속)
  [5/5] 처리한 메일 ID 기록      (실패해도 계속)

각 단계 진행 상황과 실패 지점을 로그로 남긴다. 하나라도 실패하면 종료 코드 1.

이 자동화는 어떤 경우에도 메일을 자동 발송하지 않는다. 회신 초안은 리포트
문서 안에서만 제공되며, 최종 확인·전송은 사람이 직접 한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.run_daily
  .venv/bin/python -m scripts.run_daily --limit 50
  .venv/bin/python -m scripts.run_daily --no-notify   # 카카오 발송 생략
  .venv/bin/python -m scripts.run_daily --no-mark     # 처리 기록 생략 (재실행용)
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.classifier import Classification, classify  # noqa: E402
from src.config import LOG_LEVEL  # noqa: E402
from src.gmail_auth import get_gmail_service  # noqa: E402
from src.kakao_notify import format_summary_message, send_to_me  # noqa: E402
from src.mail_fetcher import fetch_new_messages, mark_processed  # noqa: E402
from src.reply_drafter import assess_reply  # noqa: E402
from src.report import (  # noqa: E402
    MailResult,
    build_report,
    save_report,
    save_summary,
    summarize,
)

log = logging.getLogger("run_daily")


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # 서드파티 라이브러리의 잡음 로그는 경고 이상만 표시 (파이프라인 로그 가독성)
    for noisy in ("httpx", "httpcore", "anthropic", "googleapiclient", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _log_exc(prefix: str, exc: Exception) -> None:
    log.error("%s: %s: %s", prefix, type(exc).__name__, exc)
    log.debug("%s", traceback.format_exc())


def main() -> int:
    parser = argparse.ArgumentParser(description="메일 자동화 매일 파이프라인")
    parser.add_argument("--limit", type=int, default=50, help="가져올 최대 메일 수")
    parser.add_argument("--no-notify", action="store_true", help="카카오 알림 발송 생략")
    parser.add_argument("--no-mark", action="store_true", help="처리한 메일 ID 기록 생략")
    args = parser.parse_args()

    _setup_logging()
    today = date.today()
    failures: list[str] = []

    log.info("=== 메일 자동화 파이프라인 시작 (%s) ===", today.isoformat())

    # ------------------------------------------------------------------ [1/5]
    log.info("[1/5] 새 메일 가져오기")
    try:
        service = get_gmail_service()
        mails = fetch_new_messages(max_results=args.limit, service=service)
    except Exception as e:  # noqa: BLE001
        _log_exc("[1/5] 실패", e)
        log.error("메일을 가져오지 못해 파이프라인을 중단합니다.")
        return 1
    log.info("[1/5] 완료 — 새 메일 %d건", len(mails))

    if not mails:
        log.info("[2/5]~[3/5] 새 메일이 없어 분류·리포트를 건너뜁니다.")
        if args.no_notify:
            log.info("[4/5] 카카오 알림 건너뜀 (--no-notify)")
        else:
            log.info("[4/5] 카카오 알림 발송 (새 메일 없음)")
            try:
                send_to_me(f"📮 미즈메디 메일 리포트 ({today.isoformat()})\n오늘 새 메일이 없습니다.")
                log.info("[4/5] 완료 — 전송 성공")
            except Exception as e:  # noqa: BLE001
                _log_exc("[4/5] 실패", e)
                log.warning("=== 파이프라인 종료 — 카카오 알림 실패 ===")
                return 1
        log.info("[5/5] 기록할 새 메일 없음")
        log.info("=== 파이프라인 정상 완료 (처리할 메일 없음) ===")
        return 0

    # ------------------------------------------------------------------ [2/5]
    log.info("[2/5] 분류 + 회신 초안")
    results: list[MailResult] = []
    for m in mails:
        try:
            c = classify(m)
        except Exception as e:  # noqa: BLE001
            log.warning("  분류 실패 '%s' — '기타'로 처리: %s", m.subject[:30], e)
            c = Classification("기타", f"분류 예외: {type(e).__name__}", "error")

        r = None
        if c.category == "업무":
            try:
                r = assess_reply(m, service=service)
            except Exception as e:  # noqa: BLE001
                log.warning("  회신 판단 실패 '%s': %s", m.subject[:30], e)

        results.append(MailResult(mail=m, classification=c, reply=r))
        note = ""
        if r is not None:
            note = " [회신 필요]" if r.needs_reply else " [회신 불필요]"
        log.info("  %-4s | %s%s", c.category, m.subject[:44], note)

    tally = Counter(r.classification.category for r in results)
    log.info(
        "[2/5] 완료 — 업무 %d / 광고성 %d / 스팸 %d / 기타 %d",
        tally.get("업무", 0),
        tally.get("광고성", 0),
        tally.get("스팸", 0),
        tally.get("기타", 0),
    )

    # ------------------------------------------------------------------ [3/5]
    log.info("[3/5] 리포트 생성")
    try:
        report_path = save_report(build_report(results, report_date=today), report_date=today)
        save_summary(results, report_date=today)
        summary = summarize(results, report_date=today)
    except Exception as e:  # noqa: BLE001
        _log_exc("[3/5] 실패", e)
        log.error("리포트를 생성하지 못했습니다. 알림·기록을 건너뛰고 중단합니다.")
        return 1
    log.info(
        "[3/5] 완료 — %s (회신 초안 %d건)", report_path, summary["reply_drafts"]
    )

    # ------------------------------------------------------------------ [4/5]
    if args.no_notify:
        log.info("[4/5] 카카오 알림 건너뜀 (--no-notify)")
    else:
        log.info("[4/5] 카카오 알림 발송")
        try:
            send_to_me(format_summary_message(summary))
            log.info("[4/5] 완료 — 전송 성공")
        except Exception as e:  # noqa: BLE001
            failures.append("카카오 알림")
            _log_exc("[4/5] 실패", e)

    # ------------------------------------------------------------------ [5/5]
    if args.no_mark:
        log.info("[5/5] 처리 기록 건너뜀 (--no-mark)")
    elif not results:
        log.info("[5/5] 기록할 새 메일 없음")
    else:
        log.info("[5/5] 처리한 메일 ID 기록")
        try:
            mark_processed([r.mail.id for r in results])
            log.info("[5/5] 완료 — %d건 기록 (data/processed_ids.json)", len(results))
        except Exception as e:  # noqa: BLE001
            failures.append("처리 기록")
            _log_exc("[5/5] 실패", e)

    # ------------------------------------------------------------------ 종료
    if failures:
        log.warning(
            "=== 파이프라인 종료 — 실패 단계: %s (리포트는 생성됨: %s) ===",
            ", ".join(failures),
            report_path,
        )
        return 1
    log.info("=== 파이프라인 정상 완료 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

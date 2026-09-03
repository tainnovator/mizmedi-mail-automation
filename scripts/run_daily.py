"""
미즈메디병원 업무 메일 자동화 - 메인 파이프라인.

스케줄러(launchd)가 **오전 8시~오후 5시 매 정시**에 이 스크립트를 실행한다.
"체크"와 "알림"을 분리한다.

  [체크]  (매 정시, 알림 없음)
    - 새 메일 가져오기 → 분류 (+ 업무 핵심 요약) → 회신 판단
    - 회신 초안이 필요하면:
        · 먼저 스레드에 "수신 이후 내가 보낸 메시지"가 있는지 확인 →
          있으면 "이미 직접 회신함"으로 보고 초안 생략
        · 없으면 초안 텍스트 생성 + Gmail 임시보관함에 실제 초안 생성 (발송 아님)
    - 처리 결과를 data/processed_ids.json 에 notified=False 로 기록
    - 리포트(.md + summary.json)를 그날 처리분 누적으로 재생성

  [알림]  (NOTIFY_HOURS = 09/13/17시)
    - "지난 알림 슬롯 이후 아직 안 보낸 항목"을 모두 모아 카카오 1회 발송
    - 발송한 항목을 notified=True 로 갱신
    - 알림 슬롯을 놓쳐도(네트워크 장애 등) 다음 실행이 "지난 슬롯 이후
      미전송분"을 자동으로 따라잡는다 → 별도 재시도 로직 불필요
    - 보낼 게 없으면 조용히 넘어간다

last_success.json 기반 "오늘 이미 성공 → 스킵" 로직은 없다. 매 정시마다 항상
새 메일을 확인한다.

이 자동화는 어떤 경우에도 메일을 자동 발송하지 않는다. 회신 초안은 Gmail
임시보관함과 리포트 문서에만 저장되며, 최종 확인·전송은 사람이 직접 한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.run_daily
  .venv/bin/python -m scripts.run_daily --limit 50
  .venv/bin/python -m scripts.run_daily --notify      # 슬롯과 무관하게 알림 강제
  .venv/bin/python -m scripts.run_daily --no-notify    # 알림 전부 생략
  .venv/bin/python -m scripts.run_daily --no-mark      # 기록·초안·알림 전부 생략
                                                       #  (부작용 없는 테스트 실행)
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections import Counter
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import processed_log  # noqa: E402
from src.classifier import Classification, classify  # noqa: E402
from src.config import LOG_LEVEL, NOTIFY_HOURS  # noqa: E402
from src.gmail_auth import get_gmail_service  # noqa: E402
from src.kakao_notify import format_pending_notification, send_to_me  # noqa: E402
from src.mail_fetcher import fetch_new_messages  # noqa: E402
from src.reply_drafter import assess_reply  # noqa: E402
from src.report import (  # noqa: E402
    MailResult,
    build_report,
    results_from_entries,
    save_report,
    save_summary,
)

log = logging.getLogger("run_daily")


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "anthropic", "googleapiclient", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _log_exc(prefix: str, exc: Exception) -> None:
    log.error("%s: %s: %s", prefix, type(exc).__name__, exc)
    log.debug("%s", traceback.format_exc())


class CheckFailed(Exception):
    """체크 단계 실패. message 에 어느 부분인지 담는다."""


# ---------------------------------------------------------------------------
# 체크
# ---------------------------------------------------------------------------
def _run_check(args, today: date_cls) -> list[MailResult]:
    """새 메일을 가져와 분류 + 회신 판단/초안까지. 치명적 실패 시 CheckFailed."""
    log.info("[체크] 새 메일 가져오기")
    try:
        service = get_gmail_service()
        mails = fetch_new_messages(max_results=args.limit, service=service)
    except Exception as e:  # noqa: BLE001
        _log_exc("[체크] 메일 가져오기 실패", e)
        raise CheckFailed("메일 가져오기") from e
    log.info("[체크] 새 메일 %d건", len(mails))
    if not mails:
        return []

    results: list[MailResult] = []
    for m in mails:
        try:
            c = classify(m)
        except Exception as e:  # noqa: BLE001 - 메일 1건 실패는 전체를 막지 않음
            log.warning("  분류 실패 '%s' — '기타'로 처리: %s", m.subject[:30], e)
            c = Classification("기타", f"분류 예외: {type(e).__name__}", "error")

        r = None
        if c.category == "업무":
            try:
                r = assess_reply(
                    m, service=service, make_gmail_draft=not args.no_mark
                )
            except Exception as e:  # noqa: BLE001
                log.warning("  회신 판단 실패 '%s': %s", m.subject[:30], e)

        results.append(MailResult(mail=m, classification=c, reply=r))
        log.info("  %-4s | %s%s", c.category, m.subject[:44], _status_note(r))

    tally = Counter(r.classification.category for r in results)
    drafted = sum(1 for r in results if r.reply and r.reply.draft_created)
    replied = sum(1 for r in results if r.reply and r.reply.already_replied)
    failed = sum(1 for r in results if r.reply and r.reply.draft and r.reply.draft_error)
    log.info(
        "[체크] 분류: 업무 %d / 광고성 %d / 스팸 %d / 기타 %d "
        "— 초안 생성 %d / 이미 답장 %d / 초안 실패 %d",
        tally.get("업무", 0),
        tally.get("광고성", 0),
        tally.get("스팸", 0),
        tally.get("기타", 0),
        drafted,
        replied,
        failed,
    )
    return results


def _status_note(r) -> str:
    if r is None:
        return ""
    if r.already_replied:
        return " [이미 직접 회신 → 초안 생략]"
    if r.draft_created:
        return f" [회신 필요 → 임시보관함 초안 {r.draft_id}]"
    if r.draft and r.draft_error:
        return f" [회신 필요 → 초안 생성 실패: {r.draft_error}]"
    if r.needs_reply:
        return " [회신 필요]"
    return " [회신 불필요]"


def _entry(r: MailResult, today: date_cls) -> dict:
    m, c, rep = r.mail, r.classification, r.reply
    e = {
        "id": m.id,
        "date": today.isoformat(),  # 처리한 날 (리포트 누적 기준)
        "thread_id": m.thread_id,
        "sender": m.sender,
        "subject": m.subject,
        "received_at": m.received_at.isoformat(),
        "category": c.category,
        "classify_reason": c.reason,
        "classify_method": c.method,
        "summary": c.summary,
    }
    if rep is not None:
        e.update(
            {
                "needs_reply": rep.needs_reply,
                "reply_status": rep.reply_status,
                "reply_reason": rep.reason,
                "reply_method": rep.method,
                "draft_id": rep.draft_id,
                "draft_text": rep.draft,
                "draft_error": rep.draft_error,
            }
        )
    else:
        e["reply_status"] = "not_applicable"
    return e


# ---------------------------------------------------------------------------
# 알림 슬롯 판정 (슬롯 추적 방식)
# ---------------------------------------------------------------------------
def _due_notify_slot(now: datetime, last_notified: datetime | None) -> datetime | None:
    """지금 시점 기준, '아직 알림 안 보낸 가장 최근 지난 슬롯'. 없으면 None."""
    passed = [
        now.replace(hour=h, minute=0, second=0, microsecond=0)
        for h in sorted(NOTIFY_HOURS)
        if now.replace(hour=h, minute=0, second=0, microsecond=0) <= now
    ]
    if not passed:
        return None
    most_recent = passed[-1]
    if last_notified is not None and last_notified >= most_recent:
        return None
    return most_recent


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="메일 자동화 메인 파이프라인")
    parser.add_argument("--limit", type=int, default=50, help="가져올 최대 메일 수")
    parser.add_argument("--notify", action="store_true", help="알림 슬롯과 무관하게 알림 강제")
    parser.add_argument("--no-notify", action="store_true", help="카카오 알림 전부 생략")
    parser.add_argument(
        "--no-mark",
        action="store_true",
        help="기록·초안·알림 전부 생략 (부작용 없는 테스트 실행)",
    )
    args = parser.parse_args()

    _setup_logging()
    now = datetime.now()
    today = now.date()
    test_mode = args.no_mark

    log.info("=== 파이프라인 시작 (%s %02d시) ===", today.isoformat(), now.hour)

    # ---- 체크 (항상) ------------------------------------------------------
    check_ok = True
    try:
        results = _run_check(args, today)
    except CheckFailed as e:
        check_ok = False
        results = []
        log.error("체크 실패 — 지점: %s (알림 단계는 계속 진행)", e)

    if not test_mode and results:
        try:
            processed_log.record([_entry(r, today) for r in results])
            log.info("[기록] %d건 저장 (notified=False)", len(results))
        except Exception as e:  # noqa: BLE001
            _log_exc("[기록] 실패", e)

    # ---- 리포트 재생성 (그날 누적) --------------------------------------
    if not test_mode:
        try:
            entries = processed_log.todays_entries(today)
            rs = results_from_entries(entries)
            path = save_report(build_report(rs, report_date=today), report_date=today)
            save_summary(rs, report_date=today)
            log.info("[리포트] 갱신 — 오늘 누적 %d건 (%s)", len(rs), path)
        except Exception as e:  # noqa: BLE001
            _log_exc("[리포트] 갱신 실패", e)

    # ---- 알림 (슬롯 도래 시, 체크 성패와 무관) --------------------------
    notify_ok = True
    should_notify = not test_mode and not args.no_notify and (
        args.notify or _due_notify_slot(now, processed_log.get_last_notified_at()) is not None
    )
    if should_notify:
        pending = processed_log.pending_notification()
        if pending:
            try:
                send_to_me(format_pending_notification(pending))
                processed_log.mark_notified([p["id"] for p in pending])
                log.info("[알림] 미전송 %d건 카카오 발송 완료", len(pending))
            except Exception as e:  # noqa: BLE001
                notify_ok = False
                _log_exc("[알림] 발송 실패 (다음 실행이 재시도)", e)
        else:
            log.info("[알림] 슬롯 도래했으나 미전송분 없음 — 조용히 넘어감")
    elif not test_mode and not args.no_notify:
        log.info("[알림] 지금은 알림 대상 아님 (슬롯 미도래 또는 이미 발송) — 체크만 수행")

    # ---- 종료 ----------------------------------------------------------
    if not check_ok or not notify_ok:
        log.warning("=== 파이프라인 종료 (일부 실패: 체크=%s 알림=%s) ===", check_ok, notify_ok)
        return 1
    log.info("=== 파이프라인 정상 완료 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

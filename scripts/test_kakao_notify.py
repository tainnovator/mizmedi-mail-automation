"""
카카오톡 알림 단독 테스트.

현재 processed_ids.json 에서 아직 알림에 포함되지 않은 항목
(processed_log.pending_notification())을 모아 카카오 메시지로 만들어 보고,
원하면 실제로 "나에게 보내기" 로 전송한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.test_kakao_notify --dry-run   # 메시지만 출력
  .venv/bin/python -m scripts.test_kakao_notify             # 실제 전송
  .venv/bin/python -m scripts.test_kakao_notify --run-check --dry-run
        # 먼저 매시간 체크를 1회 수행(새 메일 반영)한 뒤 미전송분을 미리보기

--dry-run 이 아니면 전송 후 해당 항목들을 notified=True 로 갱신한다.

사전: scripts/kakao_auth.py 로 최초 인증 완료 + .env 에 KAKAO_REFRESH_TOKEN 입력.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import processed_log  # noqa: E402
from src.kakao_notify import (  # noqa: E402
    KakaoError,
    format_pending_notification,
    send_to_me,
)


def _run_check_once() -> None:
    """run_daily 의 체크 단계만 1회 수행 (알림·슬롯 판정 없음)."""
    import argparse as _a
    from datetime import date

    from scripts.run_daily import _entry, _run_check

    ns = _a.Namespace(limit=50, no_mark=False, no_notify=True, notify=False)
    today = date.today()
    results = _run_check(ns, today)
    if results:
        processed_log.record([_entry(r, today) for r in results])
    print(f"체크 완료 — 새로 처리 {len(results)}건\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="카카오톡 알림 테스트")
    parser.add_argument(
        "--run-check", action="store_true", help="먼저 체크를 1회 수행"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="전송하지 않고 메시지만 출력"
    )
    args = parser.parse_args()

    if args.run_check:
        _run_check_once()

    pending = processed_log.pending_notification()
    if not pending:
        print("미전송 항목이 없습니다. (--run-check 로 새 메일을 먼저 반영해 보세요)")
        return 0

    message = format_pending_notification(pending)
    print(f"--- 미전송 {len(pending)}건 → 보낼 메시지 ({len(message)}자) ---")
    print(message)
    print("-" * 40)

    if args.dry_run:
        print("\n(--dry-run: 전송하지 않았습니다.)")
        return 0

    try:
        send_to_me(message)
    except KakaoError as e:
        print(f"\n전송 실패: {e}")
        return 1

    processed_log.mark_notified([p["id"] for p in pending])
    print(f"\n전송 완료. {len(pending)}건을 notified=True 로 갱신했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

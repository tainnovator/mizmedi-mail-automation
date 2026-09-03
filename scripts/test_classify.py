"""
메일 가져오기 + 분류 테스트 스크립트.

하는 일:
  1. 받은편지함에서 아직 처리하지 않은 새 메일을 가져온다.
  2. 각 메일을 업무 / 광고성 / 스팸 / 기타 로 분류한다 (규칙 -> LLM).
  3. 발신자 / 제목 / 분류 / 방식 / 이유 를 표로 출력한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.test_classify
  .venv/bin/python -m scripts.test_classify --limit 10
  .venv/bin/python -m scripts.test_classify --mark-processed   # 처리 완료로 기록

--mark-processed 를 주지 않으면 처리 기록(data/processed_ids.json)은 건드리지 않는다.
따라서 여러 번 돌려도 같은 메일이 계속 나온다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.classifier import classify  # noqa: E402
from src.mail_fetcher import fetch_new_messages  # noqa: E402
from src.processed_log import mark_processed  # noqa: E402


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_row(cols: list[str], widths: list[int]) -> None:
    cells = []
    for value, w in zip(cols, widths):
        # 한글 폭 보정: 대략 한글 1자 = 2칸으로 계산
        pad = w - sum(2 if ord(ch) > 0x2E7F else 1 for ch in value)
        cells.append(value + " " * max(pad, 0))
    print(" | ".join(cells))


def main() -> int:
    parser = argparse.ArgumentParser(description="메일 가져오기 + 분류 테스트")
    parser.add_argument("--limit", type=int, default=20, help="가져올 최대 메일 수")
    parser.add_argument(
        "--mark-processed",
        action="store_true",
        help="분류한 메일을 처리 완료로 기록 (다음 실행부터 제외)",
    )
    args = parser.parse_args()

    print("새 메일을 가져오는 중...\n")
    mails = fetch_new_messages(max_results=args.limit)

    if not mails:
        print("처리할 새 메일이 없습니다.")
        return 0

    widths = [22, 34, 8, 10, 46]
    headers = ["발신자", "제목", "분류", "방식", "이유"]
    _print_row(headers, widths)
    print("-" * (sum(widths) + 3 * (len(widths) - 1)))

    counter: Counter[str] = Counter()
    processed_ids: list[str] = []

    for mail in mails:
        result = classify(mail)
        counter[result.category] += 1
        processed_ids.append(mail.id)
        _print_row(
            [
                _clip(mail.sender, 22),
                _clip(mail.subject, 34),
                _clip(result.category, 8),
                _clip(result.method, 10),
                _clip(result.reason, 46),
            ],
            widths,
        )

    print("\n분류 요약:")
    for category in ("업무", "광고성", "스팸", "기타"):
        print(f"  - {category}: {counter.get(category, 0)}건")
    print(f"  합계: {len(mails)}건")

    if args.mark_processed:
        mark_processed(processed_ids)
        print(f"\n{len(processed_ids)}건을 처리 완료로 기록했습니다 (data/processed_ids.json).")
    else:
        print("\n(처리 기록은 저장하지 않았습니다. --mark-processed 로 저장 가능)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
첨부파일 자동 감지 + 다운로드 — 독립 실행 스크립트.

run_daily.py 의 매시간 자동 스케줄과 별개로, 지금 당장 새 메일의 첨부파일을
확인해서 다운로드할 때 쓴다. 시연 때 "메일 발송 → 이 스크립트 실행 → 다운로드
폴더에 파일 생성"을 그 자리에서 보여줄 수 있다.

동작:
  1. config/attachment_rules.json 규칙을 읽는다.
  2. 첨부파일이 있는 최근 메일을 가져와 규칙과 대조한다
     (발신자 이메일 + 제목 키워드 둘 다 맞으면 확정, 하나만 맞으면 미확인).
  3. 확정 매칭된 메일의 첨부파일 중 pdf/xlsx/xls/doc/docx 만, 아직 저장 안 한
     것만 다운로드 폴더에 저장한다.

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.check_attachments
  .venv/bin/python -m scripts.check_attachments --dry-run   # 저장 없이 매칭 결과만 확인
  .venv/bin/python -m scripts.check_attachments --limit 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.attachment_downloader import check_and_download_attachments  # noqa: E402

_STATUS_LABEL = {
    "downloaded": "다운로드",
    "duplicate": "중복(스킵)",
    "unmatched_ext": "형식 제외",
    "partial": "미확인",
}


def _clip(text: str, width: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_row(cols: list[str], widths: list[int]) -> None:
    cells = []
    for value, w in zip(cols, widths):
        # 한글 폭 보정: 대략 한글 1자 = 2칸으로 계산
        pad = w - sum(2 if ord(ch) > 0x2E7F else 1 for ch in value)
        cells.append(value + " " * max(pad, 0))
    print(" | ".join(cells))


def main() -> int:
    parser = argparse.ArgumentParser(description="첨부파일 자동 감지 + 다운로드")
    parser.add_argument("--limit", type=int, default=50, help="확인할 최대 메일 수")
    parser.add_argument(
        "--dry-run", action="store_true", help="실제 저장 없이 매칭 결과만 출력"
    )
    args = parser.parse_args()

    print("첨부파일 대상 메일을 확인하는 중...\n")
    result = check_and_download_attachments(max_results=args.limit, dry_run=args.dry_run)

    if result.checked == 0:
        print("확인 대상 메일이 없습니다 (최근 첨부파일 있는 메일 없음).")
        return 0

    shown = [o for o in result.outcomes if o.status != "none"]

    if shown:
        widths = [22, 34, 12, 30]
        _print_row(["발신자", "제목", "결과", "비고"], widths)
        print("-" * (sum(widths) + 3 * (len(widths) - 1)))
        for o in shown:
            detail = o.detail or o.filename or ""
            _print_row(
                [
                    _clip(o.mail.sender, 22),
                    _clip(o.mail.subject, 34),
                    _clip(_STATUS_LABEL.get(o.status, o.status), 12),
                    _clip(detail, 30),
                ],
                widths,
            )
        print()

    print("요약:")
    print(f"  확인 {result.checked}건 · 다운로드 {result.downloaded}건 · 미확인 {result.partial}건")
    if args.dry_run:
        print("  (--dry-run: 실제로 저장하지 않았습니다)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

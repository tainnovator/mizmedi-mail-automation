"""
처리한 메일의 상태 기록 (data/processed_ids.json).

스키마
  {
    "updated_at": "<ISO>",
    "last_notified_at": "<ISO 또는 null>",   # 마지막으로 카카오 알림을 보낸 시각
    "processed": {
      "<gmail msg id>": {
        "processed_at": "<ISO>",
        "date": "2026-09-02",             # 수신일(로컬) — 리포트 누적용
        "sender": "...", "subject": "...", "received_at": "2026-09-02 07:45",
        "category": "업무|광고성|스팸|기타",
        "classify_reason": "...", "classify_method": "llm",
        "summary": "핵심 요약 (업무만, 없으면 null)",
        "needs_reply": true,
        "reply_status": "draft_created|draft_failed|already_replied"
                        "|no_reply_needed|not_applicable|skipped",
        "reply_reason": "...", "reply_method": "llm",
        "draft_id": "...", "draft_text": "...", "draft_error": null,
        "notified": false                 # 카카오 알림에 포함됐는가
      },
      ...
    }
  }

- 매시간 체크: 새 메일을 record() 로 넣는다 (notified=False).
- 알림 슬롯(9/13/17시): pending_notification() 으로 notified=False 를 모아
  한 번에 발송하고 mark_notified() 로 True 로 바꾼다.
- 구버전 포맷 {"processed_ids": [...]} 는 자동 마이그레이션한다 (모두 notified=True).
"""

from __future__ import annotations

import json
from datetime import date as date_cls
from datetime import datetime, timedelta

from .config import PROCESSED_IDS_PATH, PROCESSED_RETENTION_DAYS

# record() 가 항목별로 받는 dict 의 키 (id 제외). 리포트/알림 재구성에 필요한 값들.
ENTRY_FIELDS = (
    "date",
    "thread_id",
    "sender",
    "subject",
    "received_at",
    "category",
    "classify_reason",
    "classify_method",
    "summary",
    "needs_reply",
    "reply_status",
    "reply_reason",
    "reply_method",
    "draft_id",
    "draft_text",
    "draft_error",
)
# 오래된 항목에서 남길 키 (나머지 큰 필드는 프루닝).
_KEEP_ON_PRUNE = ("date", "category", "notified", "processed_at")

_NOW = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731


# ---------------------------------------------------------------------------
# 로드 / 저장
# ---------------------------------------------------------------------------
def _load() -> dict:
    if not PROCESSED_IDS_PATH.exists():
        return {"updated_at": None, "last_notified_at": None, "processed": {}}
    try:
        raw = json.loads(PROCESSED_IDS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"updated_at": None, "last_notified_at": None, "processed": {}}

    # 구버전: {"processed_ids": ["id1", ...]} → 전부 notified=True 로 흡수
    if "processed_ids" in raw and "processed" not in raw:
        migrated = {
            mid: {"notified": True, "migrated": True} for mid in raw["processed_ids"]
        }
        return {
            "updated_at": raw.get("updated_at"),
            "last_notified_at": None,
            "processed": migrated,
        }

    raw.setdefault("processed", {})
    raw.setdefault("last_notified_at", None)
    raw.setdefault("updated_at", None)
    return raw


def _prune(processed: dict) -> None:
    cutoff = (date_cls.today() - timedelta(days=PROCESSED_RETENTION_DAYS)).isoformat()
    for mid, entry in list(processed.items()):
        entry_date = entry.get("date") or ""
        if entry_date and entry_date < cutoff:
            slim = {k: entry[k] for k in _KEEP_ON_PRUNE if k in entry}
            slim["notified"] = True  # 너무 오래돼서 더는 알림 대상 아님
            processed[mid] = slim


def _save(doc: dict) -> None:
    _prune(doc["processed"])
    doc["updated_at"] = _NOW()
    PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_IDS_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------
def processed_ids() -> set[str]:
    """이미 처리한 메일 id 집합 (fetch_new_messages 의 중복 방지에 사용)."""
    return set(_load()["processed"].keys())


def record(entries: list[dict]) -> None:
    """
    새로 처리한 메일들을 기록한다. 각 entry 는 최소 {"id": ...} 를 갖고,
    ENTRY_FIELDS 의 값들을 선택적으로 담는다.
    - 신규 id: notified=False 로 추가.
    - 기존 id: 필드만 갱신하고 notified 는 유지 (되돌리지 않음).
    """
    if not entries:
        return
    doc = _load()
    processed = doc["processed"]
    for entry in entries:
        mid = entry["id"]
        cur = processed.get(mid, {})
        merged = dict(cur)
        merged.setdefault("processed_at", _NOW())
        for key in ENTRY_FIELDS:
            if key in entry:
                merged[key] = entry[key]
        merged["notified"] = bool(cur.get("notified", False))
        processed[mid] = merged
    _save(doc)


def mark_processed(ids: list[str] | set[str]) -> None:
    """개발용 스크립트(run_pipeline, test_classify) 호환. id 만 최소 기록."""
    if not ids:
        return
    doc = _load()
    today = date_cls.today().isoformat()
    for i in ids:
        entry = doc["processed"].setdefault(i, {})
        entry.setdefault("processed_at", _NOW())
        entry.setdefault("date", today)
        entry["notified"] = True
    _save(doc)


def pending_notification() -> list[dict]:
    """
    아직 알림에 포함되지 않은 항목들 (id 포함). 정렬:
      1) 회신 초안 준비/실패  2) 이미 답장 완료  3) 그 외
      각 그룹 내에서는 최근 수신 먼저.
    """
    order = {"draft_created": 0, "draft_failed": 0, "already_replied": 1}
    items = [
        {**entry, "id": mid}
        for mid, entry in _load()["processed"].items()
        if not entry.get("notified", False)
    ]
    # 안정 정렬 2단계: 먼저 최근 수신 먼저, 그다음 그룹 순서 (그룹 내 순서 유지)
    items.sort(key=lambda e: e.get("received_at") or "", reverse=True)
    items.sort(key=lambda e: order.get(e.get("reply_status"), 2))
    return items


def mark_notified(ids: list[str]) -> None:
    if not ids:
        return
    doc = _load()
    for mid in ids:
        if mid in doc["processed"]:
            doc["processed"][mid]["notified"] = True
    doc["last_notified_at"] = _NOW()
    _save(doc)


def get_last_notified_at() -> datetime | None:
    raw = _load().get("last_notified_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def todays_entries(day: date_cls | None = None) -> list[dict]:
    """해당 날짜(수신일 기준)에 처리된 항목들 (id 포함). 리포트 누적용."""
    day = day or date_cls.today()
    key = day.isoformat()
    return [
        {**entry, "id": mid}
        for mid, entry in _load()["processed"].items()
        if entry.get("date") == key
    ]

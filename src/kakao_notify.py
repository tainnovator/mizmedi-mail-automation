"""
카카오톡 "나에게 보내기" 알림.

토큰 관리
  - 최초 access/refresh 토큰은 scripts/kakao_auth.py 로 발급한다.
  - 발급된 토큰은 credentials/kakao_token.json 에 캐시된다 (git 제외).
  - refresh token 은 .env 의 KAKAO_REFRESH_TOKEN 에도 붙여넣어 두면,
    캐시 파일이 없을 때 그 값으로 부트스트랩한다.
  - access token 이 만료되면 refresh token 으로 자동 갱신하고 캐시를 갱신한다.
  - 카카오가 새 refresh token 을 함께 주는 경우(기존 것 만료 임박 시)
    캐시에 저장하고, .env 값과 다르면 "직접 교체하라"는 안내를 출력한다.

전송 내용
  - 리포트 요약(전체 건수, 카테고리별 건수, 회신 초안 건수)을 짧게 담는다.
  - 메일 자동 발송과는 무관하다. 이건 사람에게 보내는 알림일 뿐이다.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime

import requests

from .config import (
    KAKAO_CLIENT_SECRET,
    KAKAO_REDIRECT_URI,
    KAKAO_REFRESH_TOKEN,
    KAKAO_REST_API_KEY,
    KAKAO_TOKEN_PATH,
)

AUTH_HOST = "https://kauth.kakao.com"
API_HOST = "https://kapi.kakao.com"
TOKEN_URL = f"{AUTH_HOST}/oauth/token"
AUTHORIZE_URL = f"{AUTH_HOST}/oauth/authorize"
SEND_TO_ME_URL = f"{API_HOST}/v2/api/talk/memo/default/send"
SCOPE = "talk_message"


class KakaoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 토큰 캐시
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    if KAKAO_TOKEN_PATH.exists():
        try:
            return json.loads(KAKAO_TOKEN_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _with_client_secret(payload: dict) -> dict:
    """콘솔에서 client_secret 을 켠 경우 토큰 요청에 함께 실어야 한다 (KOE010 방지)."""
    if KAKAO_CLIENT_SECRET:
        payload["client_secret"] = KAKAO_CLIENT_SECRET
    return payload


def _save_cache(data: dict) -> None:
    KAKAO_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    KAKAO_TOKEN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _store_token_response(resp: dict, previous: dict) -> dict:
    """토큰 응답을 캐시 형태로 정규화해서 저장한다."""
    now = int(time.time())
    new_refresh = resp.get("refresh_token")
    data = {
        "access_token": resp["access_token"],
        "access_token_expires_at": now + int(resp.get("expires_in", 0)) - 60,
        "refresh_token": new_refresh or previous.get("refresh_token") or KAKAO_REFRESH_TOKEN,
        "obtained_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_cache(data)

    if new_refresh and new_refresh != KAKAO_REFRESH_TOKEN:
        print(
            "\n[안내] 카카오가 새 refresh token 을 발급했습니다.\n"
            "       .env 의 KAKAO_REFRESH_TOKEN 값을 아래로 교체해 주세요 "
            "(자동으로 덮어쓰지 않습니다):\n"
            f"       KAKAO_REFRESH_TOKEN={new_refresh}\n"
        )
    return data


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------
def build_authorize_url() -> str:
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": KAKAO_REST_API_KEY,
            "redirect_uri": KAKAO_REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
        }
    )
    return f"{AUTHORIZE_URL}?{q}"


def exchange_code_for_tokens(code: str) -> dict:
    """authorization code → access/refresh 토큰. scripts/kakao_auth.py 에서 사용."""
    resp = requests.post(
        TOKEN_URL,
        data=_with_client_secret(
            {
                "grant_type": "authorization_code",
                "client_id": KAKAO_REST_API_KEY,
                "redirect_uri": KAKAO_REDIRECT_URI,
                "code": code,
            }
        ),
        timeout=10,
    )
    if resp.status_code != 200:
        raise KakaoError(f"토큰 발급 실패 ({resp.status_code}): {resp.text}")
    return _store_token_response(resp.json(), _load_cache())


def _refresh_access_token(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data=_with_client_secret(
            {
                "grant_type": "refresh_token",
                "client_id": KAKAO_REST_API_KEY,
                "refresh_token": refresh_token,
            }
        ),
        timeout=10,
    )
    if resp.status_code != 200:
        raise KakaoError(
            f"access token 갱신 실패 ({resp.status_code}): {resp.text}\n"
            "refresh token 이 만료되었을 수 있습니다. "
            "scripts/kakao_auth.py 로 다시 로그인해 주세요."
        )
    return _store_token_response(resp.json(), _load_cache())


def _current_refresh_token() -> str:
    cache = _load_cache()
    token = cache.get("refresh_token") or KAKAO_REFRESH_TOKEN
    if not token:
        raise KakaoError(
            "저장된 refresh token 이 없습니다. 먼저 scripts/kakao_auth.py 를 실행해 "
            "로그인 인증을 완료하고, KAKAO_REFRESH_TOKEN 을 .env 에 넣어 주세요."
        )
    return token


def get_access_token(force_refresh: bool = False) -> str:
    """유효한 access token 을 반환한다. 만료됐으면 refresh token 으로 갱신."""
    if not KAKAO_REST_API_KEY:
        raise KakaoError("KAKAO_REST_API_KEY 가 .env 에 설정되어 있지 않습니다.")

    cache = _load_cache()
    if (
        not force_refresh
        and cache.get("access_token")
        and cache.get("access_token_expires_at", 0) > int(time.time())
    ):
        return cache["access_token"]

    return _refresh_access_token(_current_refresh_token())["access_token"]


# ---------------------------------------------------------------------------
# 나에게 보내기
# ---------------------------------------------------------------------------
def send_to_me(text: str, link_url: str = "https://mail.google.com/") -> None:
    """텍스트 메시지를 내 카카오톡으로 보낸다. 401 이면 한 번 토큰 갱신 후 재시도."""
    if len(text) > 200:
        text = text[:197] + "..."

    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }

    for attempt in range(2):
        token = get_access_token(force_refresh=(attempt == 1))
        resp = requests.post(
            SEND_TO_ME_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=10,
        )
        if resp.status_code == 200:
            return
        if resp.status_code == 401 and attempt == 0:
            continue  # 토큰 만료 → 강제 갱신 후 재시도
        raise KakaoError(f"카카오 메시지 전송 실패 ({resp.status_code}): {resp.text}")


# ---------------------------------------------------------------------------
# 리포트 요약 → 메시지 텍스트
# ---------------------------------------------------------------------------
# 카카오 텍스트 템플릿의 text 필드 최대 길이(200자)에 맞춰 자른다.
KAKAO_TEXT_LIMIT = 200
# 한 줄(발신자 - 요약)의 최대 길이. 실제 표시 건수는 200자 예산이 결정한다.
WORK_LINE_MAX = 58


def _short_sender(sender: str) -> str:
    """'"김미진" <a@b.com>' → '김미진', 'a@b.com' → 'a'."""
    s = (sender or "").strip()
    if '"' in s:
        inside = s.split('"')[1].strip()
        if inside:
            return inside
    if "<" in s:
        name = s.split("<")[0].strip().strip('"').strip()
        if name:
            return name
    if "@" in s:
        return s.split("@")[0].strip("<").strip()
    return s or "(발신자 미상)"


def _work_line(item: dict) -> str:
    sender = _short_sender(item.get("sender", ""))
    body = (item.get("summary") or item.get("subject") or "").strip()
    body = " ".join(body.split())
    line = f"· {sender} - {body}" if body else f"· {sender}"
    if len(line) > WORK_LINE_MAX:
        line = line[: WORK_LINE_MAX - 1] + "…"
    return line


def _pack_section(
    msg: str, title: str, lines: list[str], limit: int = KAKAO_TEXT_LIMIT
) -> str:
    """msg 뒤에 빈 줄 + title + 들어가는 만큼의 lines 를 붙인다. 못 담으면 '…외 N건'."""
    if not lines:
        return msg
    candidate = msg + f"\n\n{title}"
    if len(candidate) > limit:
        return msg  # 섹션 제목조차 못 넣음
    msg = candidate
    shown = 0
    for i, line in enumerate(lines):
        remaining_after = len(lines) - (i + 1)
        tail = f"\n…외 {remaining_after}건" if remaining_after > 0 else ""
        if len(msg) + len("\n" + line) + len(tail) > limit:
            break
        msg += "\n" + line
        shown += 1
    leftover = len(lines) - shown
    if leftover > 0 and len(msg) + len(f"\n…외 {leftover}건") <= limit:
        msg += f"\n…외 {leftover}건"
    return msg


_DRAFT_STATUSES = ("draft_created", "draft_failed", "needs_reply")


def format_pending_notification(entries: list[dict]) -> str:
    """
    아직 알림에 포함되지 않은 항목들(processed_log.pending_notification())을
    카카오 텍스트 한 통으로 요약한다. 200자 이내 보장.
    """
    if not entries:
        return f"📮 미즈메디 메일 ({datetime.now():%H:%M} 기준)\n새로 확인된 메일 없음"

    cats = Counter(e.get("category", "기타") for e in entries)
    cat_str = " / ".join(
        f"{c} {cats[c]}" for c in ("업무", "광고성", "스팸", "기타") if cats.get(c)
    )
    head = [
        f"📮 미즈메디 메일 ({datetime.now():%H:%M} 기준)",
        f"새로 확인 {len(entries)}건" + (f" · {cat_str}" if cat_str else ""),
    ]

    work = [e for e in entries if e.get("category") == "업무"]
    drafts = [e for e in work if e.get("reply_status") in _DRAFT_STATUSES]
    replied = [e for e in work if e.get("reply_status") == "already_replied"]
    failed = sum(1 for e in work if e.get("reply_status") == "draft_failed")
    if work:
        parts = []
        if drafts:
            parts.append(f"회신 초안 {len(drafts)}건")
        if replied:
            parts.append(f"이미 답장 {len(replied)}건")
        seg = "업무: " + (" · ".join(parts) if parts else "회신 불필요")
        if failed:
            seg += f" (초안 저장 실패 {failed})"
        head.append(seg)

    msg = "\n".join(head)
    msg = _pack_section(msg, "[회신 초안]", [_work_line(e) for e in drafts])
    msg = _pack_section(msg, "[이미 답장 완료]", [_work_line(e) for e in replied])

    if len(msg) > KAKAO_TEXT_LIMIT:  # 최종 안전장치
        msg = msg[: KAKAO_TEXT_LIMIT - 1] + "…"
    return msg

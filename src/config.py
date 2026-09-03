"""
설정 로더.

- .env 파일에서 일반 설정을 읽는다 (python-dotenv).
- Gmail OAuth 클라이언트 정보는 .env가 아니라 credentials/ 폴더 안의
  client_secret_*.json 파일에서 직접 찾는다.
- 비밀번호 / API 키는 절대 이 파일에 하드코딩하지 않는다.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 (이 파일 기준 상위 폴더)
ROOT_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = ROOT_DIR / "credentials"
DATA_DIR = ROOT_DIR / "data"

# .env 로드 (없어도 에러는 아님 - 테스트 단계에서는 없을 수 있음)
load_dotenv(ROOT_DIR / ".env")


def get_client_secret_path() -> Path:
    """credentials/ 폴더 안의 Gmail OAuth 클라이언트 JSON 파일 경로를 찾는다."""
    if not CREDENTIALS_DIR.is_dir():
        raise FileNotFoundError(
            f"credentials/ 폴더가 없습니다: {CREDENTIALS_DIR}"
        )

    matches = sorted(glob.glob(str(CREDENTIALS_DIR / "client_secret*.json")))
    if not matches:
        raise FileNotFoundError(
            "credentials/ 폴더 안에서 client_secret*.json 파일을 찾지 못했습니다. "
            "Google Cloud Console에서 받은 OAuth 클라이언트 JSON을 넣어주세요."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"client_secret*.json 파일이 여러 개입니다: {matches}. 하나만 남겨주세요."
        )
    return Path(matches[0])


# 토큰 저장 위치도 credentials/ 안 (gitignore 대상)
TOKEN_PATH = CREDENTIALS_DIR / "token.json"

# 일반 설정 (.env)
TARGET_GMAIL_ADDRESS = os.getenv("TARGET_GMAIL_ADDRESS", "")
# 회신 초안(임시보관함)을 만들 계정. 재인증 시 이 계정으로 로그인해야 한다.
# 파이프라인은 로그인 계정이 이 값과 다르면 초안 생성을 거부한다(오배치 방지).
GMAIL_DRAFT_ACCOUNT = os.getenv("GMAIL_DRAFT_ACCOUNT", "tai.roh@mizmedi.com")
GMAIL_QUERY = os.getenv("GMAIL_QUERY") or "in:inbox"
REPORT_DIR = os.getenv("REPORT_DIR", "reports")
REPORT_PATH = ROOT_DIR / REPORT_DIR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 분류·초안용 LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "claude-sonnet-4-6")
DRAFTER_MODEL = os.getenv("DRAFTER_MODEL") or CLASSIFIER_MODEL

# 처리한 메일 상태 기록 파일 (id → 메타데이터 + notified 플래그)
PROCESSED_IDS_PATH = DATA_DIR / "processed_ids.json"

# 처리 기록 보존 기간(일). 이보다 오래된 항목은 큰 필드(초안 본문·요약 등)를
# 떼고 id + notified 만 남긴다 (dedup 은 계속 보장).
PROCESSED_RETENTION_DAYS = int(os.getenv("PROCESSED_RETENTION_DAYS", "60"))


def _parse_hours(raw: str) -> frozenset[int]:
    hours = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 23:
            hours.add(int(part))
    return frozenset(hours)


# 카카오 알림을 보내는 정시 (그 외 정시엔 체크만 하고 알림 없음).
# 알림 슬롯을 놓치면 다음 실행이 "지난 슬롯 이후 미전송분"을 따라잡는다.
NOTIFY_HOURS = _parse_hours(os.getenv("NOTIFY_HOURS", "9,13,17"))

# 카카오톡 알림
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
# 카카오 개발자 콘솔에서 "client_secret" 을 켠 경우 필수 (KOE010 방지)
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:8888/callback")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")
# access/refresh 토큰 캐시 (credentials/ 안 → git 제외)
KAKAO_TOKEN_PATH = CREDENTIALS_DIR / "kakao_token.json"

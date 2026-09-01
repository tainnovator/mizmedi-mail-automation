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
GMAIL_QUERY = os.getenv("GMAIL_QUERY") or "in:inbox"
REPORT_DIR = os.getenv("REPORT_DIR", "reports")
REPORT_PATH = ROOT_DIR / REPORT_DIR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 분류·초안용 LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "claude-sonnet-4-6")
DRAFTER_MODEL = os.getenv("DRAFTER_MODEL") or CLASSIFIER_MODEL

# 처리 완료한 메일 ID 기록 파일
PROCESSED_IDS_PATH = DATA_DIR / "processed_ids.json"

# 카카오톡 알림
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
# 카카오 개발자 콘솔에서 "client_secret" 을 켠 경우 필수 (KOE010 방지)
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:8888/callback")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")
# access/refresh 토큰 캐시 (credentials/ 안 → git 제외)
KAKAO_TOKEN_PATH = CREDENTIALS_DIR / "kakao_token.json"

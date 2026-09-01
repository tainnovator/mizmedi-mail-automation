"""
카카오 로그인 인증 (최초 1회).

동작
  1. .env 의 KAKAO_REST_API_KEY / KAKAO_REDIRECT_URI 로 인증 URL을 만든다.
  2. 브라우저를 열어 카카오 로그인 + 동의(talk_message 권한)를 받는다.
  3. Redirect URI 로 돌아온 authorization code 를 로컬 서버로 받아,
     access token / refresh token 을 발급한다.
  4. 토큰은 credentials/kakao_token.json 에 저장한다.
  5. refresh token 을 화면에 출력한다. .env 의 KAKAO_REFRESH_TOKEN 자리에
     직접 붙여넣으면 된다. (이 스크립트는 .env 를 덮어쓰지 않는다.)

사전 준비 (카카오 개발자 콘솔)
  - 내 애플리케이션 > 카카오 로그인 > 활성화 ON
  - Redirect URI 에 .env 의 KAKAO_REDIRECT_URI 값과 똑같이 등록
  - 카카오 로그인 > 동의항목 > "카카오톡 메시지 전송(talk_message)" 사용 설정

실행 (프로젝트 루트에서):
  .venv/bin/python -m scripts.kakao_auth
"""

from __future__ import annotations

import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (  # noqa: E402
    KAKAO_REDIRECT_URI,
    KAKAO_REST_API_KEY,
    KAKAO_TOKEN_PATH,
)
from src.kakao_notify import build_authorize_url, exchange_code_for_tokens  # noqa: E402

_auth_code: str | None = None
_auth_error: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global _auth_code, _auth_error
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        _auth_code = params.get("code", [None])[0]
        _auth_error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = (
            "인증 완료. 이 창을 닫고 터미널로 돌아가세요."
            if _auth_code
            else f"인증 실패: {_auth_error}"
        )
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))

    def log_message(self, *args):  # 서버 로그 억제
        pass


def main() -> int:
    if not KAKAO_REST_API_KEY:
        print("오류: .env 에 KAKAO_REST_API_KEY 가 없습니다.")
        return 1

    parsed = urlparse(KAKAO_REDIRECT_URI)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    expected_path = parsed.path or "/"

    if host not in ("localhost", "127.0.0.1"):
        print(
            f"경고: KAKAO_REDIRECT_URI 호스트가 '{host}' 입니다. "
            "이 스크립트는 localhost 로컬 서버로만 code 를 받을 수 있습니다."
        )

    print("카카오 개발자 콘솔에 아래 Redirect URI 가 등록되어 있어야 합니다:")
    print(f"  {KAKAO_REDIRECT_URI}\n")

    auth_url = build_authorize_url()
    print("브라우저에서 카카오 로그인을 진행하세요. (안 열리면 아래 URL을 직접 여세요)")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer((host, port), _Handler)
    print(f"{host}:{port} 에서 리디렉션 대기 중...")
    while _auth_code is None and _auth_error is None:
        server.handle_request()

    if _auth_error:
        print(f"인증 실패: {_auth_error}")
        return 1

    print("authorization code 수신. 토큰 발급 중...\n")
    tokens = exchange_code_for_tokens(_auth_code)

    print("=" * 60)
    print("토큰 발급 완료.")
    print(f"캐시 저장 위치: {KAKAO_TOKEN_PATH}")
    print("=" * 60)
    print("\n아래 값을 .env 의 KAKAO_REFRESH_TOKEN 에 붙여넣으세요 "
          "(자동으로 저장하지 않습니다):\n")
    print(f"KAKAO_REFRESH_TOKEN={tokens['refresh_token']}\n")
    print("완료 후 scripts/test_kakao_notify.py 로 전송 테스트를 해보세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

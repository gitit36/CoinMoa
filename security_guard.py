"""
SecurityGuard — API 권한 검증

각 거래소 API 키가 읽기 전용(조회 권한만)인지 확인하여,
위험한 권한(출금·주문 등)이 포함된 키를 사용하는 일을 방지합니다.

검증 방식:
  - Upbit/Bithumb: 위험 엔드포인트(주문·출금)에 빈 요청을 전송하여,
    "권한 없음" 에러가 아닌 "파라미터 오류"가 돌아오면 해당 권한이 있는 것으로 판단.
  - Lighter: 토큰이 'ro:' 로 시작하는지 검사 + 조회 API 호출.

Usage:
    from security_guard import SecurityGuard
    guard = SecurityGuard()
    guard.check_all(["upbit", "bithumb"])  # raises SystemExit on failure
"""

import os
import re
import logging
import requests
from dotenv import load_dotenv

logger = logging.getLogger("security_guard")

load_dotenv()

# Upbit/Bithumb 에서 "권한 없음"을 나타내는 에러 이름들
_AUTH_DENIED_ERRORS = {
    "no_authorization",
    "unauthorized",
    "out_of_scope",
    "jwt_verification",
    "invalid_access_key",
    "expired_access_key",
}


class SecurityGuard:
    """
    API 키 권한 검증기.

    위험 엔드포인트에 빈 요청을 보내(probe) 권한 여부를 판별합니다.
    - 파라미터 오류(400) → 해당 엔드포인트 접근 가능 → 위험
    - 권한 에러(401/403) → 접근 불가 → 안전
    """

    # ── Upbit ─────────────────────────────────────────────────

    def check_upbit(self, client) -> bool:
        """
        Upbit API 키 권한 검증.

        주문(POST /v1/orders)과 출금(POST /v1/withdraws/coin) 엔드포인트에
        빈 요청을 전송하여 권한 보유 여부를 판별합니다.

        Returns:
            True = 안전 (조회 전용), False = 위험한 권한 감지
        """
        probes = [
            ("주문(order)", "/v1/orders", {}),
            ("출금(withdraw)", "/v1/withdraws/coin", {}),
        ]
        return self._probe_cex(client, "Upbit", probes)

    # ── Bithumb ───────────────────────────────────────────────

    def check_bithumb(self, client) -> bool:
        """
        Bithumb API 키 권한 검증.

        주문(POST /v1/orders)과 출금(POST /v1/withdraws/coin) 엔드포인트에
        빈 요청을 전송하여 권한 보유 여부를 판별합니다.

        Returns:
            True = 안전 (조회 전용), False = 위험한 권한 감지
        """
        probes = [
            ("주문(trade)", "/v1/orders", {}),
            ("출금(withdraw)", "/v1/withdraws/coin", {}),
        ]
        return self._probe_cex(client, "Bithumb", probes)

    # ── Lighter ───────────────────────────────────────────────

    def check_lighter(self, token: str | None = None) -> bool:
        """
        Lighter 토큰 검증.

        1) 토큰이 'ro:' 로 시작하는지 정규식 검사
        2) 간단한 조회 API 호출하여 인증 성공 여부 확인

        Returns:
            True = 안전 (읽기 전용 토큰), False = 위험하거나 유효하지 않음
        """
        if token is None:
            token = os.getenv("LIGHTER_RO_TOKEN", "").strip()

        if not token:
            logger.error("Lighter 토큰이 설정되지 않았습니다.")
            return False

        # 1) 'ro:' prefix check
        if not re.match(r"^ro:", token):
            logger.warning(
                "⚠️  Lighter 토큰이 'ro:'로 시작하지 않습니다. "
                "읽기 전용 토큰만 사용하세요."
            )
            return False

        # 2) Simple query API call to verify token works
        base_url = os.getenv(
            "LIGHTER_BASE_URL",
            "https://mainnet.zklighter.elliot.ai",
        ).rstrip("/")
        account_index = os.getenv("LIGHTER_ACCOUNT_INDEX", "").strip()

        if not account_index:
            logger.error("LIGHTER_ACCOUNT_INDEX 가 설정되지 않았습니다.")
            return False

        try:
            r = requests.get(
                f"{base_url}/api/v1/account",
                params={
                    "auth": token,
                    "by": "index",
                    "value": account_index,
                },
                timeout=10,
            )
            if r.status_code == 200:
                return True
            logger.error(
                "Lighter 토큰 인증 실패 (HTTP %d): %s",
                r.status_code, r.text[:200],
            )
            return False
        except Exception as e:
            logger.error("Lighter 토큰 검증 API 호출 실패: %s", e)
            return False

    # ── Batch check ───────────────────────────────────────────

    def check_all(self, exchanges: list[str]) -> bool:
        """
        지정된 거래소 목록에 대해 API 키 권한을 일괄 검증합니다.

        Args:
            exchanges: 검증할 거래소 키 목록 (e.g. ["upbit", "bithumb", "lighter"])

        Returns:
            True = 모두 안전, False = 하나 이상 실패
        """
        from upbit_client import UpbitClient
        from bithumb_client import BithumbClient

        results = {}

        for ex in exchanges:
            ex = ex.lower().strip()
            if ex == "upbit":
                client = UpbitClient()
                results[ex] = self.check_upbit(client)
            elif ex == "bithumb":
                client = BithumbClient()
                results[ex] = self.check_bithumb(client)
            elif ex == "lighter":
                results[ex] = self.check_lighter()
            else:
                logger.warning("알 수 없는 거래소: %s (건너뜀)", ex)
                continue

        # Print results
        all_ok = True
        for ex, ok in results.items():
            if ok:
                print(f"  🔒 {ex.capitalize()} API 권한 검증 통과 ✅")
            else:
                print(
                    f"  🚨 {ex.capitalize()} API 권한 검증 실패 ❌"
                    f" — 위험한 권한(주문/출금)이 감지되었습니다."
                    f"\n     조회 전용 API 키를 발급받아 .env 에 설정하세요."
                )
                all_ok = False

        return all_ok

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _probe_cex(client, exchange_name: str, probes: list[tuple]) -> bool:
        """
        위험 엔드포인트에 빈 POST 요청을 보내 권한을 판별합니다.

        - 파라미터/검증 오류(400) → 엔드포인트 접근 가능 → 위험 권한 보유
        - 권한 오류(401/403/no_authorization) → 접근 불가 → 안전

        Returns:
            True = 안전 (모든 probe에서 권한 없음), False = 위험 권한 감지
        """
        for label, path, body in probes:
            try:
                result = client.post(path, body=body)
            except Exception as e:
                logger.error(
                    "%s %s probe 실패: %s", exchange_name, label, e,
                )
                return False

            if not isinstance(result, dict):
                # Unexpected response
                continue

            status = result.get("status_code", 0)
            error_name = str(result.get("error_name", "")).lower()

            # Auth denied → this capability is blocked → safe for this probe
            if status in (401, 403) or error_name in _AUTH_DENIED_ERRORS:
                continue

            # Parameter error (400) → endpoint accepted auth, just needs params
            # This means the key HAS this permission → DANGEROUS
            logger.warning(
                "⚠️  %s %s 권한 감지됨 (error: %s)",
                exchange_name, label, error_name,
            )
            return False

        return True

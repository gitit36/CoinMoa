# Lighter API – 잔고, 입출금, 거래 내역, 손익

[Lighter API 문서](https://apidocs.lighter.xyz/docs/get-started-for-programmers-1)를 바탕으로 계정 **잔고**, **입출금 내역**, **거래 내역**, **손익**을 조회하는 기본 기능을 제공합니다.

- **요구 사항**: Python 3.8+ (lighter-sdk 호환)

## 폴더 가이드

- 핵심 실행 코드: 루트(`main.py`, `lighter_client.py`, `api_client.py`, `extractors/`)
- 스크립트 본문: `scripts/`
- 실행 결과물: `outputs/`
- 샘플 입력 데이터: `data/samples/`
  - 예시: `data/samples/test_lighter_sj_v0.2.csv`

## 설정

```bash
# 의존성 설치 (시스템 Python 3.9 사용 권장)
python3 -m pip install -r requirements.txt

# 또는 conda 환경 사용 시
conda deactivate  # conda 환경 비활성화 (아키텍처 충돌 방지)
python3 -m pip install -r requirements.txt

# 환경 변수 설정
cp .env.example .env
# .env 에 BASE_URL, ACCOUNT_INDEX (필수) 입력
# 입출금/거래 내역: READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 중 하나 설정
```

**주의**: conda base 환경에서 실행 시 아키텍처 불일치 오류가 발생할 수 있습니다. `conda deactivate`로 conda 환경을 비활성화한 후 실행하세요.

### 환경 변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `BASE_URL` | ○ | 테스트넷: `https://testnet.zklighter.elliot.ai`, 메인넷: `https://mainnet.zklighter.elliot.ai` |
| `L1_ADDRESS` | △ | L1(이더리움) 주소. 계정 인덱스 조회 시 사용 |
| `ACCOUNT_INDEX` | ○ | 계정 인덱스 (Lighter 계정 번호) |
| `READ_ONLY_AUTH_TOKEN` | △ | 읽기 전용 토큰. [Lighter read-only tokens](https://app.lighter.xyz/read-only-tokens/)에서 발급. 입출금/거래 내역 조회에 사용. 설정 시 `API_KEY_PRIVATE_KEY` 불필요 |
| `API_KEY_INDEX` | △ | READ_ONLY_AUTH_TOKEN 미사용 시 입출금/거래 내역용 auth 토큰 생성에 사용 (기본 3) |
| `API_KEY_PRIVATE_KEY` | △ | API 키 비밀키. READ_ONLY_AUTH_TOKEN 없을 때만 입출금/거래 내역에 필요 |
| `ETHERSCAN_API_KEY` | △ | Etherscan API 키. 입출금 온체인 조회 시 rate limit 방지 |
| `KOREAEXIM_API_KEY` | △ | 한국수출입은행 환율 API 키. 거래일별 환율 조회용 (세법 기준) |

- **잔고·손익**: `ACCOUNT_INDEX`만 있어도 조회 가능 (공개 계정 정보).
- **입출금 내역·거래 내역**: `READ_ONLY_AUTH_TOKEN` 또는 `API_KEY_PRIVATE_KEY` 중 하나만 설정하면 됨. 읽기 전용만 쓰려면 토큰만 넣으면 되고 API 키 비밀키는 저장하지 않아도 됨.
- **보안**: `READ_ONLY_AUTH_TOKEN`이 설정된 상태에서 `API_KEY_PRIVATE_KEY`까지 넣으면 프로그램이 시작 시 오류로 종료합니다. 읽기 전용 모드에서는 private key 입력이 허용되지 않습니다.

## 사용법

### 한 번에 모두 출력

```bash
python lighter_client.py
```

출력 예:

- **잔고 (Balance)**: 계정 인덱스, 담보(USDC)
- **손익 (PnL)**: 미실현/실현 PnL, 마켓별 포지션
- **입출금 내역**: L1 메타데이터 (read-only 토큰 또는 API 키 있을 때)
- **거래 내역**: 체결 내역 (read-only 토큰 또는 API 키 있을 때)

### Python에서 함수로 사용

```python
import asyncio
from lighter_client import get_balance, get_pnl, get_deposits_withdrawals, get_trades

async def main():
    balance = await get_balance()           # 잔고
    pnl = await get_pnl()                   # 손익
    deposits = await get_deposits_withdrawals(limit=20)  # 입출금 (auth 필요)
    trades = await get_trades(limit=20)     # 거래 내역 (auth 필요)
    print(balance, pnl, deposits, trades)

asyncio.run(main())
```

### CSV 내보내기 (세법 기준 환율 적용)

```bash
# 기본 환율 사용 (1300원)
python3 lighter_client.py --csv

# 사용자 지정 환율
python3 lighter_client.py --csv --rate 1350

# 거래일별 환율 적용 (KOREAEXIM_API_KEY 필요)
python3 lighter_client.py --csv --daily-rates

# 파일명 지정
python3 lighter_client.py --csv --output transactions.csv
python3 lighter_client.py --csv --daily-rates -o transactions.csv

# 모든 옵션 조합
python3 lighter_client.py --csv --daily-rates --rate 1300 --output my_transactions.csv
```

### 실시간 모니터링 모드

거래 내역을 주기적으로 자동 업데이트합니다:

```bash
# 기본 설정 (60초마다 업데이트)
python3 lighter_client.py --watch

# 업데이트 간격 지정 (초 단위)
python3 lighter_client.py --watch --interval 30

# 파일명 지정
python3 lighter_client.py --watch --output live_transactions.csv

# 거래일별 환율 적용
python3 lighter_client.py --watch --daily-rates

# 모든 옵션 조합
python3 lighter_client.py --watch --interval 60 --daily-rates --rate 1300 --output live.csv
```

**실시간 모니터링 특징:**
- 지정한 간격(기본 60초)마다 자동으로 CSV 파일 업데이트
- 새로운 거래가 감지되면 즉시 파일에 반영
- 터미널에 업데이트 상태 표시
- `Ctrl+C`로 종료

**CSV 형식:**
- 컬럼: `일시 | 거래소 | 유형 | 페어 | 통화 | 가격 | 원화가치 | 적용환율`
- 입출금 내역과 거래 내역이 시간순으로 정렬되어 포함됩니다.

**환율 적용 방법:**
1. **고정 환율** (`--rate` 옵션): 모든 거래에 동일한 환율 적용 (기본 1300원)
2. **거래일별 환율** (`--daily-rates` 옵션): 각 거래일의 실제 환율 적용 (세법 기준)
   - `KOREAEXIM_API_KEY` 설정 필요: [공공데이터포털](https://www.data.go.kr/data/3068846/openapi.do)에서 무료 발급
   - 한국수출입은행 환율 API 사용 (매매기준율)
   - API 키가 없거나 조회 실패 시 기본 환율 사용

**세법 기준:**
- 국세청 고시에 따르면 거래일 기준 환율 적용 권장
- `--daily-rates` 옵션 사용 시 각 거래일의 실제 환율이 적용됩니다

**로그 CSV 및 Explorer 데이터 범위:**
- `--logs-csv` 로 내보내는 로그/거래 데이터는 **Explorer API**에서 가져옵니다.
- Explorer는 **과거 로그 보관 기간이 제한**되어 있을 수 있어, 예를 들어 2025년 4월 첫 거래라고 해도 8월 이전 데이터가 API에 없을 수 있습니다.
- 실행 시 `데이터 기간: YYYY-MM-DD ~ YYYY-MM-DD (Explorer 제공 범위)` 로 실제 받아온 기간이 표시됩니다. 그 이전 구간이 필요하면 Lighter/Explorer 측 문의가 필요할 수 있습니다.

**Read token으로 4월까지 거래 수집 (accountTrades API):**
- Explorer에 없는 과거 거래를 **accountTrades API**로 가져오려면 **READ_ONLY_AUTH_TOKEN**과 **ACCOUNT_INDEX**가 필요합니다.
- `python3 lighter_client.py --trades-api` 로 API만 사용해 2025년 4월까지 거래를 수집해 터미널에 냅니다.
- CSV로 저장: `python3 lighter_client.py --trades-api -o trades_from_api.csv`

## EdgeX (동일 방식)

[EdgeX API](https://edgex-1.gitbook.io/edgeX-documentation/api)를 사용해 Lighter와 같은 방식으로 **잔고**, **담보 입출금**, **포지션/거래 내역**, **손익**을 조회할 수 있습니다.

```bash
# EdgeX SDK 설치 (EdgeX만 쓸 경우 Lighter 의존성 없이도 동작)
pip install edgex-python-sdk

# .env 에 EdgeX 설정 추가
# EDGEX_BASE_URL=https://pro.edgex.exchange
# EDGEX_ACCOUNT_ID=your_account_id
# EDGEX_STARK_PRIVATE_KEY=your_stark_private_key_hex

# EdgeX 요약(잔고·PNL)만 출력
python3 edgex_client.py
```

**Python에서 사용:**

```python
import asyncio
from edgex_client import get_balance, get_pnl, get_deposits_withdrawals, get_trades, export_to_csv

async def main():
    b = await get_balance()
    p = await get_pnl()
    dw = await get_deposits_withdrawals(limit=50)
    tr = await get_trades(limit=50)
    csv_str = await export_to_csv(usd_to_krw_rate=1300.0)
asyncio.run(main())
```

**CSV 형식:** Lighter와 동일한 컬럼(`일시|거래소|유형|페어|통화|가격|원화가치|수수료(USD)|적용환율`), 거래소명은 `EdgeX`로 출력됩니다. 두 거래소 데이터를 합쳐서 하나의 CSV로 쓰려면 각각 `export_to_csv()` 결과를 시간순으로 병합하면 됩니다.

## API 참고

### 엔드포인트 목록

Base URL: **메인넷** `https://mainnet.zklighter.elliot.ai`, **테스트넷** `https://testnet.zklighter.elliot.ai`

| 용도 | 메서드 | 경로 | 인증 | 쿼리 예시 |
|------|--------|------|------|-----------|
| 입금 내역 | GET | `/api/v1/deposit/history` | 선택(일부 환경에선 없이 됨) | `account_index`, `limit`, `l1_address` |
| 출금 내역 | GET | `/api/v1/withdraw/history` | 선택(일부 환경에선 없이 됨) | `account_index`, `limit`, `l1_address` |
| 입출금 통합(L1 메타) | GET | `/api/v1/l1Metadata` | **필수** | `account_index`, `limit`, `l1_address`, `auth` |
| 계정 거래 내역 | GET | `/api/v1/accountTrades` | **필수** | `account_index`, `limit`, `offset`, `market_id`, `auth` |
| 계정 정보(잔고 등) | GET | `/api/v1/account` | 불필요 | `by=index`, `value={account_index}` |
| 리퍼럴 포인트 | GET | `/api/v1/referral/points` | **필수** | `account_index`, `auth` |
| 서버 상태 | GET | `/` | 불필요 | - |

**청산(liquidation)**  
전용 REST 엔드포인트는 없음. **Explorer 계정 로그**에 `tx_type`(예: `Liquidation`)으로 들어오거나, **accountTrades**에서 청산으로 체결된 거래에 포함됨. `--logs-csv` / `--logs-csv-flat` 로 내보내면 로그 CSV에 함께 나옴.

**Explorer API** (로그/거래 등, 인증 불필요):

| 용도 | 메서드 | 경로 |
|------|--------|------|
| 계정 로그 | GET | `https://explorer.elliot.ai/api/accounts/{account_index 또는 l1_address}/logs` |
| 로그 상세 | GET | `https://explorer.elliot.ai/api/logs/{tx_hash}` |

- 잔고·손익: `AccountApi.account(by="index", value=account_index)`  
  - [Account Index](https://apidocs.lighter.xyz/docs/account-index), [Get Started](https://apidocs.lighter.xyz/docs/get-started-for-programmers-1)
- 인증: read-only 토큰 또는 full auth → `auth` 쿼리 파라미터 + `Authorization` 헤더 둘 다 전송

### 인증 조건 (입출금/거래 내역)

문서([API keys](https://apidocs.lighter.xyz/docs/api-keys)) 기준:

- **일반 auth 토큰**: `{expiry_unix}:{account_index}:{api_key_index}:{random_hex}` (최대 8시간). API private key로 `create_auth_token_with_expiry()` 생성.
- **Read-only 토큰**: `ro:{account_index}:{single|all}:{expiry_unix}:{random_hex}` (1일~10년). [createToken](https://apidocs.lighter.xyz/reference/tokens_create) 또는 [앱](https://app.lighter.xyz/read-only-tokens/)에서 발급. “auth-gated 데이터 조회” 가능.

현재 구현: `auth` 쿼리 + `Authorization` 헤더에 토큰 전송. **Read-only 토큰**(`ro:...`)은 `Authorization: Bearer <token>`으로 먼저 시도하고, 401이면 raw 토큰으로 재시도합니다.  
**l1Metadata 401 "invalid auth string", accountTrades 403** 이 나오면: 문서상 read-only로 “auth-gated 데이터” 접근 가능하다고 되어 있으나, 서버가 해당 엔드포인트를 read-only로 막아 둔 상태일 수 있음. 이 경우 **API_KEY_PRIVATE_KEY**로 일반 auth 토큰을 사용하거나, Lighter 측에 read-only 토큰으로 입출금/거래 내역 API 허용 요청을 할 수 있음. `--via-read-token` 실행 시 실패하면 deposit/history, withdraw/history, l1Metadata 각 단계별 HTTP 상태가 에러 메시지에 포함됩니다.

### Private key 없이 입출금 내역 보기 (온체인)

- **구현됨**: `L1_ADDRESS`가 설정되어 있으면 **Etherscan API**로 해당 주소가 Lighter 컨트랙트([0x3B4D79...5ca7](https://etherscan.io/address/0x3b4d794a66304f130a4db8f2551b0070dfcf5ca7))에 보낸 트랜잭션 중 `deposit`(0x8a857083), `withdraw`(0xd20191bd)만 필터해 입출금 내역으로 표시합니다. **Lighter API 키/private key 불필요**.
- **ETHERSCAN_API_KEY** (선택): [Etherscan](https://etherscan.io/apis)에서 무료 API 키 발급 후 `.env`에 넣으면 rate limit/NOTOK 가능성이 줄어듭니다.
- API(deposit/history, withdraw/history, l1Metadata)는 인증이 필요해, 온체인 조회 결과가 없을 때만 시도하며 실패 시 401이 나올 수 있음.

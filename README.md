# coinTax

여러 거래소(Upbit, Bithumb, Lighter)의 거래 내역을 한방에 긁어서 하나의 CSV로 뽑아주는 도구임.

세금 신고할 때 거래소마다 따로 CSV 다운받고 엑셀에서 합치고... 이런 짓 안 해도 됨.
커맨드 한 줄이면 전부 합쳐진 파일이 나옴.


## 이게 뭔데

코인 거래하면 매수/매도/입금/출금 기록이 거래소마다 흩어져 있음.
이걸 하나하나 모으려면 귀찮고 빠뜨리기도 쉬움.

이 도구는:
- **Upbit**, **Bithumb**, **Lighter** 세 거래소의 내역을 API로 자동 수집함
- 전부 같은 포맷(일시, 거래소, 유형, 금액, 수수료 등)으로 통일함
- 시간순으로 정렬해서 **CSV 파일 하나**로 저장함

세금 계산이든 포트폴리오 정리든, 이 CSV 하나면 충분함.


## 시작하기 전에 준비할 것

### 1. Python 설치

Python 3.9 이상이 필요함. 터미널에서 아래 명령어 쳐서 확인할 수 있음:

```bash
python3 --version
```

`Python 3.9.x` 이런 식으로 나오면 됨. 안 나오면 [python.org](https://www.python.org/downloads/)에서 설치하면 됨.

### 2. 라이브러리 설치

프로젝트 폴더에서 아래 명령어 실행:

```bash
pip install python-dotenv requests pandas PyJWT
```

이미 설치돼 있으면 넘어가도 됨.

### 3. API 키 세팅

각 거래소에서 API 키를 발급받아야 함. 발급 방법은 거래소마다 다른데, 보통 "마이페이지 → API 관리" 같은 메뉴에 있음.

프로젝트 폴더에 `.env` 파일을 만들고 (이미 있으면 내용만 채우면 됨) 아래처럼 작성:

```
# Upbit
UPBIT_ACCESS_KEY=여기에_업비트_액세스키
UPBIT_SECRET_KEY=여기에_업비트_시크릿키

# Bithumb
BITHUMB_ACCESS_KEY=여기에_빗썸_액세스키
BITHUMB_SECRET_KEY=여기에_빗썸_시크릿키

# Lighter
LIGHTER_RO_TOKEN=ro:여기에_라이터_토큰
LIGHTER_ACCOUNT_INDEX=12345
LIGHTER_L1_ADDRESS=0xabc...
```

**주의**: `.env` 파일에는 실제 API 키가 들어가니까 절대 깃허브 같은 데 올리면 안 됨.

전부 다 채울 필요는 없음. 예를 들어 Upbit만 쓸 거면 Upbit 키만 넣으면 됨.


## 사용법

기본 형태는 이렇게 생겼음:

```bash
python unified_txlog.py <시작날짜> <끝날짜>
```

날짜는 `YYYY-MM-DD` 형식임. 예를 들어 2024년 한 해 전체를 뽑고 싶으면:

```bash
python unified_txlog.py 2024-01-01 2024-12-31
```

이러면 세 거래소 전부에서 2024년 거래 내역을 가져와서 `unified_timeline.csv`라는 파일로 저장됨.

### 예시 모음

**특정 거래소만 뽑고 싶을 때:**

Upbit이랑 Lighter만 뽑고 싶으면:
```bash
python unified_txlog.py 2024-01-01 2024-12-31 --exchanges upbit,lighter
```

Bithumb만:
```bash
python unified_txlog.py 2025-01-01 2025-06-30 --exchanges bithumb
```

**파일 이름을 바꾸고 싶을 때:**

```bash
python unified_txlog.py 2024-01-01 2024-12-31 --out 2024_전체내역.csv
```

**환율을 직접 지정하고 싶을 때:**

Lighter 같은 해외 거래소는 USD 기반이라 원화 환산이 필요함. 기본값은 1,300원인데, 다른 환율을 쓰고 싶으면:
```bash
python unified_txlog.py 2024-01-01 2024-12-31 --fx 1350
```

**전부 다 섞어서:**

```bash
python unified_txlog.py 2024-06-01 2024-12-31 --exchanges upbit,lighter --fx 1400 --out 하반기.csv
```

### 옵션 요약

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `시작날짜` | (필수) | 조회 시작일. `YYYY-MM-DD` |
| `끝날짜` | (필수) | 조회 종료일. `YYYY-MM-DD` |
| `--exchanges` | `upbit,bithumb,lighter` | 조회할 거래소. 콤마로 구분 |
| `--out` | `unified_timeline.csv` | 저장할 파일 이름 |
| `--fx` | `1300` | USD→KRW 환율 (Lighter용) |


## 출력 파일은 이렇게 생겼음

CSV를 열어보면 이런 컬럼들이 있음:

| 컬럼 | 설명 | 예시 |
|---|---|---|
| `ts_kst` | 시각 (정렬용) | `2024-03-15 14:30:00+09:00` |
| `일시` | 보기 좋은 시각 | `2024-03-15-14-30-00` |
| `거래소` | 어디서 발생 | `Upbit` / `Bithumb` / `Lighter` |
| `유형` | 뭘 했는지 | `매수` / `매도` / `입금` / `출금` / `청산` / `이체` |
| `페어` | 거래쌍 | `KRW-BTC`, `BTC-USD` |
| `통화` | 코인 종류 | `BTC`, `ETH` |
| `수량` | 얼마나 | `0.005` |
| `가격` | 단가 | `85000000` |
| `원화가치` | 원화 환산 금액 | `425000` |
| `적용환율` | 적용된 환율 | `1300.0` |
| `수수료` | 수수료 (원화) | `212` |
| `txid_or_uuid` | 거래 고유번호 | `abc-123-def` |


## 디렉토리 구조

```
coinTax/
├── .env                  ← API 키 (깃에 올리면 안 됨)
├── unified_txlog.py      ← 메인 실행 파일. 이것만 실행하면 됨
├── lighter_txlog.py      ← Lighter 거래소 전용 수집기
├── txlog.py              ← Upbit/Bithumb 거래 조회 유틸
├── upbit_client.py       ← Upbit API 클라이언트
├── bithumb_client.py     ← Bithumb API 클라이언트
├── README.md             ← 지금 보고 있는 이 문서
└── archive/              ← 안 쓰는 파일들 보관함
    ├── Lighter 복사본/
    ├── Lighter 복사본.zip
    ├── jinmo_codes.zip
    ├── lighter.xyz.ipynb
    └── test_lighter_sj*.csv
```

핵심 파일은 루트에 있는 `.py` 파일 5개임. `archive/`는 이전에 쓰던 참고 코드나 테스트 파일들을 모아놓은 곳이라 실행에는 관계없음.


## 새 거래소 추가하려면

나중에 Binance, Coinbase 같은 거래소를 추가하고 싶으면:

1. 해당 거래소의 API 클라이언트 파일을 만듦 (예: `binance_client.py`)
2. `unified_txlog.py`에 `get_binance_events()` 같은 함수를 추가함
3. `--exchanges` 옵션에 `binance`를 추가할 수 있도록 등록함
4. `.env`에 해당 거래소 API 키를 추가함

기존 코드 구조가 거래소별로 분리돼 있어서, 다른 파일 건드릴 필요 없이 추가만 하면 됨.


## 문제가 생기면

**"수집 실패" 에러가 뜸:**
→ `.env` 파일에 해당 거래소 API 키가 제대로 들어있는지 확인. 에러 메시지에 어떤 환경변수가 필요한지 나옴.

**"수집된 이벤트가 없습니다":**
→ 해당 기간에 거래 내역이 진짜 없는 건지, 아니면 날짜를 잘못 입력한 건지 확인.

**라이브러리 에러:**
→ `pip install python-dotenv requests pandas PyJWT` 다시 실행.

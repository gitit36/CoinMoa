# CoinMoa Tax Design

한국 거주 개인 사용자를 기준으로, CoinMoa의 거래 원장 데이터를 세무 보조 기능으로 확장하기 위한 설계 문서.

기준일: 2026-03-08


## 1. 목적

현재 CoinMoa는 여러 거래소의 거래 내역을 하나의 canonical CSV로 통합한다.

이 문서는 그 다음 단계로 아래 3가지를 설계한다.

1. 지금 바로 적용 가능한 세무 보조 로직
2. 2027-01-01 이후 가상자산 과세 시행에 대비한 구조
3. 법적 불확실성이 큰 이벤트를 안전하게 처리하는 운영 기준


## 2. 현재 법적 상태 요약

### 2.1 가상자산 양도차익 과세

- 한국 개인의 가상자산 양도·대여 소득 과세는 아직 시행 전
- 시행 예정일: 2027-01-01
- 따라서 2026년 귀속분까지는 CoinMoa에서 자동 세액 계산을 기본 활성화하지 않음

의미:

- 지금은 "세액 확정 계산기"보다 "거래 원장 정리"와 "증빙 보조"가 우선
- 다만 2027년 대비용 취득원가 추적 구조는 미리 설계 가능

### 2.2 현재 바로 적용 가능한 영역

- 해외금융계좌 신고 보조
- 상속세·증여세 평가 보조
- 거래 원장 정규화 및 증빙 export

### 2.3 법적 불확실성이 큰 영역

- 에어드랍
- 거래소 이벤트 보상
- 수수료 리베이트
- 스테이킹 보상
- 레퍼럴 수익

원칙:

- 자동 과세 이벤트로 단정하지 않음
- `manual_review` 상태로 보관


## 3. 제품 원칙

### 3.1 현재 모드

2026년까지 기본 모드는 아래와 같다.

- 거래내역 수집
- 이벤트 정규화
- 월말 잔액 계산
- 자산 흐름 재구성
- 증빙용 CSV/리포트 export

기본적으로 하지 않는 것:

- 자동 산출된 납부세액 확정
- 에어드랍/보상성 자산의 세목 단정

### 3.2 2027 대비 모드

향후 `tax_engine`을 켜면 아래 기능을 추가한다.

- 처분 이벤트 판정
- 취득원가 계산
- 과세대상 손익 집계
- 기본공제 적용
- 세액 시뮬레이션


## 4. 현재 코드베이스와 연결되는 기준 데이터

현재 `unified_txlog.py`의 canonical 컬럼:

- `ts_kst`
- `일시`
- `거래소`
- `유형`
- `페어`
- `통화`
- `수량`
- `가격`
- `원화가치`
- `적용환율`
- `수수료`
- `txid_or_uuid`

이 스키마는 통합 원장으로는 충분하지만, 세무 계산에는 부족하다.

부족한 이유:

- 동일인 지갑 간 이동인지 알 수 없음
- quote/base 자산 변화가 분리되어 있지 않음
- 취득 lot 추적이 안 됨
- 수수료 통화가 모호함
- 코인-코인 교환을 처분+취득으로 분해하기 어려움


## 5. 제안 아키텍처

세무 기능은 아래 4단계 파이프라인으로 분리한다.

1. `raw ingestion`
2. `canonical timeline`
3. `ledger normalization`
4. `tax/report engine`

### 5.1 Raw Ingestion

목적:

- 거래소 API 원본 응답 보관
- 추후 오류 추적 가능성 확보

권장 산출물:

- `outputs/raw/{exchange}/{date}.json`

필드 예시:

- exchange
- endpoint
- requested_at
- payload
- response

### 5.2 Canonical Timeline

현재 `unified_txlog.py`가 담당하는 단계.

역할:

- 거래소별 응답을 사람이 읽기 쉬운 단일 이벤트 테이블로 통합

유지 원칙:

- 현재 스키마는 계속 유지
- 다만 세무 엔진의 입력으로는 직접 사용하지 않고 중간 산출물로 사용

### 5.3 Ledger Normalization

세무 엔진용 표준 이벤트 테이블을 별도로 만든다.

권장 파일:

- `tax_ledger.py`
- `outputs/ledger/normalized_ledger.csv`

핵심 목표:

- 모든 이벤트를 "자산 증감" 중심으로 다시 표현
- 하나의 거래를 여러 개의 ledger row로 분해 가능하게 함

예시:

- KRW-BTC 매수
  - KRW 감소
  - BTC 증가
  - 수수료 차감

- BTC-USDT 교환
  - BTC 처분
  - USDT 취득
  - 수수료 차감

- 동일인 지갑 이동
  - 출금 row
  - 입금 row
  - 과세 이벤트 아님
  - 단, 수수료는 자산 감소로 기록

### 5.4 Tax / Report Engine

권장 파일:

- `tax_rules_kr.py`
- `tax_engine.py`
- `reports_tax.py`

역할:

- 법규 버전에 따라 이벤트 분류
- 취득원가 계산
- 손익 집계
- 월말 잔액 산출
- 상속·증여 평가 보조


## 6. 새 표준 스키마 제안

세무 엔진 입력 테이블 이름 예시:

- `normalized_ledger`

필수 컬럼 제안:

- `event_id`
- `group_id`
- `ts_kst`
- `exchange`
- `account_ref`
- `wallet_ref`
- `asset`
- `delta_amount`
- `direction`
- `event_type`
- `event_subtype`
- `counter_asset`
- `unit_price_krw`
- `gross_value_krw`
- `fee_asset`
- `fee_amount`
- `fee_value_krw`
- `is_internal_transfer`
- `is_taxable_disposal`
- `requires_manual_review`
- `source_txid`
- `source_order_id`
- `source_raw_ref`

컬럼 의미:

- `group_id`: 하나의 주문/입출금/이체를 묶는 ID
- `delta_amount`: 자산 증감량. 유입은 양수, 유출은 음수
- `direction`: `in` 또는 `out`
- `event_type`: `trade`, `deposit`, `withdraw`, `transfer`, `fee`, `reward`, `liquidation`
- `counter_asset`: 거래 상대 자산
- `is_internal_transfer`: 동일인 지갑 간 이동 여부
- `is_taxable_disposal`: 세법상 처분 여부
- `requires_manual_review`: 불확실 이벤트 여부


## 7. 현재 바로 구현 가능한 기능

### 7.1 해외금융계좌 신고 보조

목표:

- 해외 거래소별 월말 잔액을 계산
- 매월 말일 기준 평가금액 합계를 구함
- 신고 필요 여부를 보조 판단

적용 대상 예시:

- Lighter
- EdgeX
- 향후 Binance, Bybit, Coinbase 등

출력 예시:

- `outputs/reports/foreign_accounts_month_end.csv`

권장 컬럼:

- `date`
- `account_ref`
- `exchange`
- `asset`
- `balance`
- `price_krw`
- `value_krw`
- `monthly_total_krw`
- `above_threshold`

계산 원칙:

- 매월 말일 23:59:59 KST 기준 잔액
- 잔액은 거래원장 누적으로 재구성
- 평가가격은 별도 시세 소스 사용
- 합계가 법정 기준금액 초과인지 표시

주의:

- 이 기능은 신고 의무 "판단 보조"이지 법률 자문이 아님

### 7.2 상속세·증여세 평가 보조

목표:

- 특정 기준일에 대한 가상자산 평가자료 생성

출력 예시:

- `outputs/reports/inheritance_gift_valuation.csv`

입력:

- 기준일
- 자산 수량
- 거래소 또는 가격 소스

계산 원칙:

- 법령상 평가기간 기준으로 평균가 계산
- 어떤 가격 소스를 썼는지 보고서에 명시
- 수동 검토 가능하도록 상세 일별 가격 포함

### 7.3 증빙용 통합 원장 고도화

목표:

- 세무사/회계사에게 전달 가능한 정리본 출력

추가 산출물 예시:

- `outputs/reports/unified_timeline_enriched.csv`
- `outputs/reports/internal_transfer_matches.csv`
- `outputs/reports/manual_review_items.csv`


## 8. 2027년 과세 대비 설계

### 8.1 Feature Flag

반드시 연도와 규칙 버전으로 기능을 분리한다.

권장 설정:

- `jurisdiction=KR`
- `tax_year=2026`
- `rule_version=kr_v1_pre_2027`

향후:

- `rule_version=kr_v2_2027_virtual_asset`

효과:

- 동일 데이터라도 연도별 계산 로직을 분리 가능

### 8.2 처분 이벤트 정의

2027 과세 엔진에서 처분으로 볼 후보:

- KRW 매도
- 스테이블코인 매도
- 코인-코인 교환에서 넘겨준 자산
- 대여 또는 상환 구조 중 법상 처분으로 해석되는 항목

처분으로 보지 않는 후보:

- 동일인 소유 지갑 간 이동
- 단순 입금
- 단순 출금

단, 이 구분은 법 해석과 사실관계에 따라 달라질 수 있으므로 rule file에 고정값으로 넣는다.

### 8.3 취득원가 엔진

엔진은 두 가지 계산 방식을 모두 지원해야 한다.

- 이동평균법
- 선입선출법

필요한 내부 모델:

- asset별 lot queue
- acquisition timestamp
- acquisition quantity
- acquisition unit cost
- remaining quantity
- source event id

권장 내부 자료구조:

- `positions[account_ref][asset] -> list[Lot]`

### 8.4 2026-12-31 경과 규칙

2027 시행 전 보유자산에 대해서는 경과 규칙을 별도 적용할 수 있게 설계한다.

필요 필드:

- `actual_cost_basis`
- `deemed_cost_basis_2026_12_31`
- `applied_cost_basis`
- `cost_basis_rule`

원칙:

- 실제 취득가와 2026-12-31 시가 중 어느 값을 적용했는지 추적 가능해야 함

### 8.5 공제 및 세액 계산

세무 엔진 출력 예시:

- `gross_disposal_gain`
- `allowable_expense`
- `net_virtual_asset_income`
- `basic_deduction_applied`
- `taxable_income_after_deduction`
- `estimated_tax`
- `estimated_local_tax`

중요:

- 현재는 이 계산을 기본 비활성화
- `tax_year >= 2027`일 때만 명시적으로 활성화


## 9. 내부이체 식별 로직

현재 CoinMoa에서 가장 실무 가치가 큰 기능 중 하나.

목표:

- 동일인 지갑 이동을 과세 이벤트에서 제외
- 수수료만 비용 또는 자산 감소로 분리

매칭 기준 후보:

- 동일 자산
- 유사 시간대
- 유사 수량
- 송금 수수료 반영 허용 오차
- 주소 book 또는 사용자 등록 지갑

권장 컬럼:

- `transfer_match_id`
- `matched_from_event_id`
- `matched_to_event_id`
- `match_confidence`
- `match_rule`

운영 정책:

- 고신뢰만 자동 매칭
- 애매한 건 `manual_review`


## 10. 수동 검토가 필요한 이벤트

아래는 기본적으로 자동 확정하지 않는다.

- 에어드랍
- 이벤트 지급
- 추천인 보상
- 스테이킹/예치 이자
- 브리지 민트/번
- 파생상품 PnL 반영 방식이 불명확한 경우
- 거래소 내부 transfer와 외부 transfer를 구분 못한 경우

출력 예시:

- `outputs/reports/manual_review_items.csv`

필수 표시값:

- 원본 거래소
- 원본 타입
- 추정 분류
- 불확실 사유
- 필요한 사용자 확인 항목


## 11. 권장 구현 순서

### Phase 1. 지금 바로 구현

1. `canonical timeline` 유지
2. `normalized_ledger` 생성기 추가
3. 내부이체 매칭 추가
4. 월말 잔액 스냅샷 생성
5. 해외금융계좌 신고 보조 리포트 생성

### Phase 2. 현재 법 적용 기능

1. 상속·증여 평가용 가격 계산기
2. 기준일 valuation report 생성
3. 수동 검토 항목 분리

### Phase 3. 2027 대비

1. 취득 lot 엔진 추가
2. FIFO/이동평균법 동시 지원
3. 처분 이벤트 판정기 추가
4. 2026-12-31 경과규칙 반영
5. 세액 시뮬레이터 추가


## 12. 권장 파일 구조

예시:

```text
CoinMoa/
├── unified_txlog.py
├── tax_ledger.py
├── tax_rules_kr.py
├── tax_engine.py
├── valuation_kr.py
├── reports_tax.py
├── TAX_DESIGN.md
└── outputs/
    ├── raw/
    ├── ledger/
    └── reports/
```

파일 역할:

- `tax_ledger.py`: canonical timeline -> normalized ledger 변환
- `tax_rules_kr.py`: 한국 규칙과 rule version 정의
- `tax_engine.py`: lot 계산, 처분 판정, 손익 산출
- `valuation_kr.py`: 상속·증여 및 월말 평가
- `reports_tax.py`: 세무 보조용 CSV 출력


## 13. 최소 구현 규칙

실제 구현 시 아래 규칙을 지킨다.

- 세무 계산은 기본적으로 off
- 결과에는 항상 `rule_version`을 기록
- 사람이 확인해야 하는 항목은 숨기지 않고 드러냄
- 수수료는 반드시 별도 필드로 보존
- 내부이체는 과세 제외와 원가 이전을 분리해 표현
- 가격 소스와 환율 소스를 결과물에 남김


## 14. 당장 적용할 결론

현재 CoinMoa에 먼저 붙일 기능은 아래 3개다.

1. `normalized_ledger`
2. `월말 잔액 / 해외금융계좌 신고 보조 리포트`
3. `상속·증여 평가 보조 리포트`

보류할 기능은 아래다.

1. 자동 세액 확정 계산
2. 에어드랍/보상성 자산 자동 과세 분류
3. 법 해석이 필요한 소득 분류 자동화

즉, 지금의 제품 방향은 "세금 계산기"보다 "세무 증빙 엔진"이 맞다.


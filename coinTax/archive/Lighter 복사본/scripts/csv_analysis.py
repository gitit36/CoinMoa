"""CSV analysis utility and inferred schema reporting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class CSVAnalysisResult:
    row_count: int
    columns: list[str]
    dtypes: dict[str, str]
    missing: dict[str, int]
    categorical_uniques: dict[str, list[Any]]
    inferred_schema: dict[str, str]
    issues: list[str]
    data_dictionary: dict[str, str]


def analyze_csv(path: str, top_n: int = 10) -> tuple[pd.DataFrame, CSVAnalysisResult]:
    """Analyze reference CSV and return structured findings."""
    df = pd.read_csv(path)

    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    missing = {c: int(v) for c, v in df.isna().sum().items()}

    categorical_uniques: dict[str, list[Any]] = {}
    for c in df.columns:
        if df[c].dtype == object or df[c].nunique(dropna=True) <= 25:
            vals = df[c].value_counts(dropna=False).head(top_n).index.tolist()
            categorical_uniques[c] = vals

    issues: list[str] = []
    dup_full = int(df.duplicated().sum())
    if dup_full:
        issues.append(f"Fully duplicated rows: {dup_full}")
    dup_key = int(df.duplicated(subset=["일시", "유형", "페어", "가격", "원화가치"]).sum()) if set(["일시", "유형", "페어", "가격", "원화가치"]).issubset(df.columns) else 0
    if dup_key:
        issues.append(f"Potential duplicate fills by key(timestamp,type,pair,price,value): {dup_key}")

    if "유형" in df.columns:
        known = set(df["유형"].dropna().astype(str).unique().tolist())
        if "입금" not in known and "출금" not in known:
            issues.append("No explicit deposit/withdraw labels found; transfer-only rows are ambiguous for cashflow.")

    if "통화" in df.columns and int(df["통화"].isna().sum()) == len(df):
        issues.append("Column '통화' is fully null and carries no information.")

    inferred_schema = {
        "timestamp": "일시",
        "exchange": "거래소",
        "event_type": "유형 (매수/매도/청산/이체)",
        "instrument": "페어",
        "trade_price": "가격",
        "fiat_value": "원화가치",
        "fx_rate": "적용환율",
        "cashflow": "유형='이체' (deposit/withdraw direction missing)",
        "realized_unrealized_pnl": "not present directly in this CSV",
        "fees": "not present directly in this CSV",
        "airdrop_token_received": "not explicit; must infer from external API/account logs",
        "token_sell_events": "rows with 페어 containing LIT and 유형='매도'",
    }

    data_dictionary = {
        "Unnamed: 0": "Row index from previous export",
        "일시": "Event timestamp, format YYYY-MM-DD-HH-MM-SS",
        "거래소": "Exchange/source label from original exporter",
        "유형": "Event category (buy/sell/liquidation/transfer)",
        "페어": "Instrument or market identifier",
        "통화": "Currency code field (unused in this dataset)",
        "가격": "Execution/transaction price in quote currency",
        "원화가치": "KRW notional value (typically quote_notional * fx_rate)",
        "적용환율": "FX conversion rate applied to KRW value",
    }

    result = CSVAnalysisResult(
        row_count=len(df),
        columns=list(df.columns),
        dtypes=dtypes,
        missing=missing,
        categorical_uniques=categorical_uniques,
        inferred_schema=inferred_schema,
        issues=issues,
        data_dictionary=data_dictionary,
    )
    return df, result

"""Environment-driven configuration (read-only; no key mutation)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    explorer_base_url: str = os.getenv("EXPLORER_BASE_URL", "https://explorer.elliot.ai").rstrip("/")

    account_index: int = int(os.getenv("ACCOUNT_INDEX", "0") or "0")
    l1_address: str = os.getenv("L1_ADDRESS", "").strip()

    read_only_auth_token: str = os.getenv("READ_ONLY_AUTH_TOKEN", "").strip()
    api_key_index: int = int(os.getenv("API_KEY_INDEX", "3") or "3")
    api_key_private_key: str = os.getenv("API_KEY_PRIVATE_KEY", "").strip()

    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20") or "20")
    max_retries: int = int(os.getenv("MAX_RETRIES", "6") or "6")
    backoff_base_seconds: float = float(os.getenv("BACKOFF_BASE_SECONDS", "0.8") or "0.8")
    rate_limit_sleep_seconds: float = float(os.getenv("RATE_LIMIT_SLEEP_SECONDS", "0.12") or "0.12")

    page_limit: int = int(os.getenv("PAGE_LIMIT", "200") or "200")
    max_pages: int = int(os.getenv("MAX_PAGES", "1500") or "1500")
    fx_rate: float = float(os.getenv("FX_RATE", "1300") or "1300")


SETTINGS = Settings()


def get_settings() -> Settings:
    """Return immutable runtime settings."""
    return SETTINGS


# Backward-compatible module constants for legacy clients.
BASE_URL = SETTINGS.base_url
EXPLORER_BASE_URL = SETTINGS.explorer_base_url

ACCOUNT_INDEX = SETTINGS.account_index
L1_ADDRESS = SETTINGS.l1_address

READ_ONLY_AUTH_TOKEN = SETTINGS.read_only_auth_token
API_KEY_INDEX = SETTINGS.api_key_index
API_KEY_PRIVATE_KEY = SETTINGS.api_key_private_key

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "").strip()
KOREAEXIM_API_KEY = os.getenv("KOREAEXIM_API_KEY", "").strip()

EDGEX_BASE_URL = os.getenv("EDGEX_BASE_URL", "https://pro.edgex.exchange").strip()
EDGEX_ACCOUNT_ID = os.getenv("EDGEX_ACCOUNT_ID", "").strip()
EDGEX_STARK_PRIVATE_KEY = os.getenv("EDGEX_STARK_PRIVATE_KEY", "").strip()


def get_auth_required() -> bool:
    """Whether authenticated endpoints can be called."""
    return bool(READ_ONLY_AUTH_TOKEN or API_KEY_PRIVATE_KEY)

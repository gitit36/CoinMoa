"""Backward-compatible wrapper for minute price collector."""
from scripts.collect_usdt_krw_minute_price import *  # noqa: F401,F403
from scripts.collect_usdt_krw_minute_price import main


if __name__ == "__main__":
    main()

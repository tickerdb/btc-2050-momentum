"""
BTC 2050 Momentum: the rules, and the TickerDB data they run on.

Rules, decided only at each daily close (00:00 UTC):
  1. Buy when the 50-day SMA is rising, the 20-day SMA rose at least 0.05%
     since yesterday, and BTC closes above the 50-day SMA.
  2. Sell when the 20-day SMA fell at least 0.1% since yesterday. Go short only
     if BTC also closes below the 50-day SMA; otherwise wait in cash.
  3. Cover the short at a daily close 7.5% in its favour, or on the next buy
     signal. No stop: shorts only open below the 50-day SMA, and in the backtest
     no short ever reached 10% against it before one of those exits.
  4. After a take-profit, wait in cash for the next buy.
  5. 1x, no leverage. In the backtest, orders fill at the next daily open.

Used by backtest.py (history since 2019) and run.py (today's decision).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://api.tickerdb.com/v1"
TICKER = "BTCUSD"

# Parameters
ENTRY_BAND = 0.0005  # 20-day SMA must rise at least 0.05% since yesterday to buy
EXIT_BAND = 0.001    # 20-day SMA must fall at least 0.1% since yesterday to sell and short
TAKE_PROFIT = 0.075  # cover a short at a close 7.5% in its favour


# ---------------------------------------------------------------- data
def api_key() -> str:
    key = os.environ.get("TICKERDB_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set TICKERDB_API_KEY (free key: see https://tickerdb.com/setup).")
    return key


def get(path: str, params: dict | None = None) -> dict:
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key()}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_daily(start: str, end: str | None = None) -> list[dict]:
    """BTCUSD daily rows from TickerDB: open/high/low/close and the 20- and 50-day SMAs,
    oldest first. One /v1/history request (about 2 credits per 50 days)."""
    params = {
        "tickers": TICKER,
        "timeframe": "daily",
        "fields": "trend_ma20_price,trend_ma50_price",
        "ohlcv": "true",
        "start": start,
    }
    if end:
        params["end"] = end
    rows: list[dict] = []
    page = get("/history", params)
    tokens = list(page.get("page_tokens") or [])
    while True:
        rows += page.get("rows", [])
        if page.get("next_page_token"):
            page = get("/history", {**params, "page_token": page["next_page_token"]})
        elif tokens:
            page = get("/history", {**params, "page_token": tokens.pop(0)})
        else:
            break
    out = [
        {
            "date": r["date"],
            "open": float(r["ohlcv_open"]),
            "high": float(r["ohlcv_high"]),
            "low": float(r["ohlcv_low"]),
            "close": float(r["ohlcv_close"]),
            "ma20": None if r.get("trend_ma20_price") is None else float(r["trend_ma20_price"]),
            "ma50": None if r.get("trend_ma50_price") is None else float(r["trend_ma50_price"]),
        }
        for r in rows
        if r.get("ohlcv_close") is not None
    ]
    out.sort(key=lambda r: r["date"])
    return out


def latest_published_day() -> str | None:
    """The newest crypto date TickerDB has published (GET /v1/status, free)."""
    status = get("/status")
    return (((status.get("timeframes") or {}).get("daily") or {}).get("asset_classes") or {}).get("crypto", {}).get("date")


# ---------------------------------------------------------------- signals
def change(rows: list[dict], i: int, key: str) -> float | None:
    """Day-over-day change of an SMA at row i, as a fraction."""
    if i < 1 or rows[i][key] is None or rows[i - 1][key] in (None, 0):
        return None
    return rows[i][key] / rows[i - 1][key] - 1


def buy_signal(rows: list[dict], i: int) -> bool:
    c20, c50, ma50 = change(rows, i, "ma20"), change(rows, i, "ma50"), rows[i]["ma50"]
    return c20 is not None and c50 is not None and ma50 is not None and c50 > 0 and c20 > ENTRY_BAND and rows[i]["close"] > ma50


def sell_signal(rows: list[dict], i: int) -> bool:
    c20 = change(rows, i, "ma20")
    return c20 is not None and c20 < -EXIT_BAND


@dataclass
class Position:
    side: str = "cash"         # "long", "short" or "cash"
    entry_price: float = 0.0
    entry_date: str = ""


def decide(rows: list[dict], i: int, pos: Position) -> tuple[list[str], str]:
    """What to do after the close of row i, given the current position.
    Returns the actions in order and the side to hold afterwards."""
    close = rows[i]["close"]
    actions: list[str] = []
    side = pos.side
    if side == "short":
        if close <= pos.entry_price * (1 - TAKE_PROFIT):
            actions.append("cover short (take profit)")
            side = "cash"
    if side == "long" and sell_signal(rows, i):
        # Short only once BTC is below its 50-day SMA; a dip while it's still above is
        # usually a pullback in an uptrend, so sell and wait in cash instead.
        ma50 = rows[i]["ma50"]
        if ma50 is not None and close < ma50:
            actions += ["sell long", "open short"]
            side = "short"
        else:
            actions.append("sell long")
            side = "cash"
    elif side == "short" and buy_signal(rows, i):
        actions += ["cover short (buy signal)", "buy"]
        side = "long"
    elif side == "cash" and buy_signal(rows, i):
        actions.append("buy")
        side = "long"
    return actions, side

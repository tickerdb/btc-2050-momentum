"""
Run BTC 2050 Momentum for today: what to do after the latest daily close.

    export TICKERDB_API_KEY=tdb_...      # free key: https://tickerdb.com/setup
    python run.py

Schedule it once a day, after TickerDB publishes the day that just closed
(a BTC day closes at 00:00 UTC; TickerDB publishes it at about 04:10 UTC), for
example 04:30 UTC. Each run:

  1. Checks GET /v1/status (free). If yesterday's (UTC) day is not published
     yet, it exits with code 75 so your scheduler can retry in 15 minutes.
  2. Fetches the last 10 days of BTCUSD from /v1/history, fresh every run
     (about 2 credits; daily runs fit the free plan's 250 credits a month).
  3. Applies the rules to the newest day, given the position in state.json,
     prints what to do, and saves the new position.

It never places orders: it tells you (or your agent) what the model does.
A day is only decided once; running twice on the same day does nothing new.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from model import TICKER, Position, decide, fetch_daily, latest_published_day

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
NOT_READY = 75  # EX_TEMPFAIL: try again later


def load_state() -> tuple[Position, str]:
    if STATE.exists():
        s = json.loads(STATE.read_text())
        return Position(s.get("side", "cash"), float(s.get("entry_price", 0)), s.get("entry_date", "")), s.get("last_decided", "")
    return Position(), ""


def save_state(pos: Position, day: str) -> None:
    STATE.write_text(json.dumps({"side": pos.side, "entry_price": pos.entry_price, "entry_date": pos.entry_date,
                                 "last_decided": day}, indent=2) + "\n")


def main() -> int:
    just_closed = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    published = latest_published_day()
    if not published or published < just_closed:
        print(f"TickerDB has not published {just_closed} yet (latest: {published}). Try again in 15 minutes.")
        return NOT_READY

    start = (datetime.fromisoformat(just_closed) - timedelta(days=10)).date().isoformat()
    rows = fetch_daily(start)
    if not rows or rows[-1]["date"] < just_closed:
        print(f"No {TICKER} row for {just_closed} yet. Try again in 15 minutes.")
        return NOT_READY

    pos, last_decided = load_state()
    day = rows[-1]["date"]
    if day <= last_decided:
        print(f"{day} was already decided. Position: {pos.side}" + (f" since {pos.entry_date} at ${pos.entry_price:,.0f}" if pos.side != "cash" else ""))
        return 0

    i = len(rows) - 1
    close = rows[i]["close"]
    actions, side = decide(rows, i, pos)
    if side != pos.side:
        # A new position enters at about today's price (the backtest fills at the next open, 00:00 UTC).
        pos = Position(side, close, day) if side != "cash" else Position()
    save_state(pos, day)

    print(f"{TICKER} close {day}: ${close:,.2f}")
    print("Action: " + (", then ".join(actions) if actions else "none, hold"))
    print(f"Position: {pos.side}" + (f" since {pos.entry_date} at ${pos.entry_price:,.0f}" if pos.side != "cash" else ""))
    if pos.side == "short":
        print(f"  take profit at a close <= ${pos.entry_price * 0.925:,.0f}, or cover on the next buy signal")
    return 0


if __name__ == "__main__":
    sys.exit(main())

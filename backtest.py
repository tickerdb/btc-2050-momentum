"""
Replay BTC 2050 Momentum's rules on TickerDB's BTCUSD daily data, 2019 to the end of the backtest: the
trades they make.

    export TICKERDB_API_KEY=tdb_...      # https://tickerdb.com/setup
    python backtest.py                   # fetch the data, then replay
    python backtest.py --offline         # replay again on the cached data/btcusd_daily.csv

Daily history from 2019 needs a TickerDB plan that includes it (Pro: 2019 on). The fetch is one
/v1/history request, about 90 credits; the result is cached in data/btcusd_daily.csv.

Point in time: a decision at a close uses only data up to that close, and the order fills at the next
daily open (00:00 UTC).

Writes results/replay-trades.csv (each trade's side, entry and exit with their fill prices) and checks
it against the published record (results/record.json, written by readme.py): the closed trades must be
exactly the same. The performance figures are the record's, valued at every daily close (readme.py);
this replay values nothing.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from model import Position, decide, fetch_daily

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "btcusd_daily.csv"
RESULTS = HERE / "results"
START = "2019-01-06"     # first decision
FETCH_FROM = "2019-01-01"


def end_date() -> str | None:
    """The published backtest's last day (results/record.json): the replay stops there."""
    record = RESULTS / "record.json"
    if not record.exists():
        return None
    return json.loads(record.read_text(encoding="utf-8"))["backtest"]["end"]


def load(offline: bool) -> list[dict]:
    if offline:
        if not CACHE.exists():
            raise SystemExit(f"No cached data at {CACHE}. Run without --offline first.")
        with CACHE.open() as f:
            rows = [{k: (v if k == "date" else (None if v == "" else float(v))) for k, v in row.items()}
                    for row in csv.DictReader(f)]
    else:
        rows = fetch_daily(FETCH_FROM, end_date())
        CACHE.parent.mkdir(exist_ok=True)
        with CACHE.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "ma20", "ma50"])
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if r[k] is None else r[k]) for k in w.fieldnames})
    end = end_date()
    return [r for r in rows if end is None or r["date"] <= end]


def simulate(rows: list[dict]) -> list[dict]:
    """Trades: each {side, entry_date, entry_price, exit_date, exit_price, reason}; a trade still open at
    the last row has no exit."""
    trades: list[dict] = []
    pos = Position()
    cur: dict | None = None
    i0 = next(i for i, r in enumerate(rows) if r["date"] >= START)
    for i in range(i0, len(rows) - 1):
        fill_date, fill_price = rows[i + 1]["date"], rows[i + 1]["open"]
        actions, side = decide(rows, i, pos)
        for a in actions:
            if a.startswith(("cover", "sell")) and cur:
                cur.update(exit_date=fill_date, exit_price=fill_price, reason=a)
                trades.append(cur)
                cur = None
            elif a in ("buy", "open short"):
                cur = {"side": "long" if a == "buy" else "short", "entry_date": fill_date, "entry_price": fill_price}
        pos = Position(side, cur["entry_price"], cur["entry_date"]) if cur else Position()
    if cur:
        trades.append({**cur, "exit_date": None, "exit_price": None, "reason": "open"})
    return trades


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--offline", action="store_true", help="use data/btcusd_daily.csv instead of fetching")
    args = ap.parse_args()

    rows = load(args.offline)
    trades = simulate(rows)
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "replay-trades.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["side", "entry_date", "entry_price", "exit_date", "exit_price", "reason"])
        for t in trades:
            w.writerow([t["side"], t["entry_date"], t["entry_price"], t["exit_date"] or "",
                        "" if t["exit_price"] is None else t["exit_price"], t["reason"]])
    closed = [t for t in trades if t["exit_date"]]
    live = next((t for t in trades if not t["exit_date"]), None)
    print(f"Replayed {rows[0]['date']} to {rows[-1]['date']}: {len(closed)} closed trades "
          f"({sum(t['side'] == 'long' for t in closed)} long, {sum(t['side'] == 'short' for t in closed)} short), "
          f"holding now: {live['side'] if live else 'cash'}.")
    print("Wrote results/replay-trades.csv.")
    import readme
    if readme.RECORD.exists():
        problems = readme.replay_differences(readme.load())
        if problems:
            print("MISMATCH:", *problems)
            raise SystemExit(1)
        print("The replay makes exactly the published record's trades.")


if __name__ == "__main__":
    main()

"""
What the model holds now, from TickerDB: its newest book (GET /v1/models/{slug}/holdings, every plan,
1 credit). run.py starts from it the first time it runs (no state.json), so you begin with the
position the model actually has, not from cash.

A book row is `held` (in the book at that close), `exiting` (held now, sold or covered at the next
open) or `entering` (decided at that close, bought or shorted at the next open: no entry yet).
"""
from __future__ import annotations

from typing import Callable, Optional


def fetch(get: Callable[[str], dict], slug: str) -> Optional[dict]:
    """{"date", "holdings"} of the model's newest book, or None when TickerDB cannot give it."""
    try:
        book = get(f"/models/{slug}/holdings")
    except (SystemExit, Exception) as error:     # an HTTP or network error, however get() reports it
        print(f"Could not read the model's current book ({error}); starting from cash.")
        return None
    if not book.get("date"):
        return None
    return {"date": book["date"], "holdings": list(book.get("holdings") or [])}


def after_next_open(book: dict) -> list[dict]:
    """The positions held once the next open's orders are filled: held and entering rows, not exiting ones."""
    return [h for h in book["holdings"] if h.get("position_state") in ("held", "entering")]


def describe(h: dict) -> str:
    """One line for a book row, e.g. "short NVDA since 2026-11-05 at $196.07 (+25.3% at the close)"."""
    side, ticker = h.get("side", "long"), h.get("ticker", "?")
    if h.get("position_state") == "entering":
        return f"{'short' if side == 'short' else 'buy'} {ticker} at the next open"
    text = f"{side} {ticker}"
    if h.get("entry_date"):
        text += f" since {h['entry_date']}"
    if h.get("entry_price") is not None:
        text += f" at ${float(h['entry_price']):,.2f}"
    if h.get("return_pct") is not None:
        text += f" ({float(h['return_pct']):+.1f}% at the close)"
    if h.get("position_state") == "exiting":
        text += f", {'covered' if side == 'short' else 'sold'} at the next open"
    return text


def show(book: dict, cash: str = "cash") -> None:
    """Print the book as run.py's first lines."""
    rows = book["holdings"]
    print(f"Starting from the model's book at the close of {book['date']}:")
    for h in rows:
        print(f"  {describe(h)}")
    if not rows:
        print(f"  nothing held ({cash})")

"""Offline tests of how run.py starts from the model's current book.   python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import book  # noqa: E402
import run  # noqa: E402
from model import Position  # noqa: E402

LONG = {"ticker": "BTCUSD", "side": "long", "position_state": "held", "entry_date": "2026-11-10",
        "entry_price": 104000.0, "price": 101000.0, "return_pct": -3.0}
ROWS = [{"date": "2026-11-19", "close": 92000.0}]


class StartFromTheBook(unittest.TestCase):
    def test_a_held_position_is_the_starting_state(self):
        pos, decided = run.from_book({"date": "2026-11-19", "holdings": [LONG]}, ROWS)
        self.assertEqual((pos, decided), (Position("long", 104000.0, "2026-11-10"), "2026-11-19"))
        self.assertEqual(run.describe(pos), "long since 2026-11-10 at $104,000")

    def test_a_side_decided_at_the_close_enters_at_that_close(self):
        exiting = {**LONG, "position_state": "exiting"}
        entering = {"ticker": "BTCUSD", "side": "short", "position_state": "entering"}
        pos, _ = run.from_book({"date": "2026-11-19", "holdings": [exiting, entering]}, ROWS)
        self.assertEqual(pos, Position("short", 92000.0, "2026-11-19"))

    def test_an_empty_book_or_none_starts_in_cash(self):
        self.assertEqual(run.from_book({"date": "2026-11-19", "holdings": []}, ROWS), (Position(), "2026-11-19"))
        self.assertEqual(run.from_book(None, ROWS), (Position(), ""))

    def test_fetch_falls_back_to_cash_on_an_api_error(self):
        def refused(path):
            raise OSError("HTTP Error 403")
        self.assertIsNone(book.fetch(refused, "btc-2050-momentum"))


if __name__ == "__main__":
    unittest.main()

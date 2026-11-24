import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proof"))
from collateral_card import x402
from collateral_card.demo import _http_get, _start_x402_server, _RemoteWriteCounter
from collateral_card.paid_quote import weekend_quote


class QuoteTest(TestCase):
    def test_real_prices_and_observation_window(self):
        quote = weekend_quote("NVDAc", "2026-11-06", "2026-11-09T00:05:00Z")
        self.assertEqual(quote["lending_price_usd"], "187.96606001")
        self.assertEqual(quote["pool_close_usd"], "178.46556282635999")
        self.assertEqual(quote["pool_minus_lending_percent"], "-5.05")
        self.assertEqual(quote["pool_close_at_utc"], "2026-11-09T00:00:00Z")
        self.assertEqual(datetime.fromisoformat(quote["as_of_utc"]).minute, 5)
        for at in ("2026-11-08T23:59:59Z", "2026-11-09T01:00:33Z", "2026-11-09T00:05:00"):
            with self.subTest(at=at), self.assertRaises(ValueError):
                weekend_quote("NVDAc", "2026-11-06", at)
        with self.assertRaises(ValueError):
            weekend_quote("????", "2026-11-06", "2026-11-09T00:05:00Z")

    def test_quote_requests_are_checked_before_asking_for_payment(self):
        payee = "0x0000000000000000000000000000000000000001"
        terms = x402.requirements(payee, 50000)
        server, base = _start_x402_server(
            "http://127.0.0.1:1", payee, terms, _RemoteWriteCounter()
        )
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        status, body, _ = _http_get(base + "/quote")
        self.assertEqual(status, 402)
        self.assertNotIn("lending_price_usd", json.loads(body))
        status, _, headers = _http_get(base + "/quote?stock=AAPLc")
        self.assertEqual(status, 404)
        self.assertIsNone(next((value for key, value in headers.items()
                                if key.lower() == "payment-required"), None))
        with patch("collateral_card.demo._block_timestamp", return_value=100):
            status, _, _ = _http_get(base + "/quote", {"PAYMENT-SIGNATURE": x402.encode_header({
                "x402Version": 2, "accepted": ["bad"], "payload": ["bad"],
            })})
        self.assertEqual(status, 402)

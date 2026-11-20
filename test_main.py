import tempfile
import unittest
from pathlib import Path

from main import Monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "events.sqlite3")
        self.monitor = Monitor(self.db)

    def tearDown(self):
        self.monitor.close()
        self.tmp.cleanup()

    def test_fresh_quote_does_not_open_incident(self):
        result = self.monitor.process(
            {"type": "quote", "symbol": "AAPL", "market_timestamp": 100.5}, now=101
        )
        self.assertIsNone(result["incident"])
        self.assertFalse(result["local_trading_paused"])
        self.assertEqual(self.monitor.incident_count(), 0)

    def test_stale_quote_creates_incident_and_persistent_pause(self):
        result = self.monitor.process(
            {"type": "quote", "symbol": "AAPL", "market_timestamp": 98}, now=101
        )
        self.assertEqual(result["incident"]["severity"], "HIGH")
        self.assertTrue(result["local_trading_paused"])
        self.assertIn("Investigate incident", result["incident"]["suggested_devin_task"])
        self.monitor.close()
        self.monitor = Monitor(self.db)
        self.assertTrue(self.monitor.paused)

    def test_position_mismatch_opens_incident(self):
        result = self.monitor.process(
            {"type": "position_reconciliation", "expected_qty": 0, "actual_qty": 1}, now=101
        )
        self.assertIn("Position mismatch", result["incident"]["reason"])
        self.assertEqual(self.monitor.incident_count(), 1)

    def test_matching_position_no_incident(self):
        result = self.monitor.process(
            {"type": "position_reconciliation", "expected_qty": 1, "actual_qty": 1}, now=101
        )
        self.assertIsNone(result["incident"])

    def test_broker_error_opens_incident(self):
        result = self.monitor.process({"type": "broker_error", "code": "429"}, now=101)
        self.assertIn("429", result["incident"]["reason"])

    def test_unknown_event_rejected(self):
        with self.assertRaises(ValueError):
            self.monitor.process({"type": "place_live_order", "symbol": "AAPL"})


if __name__ == "__main__":
    unittest.main()

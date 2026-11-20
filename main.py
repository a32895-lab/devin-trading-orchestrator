#!/usr/bin/env python3
"""A standard-library-only, paper-only trading incident monitor.

This project does NOT place orders, connect to a broker or operate Devin by
itself. It generates structured incidents that can be handed to an automation.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STALE_AFTER_SECONDS = 2.0
ALLOWED_EVENTS = {"quote", "broker_error", "position_reconciliation"}


class Monitor:
    def __init__(self, db_path: str = "trading_events.sqlite3") -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                severity TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self.conn.commit()

    @property
    def paused(self) -> bool:
        row = self.conn.execute("SELECT value FROM state WHERE key = 'paused'").fetchone()
        return bool(row and row["value"] == "true")

    def process(self, event: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        """Persist an event, detect an incident and set the *local* safety flag."""
        if not isinstance(event, dict) or event.get("type") not in ALLOWED_EVENTS:
            raise ValueError(f"event.type must be one of {sorted(ALLOWED_EVENTS)}")
        now = time.time() if now is None else now
        event_type = event["type"]
        reason: str | None = None

        if event_type == "quote":
            timestamp = float(event["market_timestamp"])
            if now - timestamp > STALE_AFTER_SECONDS:
                reason = f"Stale quote: {now - timestamp:.2f}s old"
            elif timestamp - now > STALE_AFTER_SECONDS:
                reason = f"Clock skew: quote is {timestamp - now:.2f}s in the future"
        elif event_type == "broker_error":
            reason = f"Broker API error: {event.get('code', 'UNKNOWN')}"
        elif event_type == "position_reconciliation":
            expected = float(event["expected_qty"])
            actual = float(event["actual_qty"])
            if abs(expected - actual) > 1e-9:
                reason = f"Position mismatch: expected={expected:g}, actual={actual:g}"

        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO events(event_type, payload, received_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(event, ensure_ascii=False, sort_keys=True), now),
            )
            event_id = cursor.lastrowid
            incident_id = None
            if reason is not None:
                incident_id = self.conn.execute(
                    "INSERT INTO incidents(event_id, severity, reason, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, "HIGH", reason, now),
                ).lastrowid
                # Local demonstration state only; NOT a broker-side kill switch.
                self.conn.execute(
                    "INSERT INTO state(key, value) VALUES('paused', 'true') "
                    "ON CONFLICT(key) DO UPDATE SET value='true'"
                )

        result: dict[str, Any] = {
            "event_id": event_id,
            "event_type": event_type,
            "local_trading_paused": self.paused,
            "incident": None,
        }
        if incident_id is not None:
            result["incident"] = {
                "id": incident_id,
                "severity": "HIGH",
                "reason": reason,
                "suggested_devin_task": (
                    f"Investigate incident {incident_id}: {reason}. "
                    "Inspect logs, identify root cause, propose a fix and tests. "
                    "Do not deploy or change live risk limits."
                ),
            }
        return result

    def incident_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def close(self) -> None:
        self.conn.close()


def post_webhook(url: str, result: dict[str, Any]) -> None:
    """Opt-in generic JSON webhook. Target endpoint/auth is user-configured."""
    payload = json.dumps(result).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        if not (200 <= response.status < 300):
            raise RuntimeError(f"Webhook failed with HTTP {response.status}")


def demo_events(now: float) -> list[dict[str, Any]]:
    return [
        {"type": "quote", "symbol": "AAPL", "market_timestamp": now - 0.2},
        {"type": "quote", "symbol": "AAPL", "market_timestamp": now - 3.2},
        {"type": "position_reconciliation", "symbol": "AAPL", "expected_qty": 0, "actual_qty": 1},
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only trading incident monitor")
    parser.add_argument("--db", default="trading_events.sqlite3", help="SQLite file path")
    parser.add_argument("--event", type=Path, help="JSON file containing one event")
    parser.add_argument("--webhook-url", default=os.environ.get("INCIDENT_WEBHOOK_URL", ""),
                        help="Optional generic HTTPS endpoint for incident notifications")
    args = parser.parse_args(argv)

    monitor = Monitor(args.db)
    try:
        now = time.time()
        if args.event:
            events = [json.loads(args.event.read_text(encoding="utf-8"))]
        else:
            print("[DEMO] Simulated events only. No brokerage/Devin access.")
            events = demo_events(now)

        for event in events:
            result = monitor.process(event, now=now)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["incident"] and args.webhook_url:
                try:
                    post_webhook(args.webhook_url, result)
                    print("[WEBHOOK] Incident sent to configured endpoint")
                except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
                    print(f"[WEBHOOK ERROR] {exc}", file=sys.stderr)
                    # Incident is still stored locally even if notification fails.
        print(f"\nIncidents stored: {monitor.incident_count()}")
        print(f"Local trading pause flag: {monitor.paused}")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    finally:
        monitor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

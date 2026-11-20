#!/usr/bin/env python3
"""Read-only Alpaca Paper Trading API integration.

Only two authenticated GET endpoints are allowed. No order endpoints are
implemented. Redirects are blocked to avoid forwarding API credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from main import Monitor

PAPER_API_BASE = "https://paper-api.alpaca.markets"
_MAX_RESPONSE_BYTES = 1024 * 1024


class PaperAPIError(Exception):
    """Sanitized error. Never contains keys, account IDs, or response bodies."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PaperAlpacaClient:
    def __init__(self, key_id: str, secret_key: str, timeout: int = 15):
        if not key_id or not secret_key:
            raise ValueError("Missing Alpaca PAPER API credentials")
        self._key_id = key_id.strip()
        self._secret_key = secret_key.strip()
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _get(self, path: str) -> Any:
        if path not in ("/v2/account", "/v2/positions"):
            raise ValueError("Only account and positions GET paths are allowed")
        tag = "ACCOUNT" if path == "/v2/account" else "POSITIONS"
        request = Request(
            PAPER_API_BASE + path,
            headers={
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
                "User-Agent": "devin-trading-orchestrator-paper-readonly/2.0",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                if status != 200:
                    raise PaperAPIError(f"HTTP_{status}_{tag}")
                content_type = response.headers.get("Content-Type", "").lower()
                media_type = content_type.split(";", 1)[0].strip()
                if media_type != "application/json" and not media_type.endswith("+json"):
                    raise PaperAPIError(f"UNEXPECTED_CONTENT_TYPE_{tag}")
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise PaperAPIError(f"RESPONSE_TOO_LARGE_{tag}")
                try:
                    return json.loads(raw)
                except (ValueError, UnicodeError):
                    raise PaperAPIError(f"INVALID_JSON_{tag}") from None
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                raise PaperAPIError(f"REDIRECT_BLOCKED_{tag}") from None
            raise PaperAPIError(f"HTTP_{exc.code}_{tag}") from None
        except (URLError, TimeoutError, OSError):
            raise PaperAPIError(f"NETWORK_ERROR_{tag}") from None

    def get_account(self) -> dict[str, Any]:
        account = self._get("/v2/account")
        if not isinstance(account, dict) or "status" not in account:
            raise PaperAPIError("INVALID_ACCOUNT_RESPONSE")
        return account

    def get_positions(self) -> list[dict[str, Any]]:
        positions = self._get("/v2/positions")
        if not isinstance(positions, list) or not all(
            isinstance(p, dict) and "symbol" in p and "qty" in p for p in positions
        ):
            raise PaperAPIError("INVALID_POSITION_RESPONSE")
        return positions


def parse_quantities(positions: list[dict[str, Any]]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for p in positions:
        symbol = str(p["symbol"]).upper()
        try:
            qty = Decimal(str(p["qty"]))
        except (InvalidOperation, KeyError) as exc:
            raise PaperAPIError("INVALID_POSITION_QUANTITY") from exc
        if not qty.is_finite():
            raise PaperAPIError("INVALID_POSITION_QUANTITY")
        result[symbol] = qty
    return result


def load_expected(path: Path) -> dict[str, Decimal]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError('Expected positions must be a JSON object, e.g. {"AAPL": "0"}')
    expected: dict[str, Decimal] = {}
    for symbol, value in data.items():
        if not isinstance(symbol, str) or not symbol or not symbol.replace(".", "").isalnum():
            raise ValueError("Invalid symbol in expected positions")
        try:
            qty = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Invalid quantity in expected positions") from exc
        if not qty.is_finite():
            raise ValueError("Invalid quantity in expected positions")
        expected[symbol.upper()] = qty
    return expected


def check_positions(
    monitor: Monitor,
    actual: dict[str, Decimal],
    expected: dict[str, Decimal],
) -> list[dict[str, Any]]:
    """Compare PAPER positions with local expected-position quantities."""
    results = []
    for symbol in sorted(set(actual) | set(expected)):
        result = monitor.process({
            "type": "position_reconciliation",
            "symbol": symbol,
            "expected_qty": float(expected.get(symbol, 0)),
            "actual_qty": float(actual.get(symbol, 0)),
            "source": "alpaca_paper_readonly",
        })
        results.append({"symbol": symbol, "match": result["incident"] is None})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Alpaca Paper Trading API integration")
    parser.add_argument("--db", default="trading_events.sqlite3", help="Local SQLite file")
    parser.add_argument(
        "--expected", type=Path,
        help="Optional LOCAL expected-positions JSON file; creates incidents for mismatches",
    )
    args = parser.parse_args(argv)
    key_id = os.getenv("APCA_API_KEY_ID", "")
    secret = os.getenv("APCA_API_SECRET_KEY", "")
    if not key_id or not secret:
        print(
            "Missing PAPER credentials: set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
            "in the current terminal. Never commit or share these secrets.",
            file=sys.stderr,
        )
        return 2
    try:
        expected = load_expected(args.expected) if args.expected else None
    except (OSError, ValueError) as exc:
        print(f"Invalid expected positions file: {type(exc).__name__}", file=sys.stderr)
        return 2

    monitor = Monitor(args.db)
    try:
        client = PaperAlpacaClient(key_id, secret)
        account = client.get_account()
        positions = client.get_positions()
        quantities = parse_quantities(positions)
        summary: dict[str, Any] = {
            "integration": "ALPACA_PAPER_READ_ONLY",
            "endpoint": PAPER_API_BASE,
            "authenticated_api_calls": ["GET /v2/account", "GET /v2/positions"],
            "connection": "SUCCESS",
            "paper_account_status": str(account["status"]),
            "positions_count": len(positions),
            "orders_placed": 0,
        }
        if expected is not None:
            summary["reconciliation"] = check_positions(monitor, quantities, expected)
            summary["local_trading_paused"] = monitor.paused
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    except PaperAPIError as exc:
        monitor.process({"type": "broker_error", "code": exc.code, "source": "alpaca_paper"})
        print(f"Paper API connection failed: {exc.code}", file=sys.stderr)
        return 1
    finally:
        monitor.close()


if __name__ == "__main__":
    raise SystemExit(main())

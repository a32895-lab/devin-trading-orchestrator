#!/usr/bin/env python3
"""Safe, read-only diagnostic for Alpaca PAPER Trading HTTPS API.

Asks for credentials in masked prompts. Sends them only to the hardcoded Alpaca
paper API hostname. Never prints/saves credentials or full API response bodies.
Rejects redirects to avoid forwarding credentials to other hosts.
"""
from __future__ import annotations

import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://paper-api.alpaca.markets"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def classify_response(status: int, content_type: str, raw_body: bytes) -> str:
    if status != 200:
        return "ERROR (HTTP status is not 200)"
    try:
        obj = json.loads(raw_body)
    except (ValueError, UnicodeError):
        return "INVALID_JSON (server/network returned non-JSON content)"
    if isinstance(obj, dict):
        return "VALID_JSON_OBJECT"
    if isinstance(obj, list):
        return "VALID_JSON_ARRAY"
    return "VALID_JSON_OTHER"


def check(opener, path: str, key_id: str, secret: str) -> None:
    req = Request(
        BASE_URL + path,
        headers={
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": "alpaca-paper-diagnose-readonly/1.0",
        },
        method="GET",
    )
    print(f"\nEndpoint: {path}")
    try:
        with opener.open(req, timeout=15) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "(missing)")
            raw = response.read(1024 * 1024 + 1)
            print(f"HTTP status: {status}")
            print(f"Content-Type: {content_type}")
            if len(raw) > 1024 * 1024:
                print("Body check: TOO_LARGE (over 1 MiB; no body printed)")
            else:
                print(f"Body check: {classify_response(status, content_type, raw)}")
    except HTTPError as exc:
        print(f"HTTP status: {exc.code}")
        print(f"Content-Type: {exc.headers.get('Content-Type', '(missing)') if exc.headers else '(missing)'}")
        if 300 <= exc.code < 400:
            print("Body check: REDIRECT_BLOCKED (credentials were not forwarded)")
        elif exc.code == 401:
            print("Body check: UNAUTHORIZED (check PAPER key ID/secret pair)")
        elif exc.code == 403:
            print("Body check: FORBIDDEN (check account or API permissions)")
        else:
            print("Body check: HTTP_ERROR (no body printed)")
    except (URLError, OSError, TimeoutError) as exc:
        print(f"Network error type: {type(exc).__name__} (no response/body printed)")


def main() -> int:
    print("Alpaca PAPER API read-only diagnostics (GET only; NO orders)")
    print("Your keys are hidden when typed and are NOT saved to a file.")
    try:
        key = getpass.getpass("Paper API Key ID: ").strip()
        secret = getpass.getpass("Paper Secret Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 1
    if not key or not secret:
        print("One or both credentials are empty. No requests sent.")
        return 1
    opener = build_opener(NoRedirect())
    check(opener, "/v2/account", key, secret)
    check(opener, "/v2/positions", key, secret)
    print("\nFinished. You may share only the lines from 'Endpoint' onward.")
    print("Never share your API keys or the credential entry screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

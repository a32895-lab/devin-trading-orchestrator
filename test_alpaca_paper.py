"""Offline tests for the Paper adapter. No live trading or real keys are used."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from alpaca_paper import (
    PAPER_API_BASE, PaperAPIError, PaperAlpacaClient,
    check_positions, load_expected, main, parse_quantities,
)
from main import Monitor


class FakeResponse:
    def __init__(self, value=None, *, raw=None, status=200, content_type="application/json; charset=UTF-8"):
        self.data = io.BytesIO(raw if raw is not None else json.dumps(value).encode("utf-8"))
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self, size=-1):
        return self.data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.data.close()


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AlpacaPaperTests(unittest.TestCase):
    def make_client(self, responses):
        fake = FakeOpener(responses)
        with patch("alpaca_paper.build_opener", return_value=fake):
            client = PaperAlpacaClient(" paper_key ", " paper_secret ")
        return client, fake

    def test_only_paper_base_and_get(self):
        client, fake = self.make_client([FakeResponse({"status": "ACTIVE"})])
        status = client.get_account()
        self.assertEqual(status["status"], "ACTIVE")
        self.assertEqual(fake.requests[0].full_url, PAPER_API_BASE + "/v2/account")
        self.assertEqual(fake.requests[0].get_method(), "GET")
        self.assertEqual(fake.requests[0].get_header("Apca-api-key-id"), "paper_key")

    def test_no_order_endpoints(self):
        client, _ = self.make_client([])
        with self.assertRaises(ValueError):
            client._get("/v2/orders")

    def test_account_object_positions_array(self):
        client, fake = self.make_client([
            FakeResponse({"status": "ACTIVE"}),
            FakeResponse([{"symbol": "AAPL", "qty": "0.5"}]),
        ])
        self.assertEqual(client.get_account()["status"], "ACTIVE")
        self.assertEqual(str(parse_quantities(client.get_positions())["AAPL"]), "0.5")
        self.assertEqual(len(fake.requests), 2)

    def test_positions_empty_array(self):
        client, _ = self.make_client([FakeResponse([])])
        self.assertEqual(client.get_positions(), [])

    def test_http_error_sanitized(self):
        client, _ = self.make_client([HTTPError(PAPER_API_BASE, 401, "Auth failed", None, None)])
        with self.assertRaises(PaperAPIError) as exc:
            client.get_account()
        self.assertEqual(exc.exception.code, "HTTP_401_ACCOUNT")
        self.assertNotIn("paper_secret", str(exc.exception))

    def test_redirect_blocked(self):
        client, _ = self.make_client([HTTPError(PAPER_API_BASE, 302, "Found", None, None)])
        with self.assertRaises(PaperAPIError) as exc:
            client.get_account()
        self.assertEqual(exc.exception.code, "REDIRECT_BLOCKED_ACCOUNT")

    def test_html_response_gives_endpoint_error(self):
        client, _ = self.make_client([FakeResponse(raw=b"<html>proxy page</html>", content_type="text/html")])
        with self.assertRaises(PaperAPIError) as exc:
            client.get_account()
        self.assertEqual(exc.exception.code, "UNEXPECTED_CONTENT_TYPE_ACCOUNT")

    def test_invalid_json_gives_endpoint_error(self):
        client, _ = self.make_client([FakeResponse(raw=b"not valid JSON")])
        with self.assertRaises(PaperAPIError) as exc:
            client.get_positions()
        self.assertEqual(exc.exception.code, "INVALID_JSON_POSITIONS")

    def test_missing_keys_does_not_call_network(self):
        with patch.dict("alpaca_paper.os.environ", {}, clear=True):
            with patch("alpaca_paper.build_opener") as opener:
                with patch("sys.stderr", new_callable=io.StringIO):
                    rc = main(["--db", ":memory:"])
        self.assertEqual(rc, 2)
        opener.assert_not_called()

    def test_expected_positions_mismatch_sets_local_incident(self):
        with tempfile.TemporaryDirectory() as temp:
            monitor = Monitor(str(Path(temp) / "events.sqlite3"))
            try:
                path = Path(temp) / "expected_positions.local.json"
                path.write_text('{"AAPL": "0"}', encoding="utf-8")
                result = check_positions(monitor, {"AAPL": parse_quantities([{"symbol": "AAPL", "qty": "1"}])["AAPL"]}, load_expected(path))
                self.assertEqual(result, [{"symbol": "AAPL", "match": False}])
                self.assertTrue(monitor.paused)
            finally:
                monitor.close()

    def test_mock_success_redacts_sensitive_data(self):
        client, fake = self.make_client([
            FakeResponse({"status": "ACTIVE", "account_number": "secret_account"}),
            FakeResponse([]),
        ])
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("alpaca_paper.os.environ", {
                "APCA_API_KEY_ID": "paper_key", "APCA_API_SECRET_KEY": "paper_secret",
            }):
                with patch("alpaca_paper.build_opener", return_value=fake):
                    with patch("sys.stdout", new_callable=io.StringIO) as out:
                        rc = main(["--db", str(Path(temp) / "events.sqlite3")])
            self.assertEqual(rc, 0)
            body = out.getvalue()
            self.assertIn('"connection": "SUCCESS"', body)
            self.assertIn('"orders_placed": 0', body)
            self.assertNotIn("secret_account", body)
            self.assertNotIn("paper_secret", body)


if __name__ == "__main__":
    unittest.main()

# Alpaca Paper Trading — read-only API integration

This module makes **real authenticated HTTPS requests** to Alpaca's PAPER Trading API: `GET /v2/account` and `GET /v2/positions`.
It **cannot** place, cancel or modify orders. The API endpoint is hard-coded to `https://paper-api.alpaca.markets`, not the live trading server.

## What it proves (and what it doesn't)

- **Implemented:** real paper-API client (GET requests with API headers); credential checks; sanitized error logging to local SQLite incident monitor; optional position reconciliation against a local expected-position file.
- **Not proved until you run it with your own Paper keys:** that your account is connected successfully. Unit tests use **mock responses**, not Alpaca's server.
- **Not implemented:** live trading, auto-orders, market data streaming, Devin Bot, Slack automation, autonomous bug fixes or production-grade broker risk controls.

## Get an Alpaca Paper account

Official docs: https://docs.alpaca.markets/us/docs/paper-trading

Use a **Paper Trading** account and generate **Paper API keys**. Keys for live accounts are different. Never share keys in ChatGPT, screenshots, Slack or public GitHub.

## Windows CMD instructions

1. Open the folder containing `main.py` and `alpaca_paper.py` in File Explorer. Click the address bar, type `cmd`, and press Enter.
2. Run this command. It prompts for your credentials without echoing them in the terminal or storing them in command history:

```cmd
py -c "import os,getpass,runpy; os.environ['APCA_API_KEY_ID']=getpass.getpass('Paper API Key ID: ').strip(); os.environ['APCA_API_SECRET_KEY']=getpass.getpass('Paper Secret Key: ').strip(); runpy.run_path('alpaca_paper.py',run_name='__main__')"
```

Paste the Paper Key ID, press Enter, paste the Paper Secret Key, and press Enter. Nothing appears while typing or pasting: this is normal. Never share the credential-entry screen. Do not use `setx`; never store keys in code, repo, screenshots or chat.

3. This command executes the read-only adapter in the same Python process; no second `py alpaca_paper.py` command is required.

If you have valid Paper keys and network access, you should see JSON containing `"connection": "SUCCESS"`, `"paper_account_status"`, and `"orders_placed": 0`. If it fails, a safe error code (`HTTP_401`, `HTTP_403`, `NETWORK_ERROR`...) is printed; do not share credentials.

4. Run **offline** tests (with mock responses):

```cmd
py -m unittest -v test_main test_alpaca_paper
```

This assumes `test_main.py` and `test_alpaca_paper.py` are in the same folder as `main.py` (as in your GitHub repository).

## Optional: reconcile paper holdings with expected positions

Create a local file named `expected_positions.local.json` (do **not** publish it), e.g.:

```json
{"AAPL":"0"}
```

Then run:

```cmd
py alpaca_paper.py --expected expected_positions.local.json
```

If a quantity differs from the Paper account, a `position_reconciliation` event and a local `paused` flag are recorded in SQLite. This is only a **local flag**, not an Alpaca-side trading halt.

## Security notes

- Avoid uploading `.env` or any file containing keys, account numbers, raw API responses, personal data or local SQLite logs.
- The script uses Python standard library only; no additional `pip install` is needed.
- This code is intended for learning and verifying **read-only Paper Trading** connectivity, not for real-money trading.

## Interpreting safe error codes

`HTTP_401_ACCOUNT`: Paper credentials were rejected. `INVALID_JSON_ACCOUNT` or `INVALID_JSON_POSITIONS`: response could not be decoded as JSON on that endpoint. `UNEXPECTED_CONTENT_TYPE_*`: a server or network device returned another media type, such as HTML. `REDIRECT_BLOCKED_*`: the response attempted a redirect; credentials were not forwarded. Do not share keys or raw API responses.

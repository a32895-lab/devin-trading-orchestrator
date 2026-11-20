# Devin Trading Orchestrator — Minimal Demonstration

A **working Python starter project** for detecting simulated trading incidents and preparing structured engineering tasks that can be handed to an AI coding agent (for example, Devin).

**Status:** runnable local prototype, not a production trading bot. No live orders, brokerage connection, Devin integration, Slack integration or automated code fixes are implemented. The optional webhook is generic and needs an endpoint configured by you.

## What works now

- Simulates a fresh and stale market quote and a position mismatch.
- Flags stale quotes (> 2 seconds), brokerage errors and position mismatches.
- Writes events and HIGH-severity incidents to SQLite.
- Persists a **local** `paused` flag after an incident, across restarts.
- Produces an `incident` object containing a `suggested_devin_task` description.
- Optionally POSTs the JSON incident to a user-configured HTTP(S) webhook.
- Has unit tests using Python's standard library.

**Important:** The `paused` flag does not cancel broker orders or halt a real broker account. A production trading engine would need a separate, fail-closed broker-side control and reconciliation process.

## Requirements

Python **3.10+**. No pip packages needed.

## Run it

```bash
python main.py
```

You should see fresh quote -> no incident, stale quote -> HIGH incident, position mismatch -> HIGH incident. A local `trading_events.sqlite3` file will be created.

Run all tests:

```bash
python -m unittest discover -s tests -v
```

## Try your own event

Create `example_event.json` with:

```json
{"type":"broker_error", "code":"429", "message":"Rate limited"}
```

Then run:

```bash
python main.py --event example_event.json --db custom.sqlite3
```

## Engineering handoff / optional webhook

The generated `suggested_devin_task` is only a task draft. **It does not mean Devin was called.**

If you already have an authorized webhook receiver that can forward events to Devin Automations or your issue tracker, you can POST incident JSON to it:

```bash
INCIDENT_WEBHOOK_URL="https://your-own-receiver.example/incident" python main.py
```

Do not send secrets, API tokens, personal or real-trading account data to a public receiver. This prototype does not support webhook authentication/retries; it is not suitable for production use.

## Architecture (implemented)

```text
Simulated quote / broker error / position reconciliation
                |
                v
         main.py validation
                |
                v
          SQLite events
                |
                v
     Incident + local pause flag
                |
                +----> console JSON + suggested Devin task
                |
                +----> optional configured webhook
```

## Next steps (NOT implemented)

1. Broker paper-trading integration with authenticated API and proper market-data licensing.
2. Reliable, authenticated event queue and alert deduplication.
3. Devin Automation configuration, issue tracking and human approval for PRs.
4. Live-trading controls, recovery, broker-side kill switch and independent risk review.

## Publish to your own public GitHub repository

Create a **public empty repository** called `devin-trading-orchestrator` at https://github.com/new, then run from this directory:

```bash
git init
git add main.py README.md tests/test_main.py .gitignore
git commit -m "Add minimal trading incident monitor"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/devin-trading-orchestrator.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub account name. GitHub will require authentication. You can also upload the files in GitHub's web interface. Do not commit the local SQLite database.

**Disclosure:** Initial scaffolding was generated with ChatGPT assistance; review and modify the code yourself before representing it as your own engineering work.

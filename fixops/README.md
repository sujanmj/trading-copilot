# FixOps Controller

Phase 1 of FixOps Controller automates one Telegram `/full` collection cycle and saves the resulting report under `fixops/incidents/`.

It does not run Codex, does not run Git, does not delete files, and does not place trades.

## Environment

Set these environment variables before running:

```powershell
$env:TELEGRAM_BOT_TOKEN="your-bot-token"
$env:TELEGRAM_CHAT_ID="your-chat-id"
```

Do not commit real tokens or chat IDs.

## Run

From the Trading Copilot repo root:

```powershell
python fixops/fixloop.py
```

The loop sends `/full`, collects messages visible to the configured bot token, and writes:

- `fixops/incidents/latest_full_report.txt`
- `fixops/incidents/latest_full_report.json`

Collection stops when either the overall timeout is reached or no new message arrives for 15 seconds.

## Phase 1 Limitation

This version uses the Telegram Bot API. Telegram bot tokens can only read updates delivered to that bot. If another live process is already polling the same bot token, or if Telegram does not deliver the desired `/full` replies to this bot token, collection may return fewer messages than expected. Later phases can add a dedicated relay or user-authorized client if needed.

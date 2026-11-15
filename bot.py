"""bot.py — Telegram bot for server-health-check: runs the check on request.

Shows a "🔄 Check now" button under the message field and the /check command
in the bot menu. On request it runs health_check.py with --always-notify,
so the check sends its card to Telegram even if the status did not change.
Only messages from TELEGRAM_CHAT_ID are handled; all others are ignored.

Usage:   python3 bot.py   (runs until stopped; see systemd/server-health-check-bot.service)
Needs:   TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, and HEALTH_CHECK_CONFIG for the check.
"""

import subprocess
import sys
import time
from pathlib import Path
import requests
from telegram_notify import TELEGRAM_API, get_token_and_id

CHECK_BUTTON = "🔄 Check now"
KEYBOARD = {"keyboard": [[{"text": CHECK_BUTTON}]], "resize_keyboard": True, "is_persistent": True}
POLL_TIMEOUT = 50      # seconds Telegram keeps getUpdates open while there are no new messages
CHECK_TIMEOUT = 120    # seconds the check may run
RETRY_DELAY = 5        # seconds to wait after a network error
HEALTH_CHECK = Path(__file__).parent / "health_check.py"


def call_api(token, method, payload, timeout=10):
    """Call a Bot API method and return its "result". Errors never show the token."""
    try:
        r = requests.post(f"{TELEGRAM_API}/bot{token}/{method}", json=payload, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Telegram {method}: no response ({type(e).__name__})")
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {method}: HTTP {r.status_code}")
    return r.json()["result"]


def run_check():
    """Run health_check.py; return None if it sent its card, otherwise a text about what went wrong."""
    try:
        result = subprocess.run([sys.executable, str(HEALTH_CHECK), "--always-notify"],
                                capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"⚠️ The check did not finish in {CHECK_TIMEOUT} s"
    if "Alert sent to Telegram" in result.stdout:
        return None
    return f"⚠️ The check ran (exit code {result.returncode}), but sent no card:\n{result.stderr.strip()}"


def handle_message(token, chat_id, message):
    sender = str(message.get("chat", {}).get("id"))
    if sender != chat_id:
        print(f"Ignored a message from another chat: {sender}")
        return
    text = message.get("text", "")
    if text == "/start":
        call_api(token, "sendMessage", {"chat_id": chat_id, "reply_markup": KEYBOARD,
                                        "text": "Press the button below to check the server."})
    elif text in (CHECK_BUTTON, "/check"):
        print("Check requested")
        call_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
        problem = run_check()
        if problem:
            call_api(token, "sendMessage", {"chat_id": chat_id, "text": problem, "reply_markup": KEYBOARD})


def main():
    token, chat_id = get_token_and_id()
    if not token or not chat_id:
        print("ERROR: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2
    call_api(token, "setMyCommands", {"commands": [{"command": "check", "description": "Run the health check now"}]})
    print("Bot started, waiting for messages")
    offset = None
    while True:
        payload = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            updates = call_api(token, "getUpdates", payload, timeout=POLL_TIMEOUT + 10)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(token, chat_id, update["message"])
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    sys.exit(main())

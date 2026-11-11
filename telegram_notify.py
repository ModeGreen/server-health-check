"""telegram_notify.py — send a text message from a Telegram bot.

Usage:   python3 telegram_notify.py "text"
Needs:   TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables
         (see telegram.env.example and README.md).
Exit codes: 0 — sent, 1 — not sent, 2 — wrong usage.
"""

import os
import sys
import requests

TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_TIMEOUT = 10

def send_telegram(token, chat_id, text, timeout, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(f'{TELEGRAM_API}/bot{token}/sendMessage', json=payload, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Telegram: no response ({e.__class__.__name__})")
    if r.status_code != 200:
        raise RuntimeError(f"Telegram: HTTP {r.status_code}")
    return

def get_token_and_id():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def main():

    if len(sys.argv) != 2:
        print ("Usage: telegram_notify.py <text>", file=sys.stderr)
        return 2

    text = sys.argv[1]

    token, chat_id = get_token_and_id()

    if (not token) or (not chat_id):
        print ("ERROR: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    try:
        send_telegram(token, chat_id, text, TELEGRAM_TIMEOUT )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print('Sent')
    return 0

if __name__ == "__main__":
    sys.exit(main())

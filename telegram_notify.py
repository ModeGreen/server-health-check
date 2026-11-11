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

def send_telegram(token, chat_id, text, timeout):
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(f'{TELEGRAM_API}/bot{token}/sendMessage', json=payload, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Telegram: no response ({e.__class__.__name__})")
    if r.status_code != 200:
        raise RuntimeError(f"Telegram: HTTP {r.status_code}")
    return

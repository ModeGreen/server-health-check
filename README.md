# server-health-check

A small health check for a Linux server, written in Python. It checks disk usage, memory, CPU load, CPU temperature, laptop battery charge and whether services answer over HTTP, prints a short report and exits with a Nagios-style code, so it can be run by cron, a systemd timer or a monitoring system. When the status changes, it sends an alert to Telegram.

Built as part of my DevOps learning path; it runs on my home server.

## What it checks

| Check | Source | Value | Default thresholds (warning / critical) |
|---|---|---|---|
| Disk usage | `findmnt` — real disks only (`/dev/...`, no loop devices) | % used | 75% / 90% |
| Memory | `/proc/meminfo` | % in use: `MemTotal` − `MemAvailable` | 80% / 90% |
| CPU load | `/proc/loadavg` | 15-minute load average per CPU, % (100% = all CPUs busy) | 100% / 200% |
| CPU temperature | `/sys/class/thermal`, sensor `x86_pkg_temp` (Intel CPUs) | °C | 85 °C / 95 °C; skipped where there is no sensor (virtual machines, WSL) |
| Laptop battery | `/sys/class/power_supply`, the supply with `type` = `Battery` | charge, %, with the charging status next to it | 20% / 10%, lower is worse; skipped where there is no battery |
| Services | HTTP `GET` to each `url` from the config (`requests`, redirects are not followed) | HTTP status | 200–399 is OK; any other status or no answer within 5 s is CRITICAL |

## Example

```
$ .venv/bin/python health_check.py; echo $?
Checked: disks (2), memory 41.3%, load 6.3%, temp 47.0 °C, battery 87% (Charging), services (2). Problems: 2
  /var: 91.2% — CRITICAL
  my-app: no response (ConnectionError) — CRITICAL
2
```

The summary line always shows the current memory, load, CPU temperature and battery charge (`n/a` if there is no sensor or no battery). Problems are also saved to `alerts.json`, and every run appends one line to `history.log`, so it doubles as a simple history of memory, load, temperature and battery charge:

```
2026-11-10 14:00:02 home-server CRITICAL Checked: disks (2), memory 41.3%, load 6.3%, temp 47.0 °C, battery 87% (Charging), services (2). Problems: 2
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | WARNING |
| 2 | CRITICAL |
| 3 | UNKNOWN — the check itself failed (bad config, `findmnt` error) |

## Quick start

```bash
git clone https://github.com/ModeGreen/server-health-check.git
cd server-health-check
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp health_check.example.yaml health_check.yaml
.venv/bin/python health_check.py; echo $?
```

Requires Linux and Python 3.

## Configuration

Settings live in `health_check.yaml` next to the script, one section per check. This file is not in Git: it holds the real addresses of your services. Start from the example and edit it:

```bash
cp health_check.example.yaml health_check.yaml
```

Another file can be set with the `HEALTH_CHECK_CONFIG` environment variable:

```bash
HEALTH_CHECK_CONFIG=/etc/health_check.yaml .venv/bin/python health_check.py
```

```yaml
disk:
  default:
    warning: 75
    critical: 90
  disks:            # optional: own thresholds for some disks
    /var:
      warning: 70
      critical: 85
  ignore:           # optional: disks that are not checked
    - /mnt/backup
memory:
  warning: 80
  critical: 90
load:
  warning: 100
  critical: 200
temperature:        # °C
  warning: 85
  critical: 95
battery:            # %, lower is worse: warning > critical
  warning: 20
  critical: 10
services:           # optional: HTTP checks
  - name: my-app
    url: http://localhost:8080/health
```

A missing section, bad thresholds or a bad `services` list stop the check with exit code `3` and a clear `ERROR:` message.

## Run on a systemd timer

The `systemd/` folder has a user service and a timer that run the check every 5 minutes. Install them for your user — no root needed, except for `enable-linger`:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/server-health-check.service systemd/server-health-check.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now server-health-check.timer
sudo loginctl enable-linger $USER    # keep the timer running after you log out
```

The service expects the project in `~/server-health-check` and the config in `~/.config/server-health-check/health_check.yaml`. Exit codes 1 and 2 (WARNING and CRITICAL) count as a successful run; exit code 3 (the check itself failed) marks the service as failed, so it shows up in `systemctl --user --failed`.

```bash
systemctl --user list-timers                  # when the next run is
journalctl --user -u server-health-check      # the output of every run
```

## Send a message to Telegram

`telegram_notify.py` sends a text message from your Telegram bot. The health check will use it for alerts; it also works on its own, for example at the end of a backup script.

**1. Create a bot.** Send `/newbot` to [@BotFather](https://t.me/BotFather) in Telegram, pick a name and a username, and keep the token it gives you. Then open your bot and press **Start**: a bot can't write to you first.

**2. Keep the token out of Git** — in a file outside the repository that only you can read:

```bash
mkdir -p ~/.config/server-health-check
cp telegram.env.example ~/.config/server-health-check/telegram.env
chmod 600 ~/.config/server-health-check/telegram.env
nano ~/.config/server-health-check/telegram.env    # put in your token
```

**3. Find your chat ID** — `"chat": {"id": ...}` in the messages your bot has received:

```bash
set -a; source ~/.config/server-health-check/telegram.env; set +a
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates" | python3 -m json.tool
```

Put it into `TELEGRAM_CHAT_ID` in the same file.

**4. Send a message:**

```bash
set -a; source ~/.config/server-health-check/telegram.env; set +a
.venv/bin/python telegram_notify.py "Hello from my server"; echo $?
```

| Code | Meaning |
|---|---|
| 0 | Sent |
| 1 | Not sent: no answer from Telegram, or Telegram refused the request (wrong token or chat ID) |
| 2 | Wrong usage: no text, or the variables are not set |

The token is part of the request URL, so error messages show only the HTTP status or the error type, never the URL. If the token leaks anyway, send `/revoke` to @BotFather to get a new one.

## Telegram alerts

When the status changes — for example from OK to CRITICAL, or back to OK — the check sends one message to Telegram:

```
🔴 CRITICAL · home-server
was OK

Problems:
┃ 🔴 /var: 91.2%

┃ 💾 Disks: 2
┃ 🧠 Memory: 41.3%
┃ ⚙️ Load: 6.3%
┃ 🌡 Temperature: 47.0 °C
┃ 🔋 Battery: 87% (Charging)
┃ 🌐 Services: 2
```

The message is sent with Telegram's HTML formatting (`parse_mode` `HTML`): the status and the values are bold, the problems are a block quote under the "Problems:" title, and the summary of all checks is a second block quote. When the status is back to OK, the first block says "All checks passed". Names and values are escaped, so a `<`, `>` or `&` in a service name can't break the message.

While the status stays the same, nothing is sent, so a long problem does not flood the chat. The last status is kept in `last_status` next to the script. If Telegram does not answer, the check prints an `ERROR:` line and keeps the old status, so it tries again on the next run.

Alerts are on when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set (see the section above). The systemd service reads them from `~/.config/server-health-check/telegram.env`; without that file the check runs as before, just without alerts.

To test the whole chain, set a low memory threshold in your config (for example `warning: 1`), run the service and wait for the message. Then put the threshold back and run it again — the next message says the status is OK again:

```bash
systemctl --user start server-health-check.service
journalctl --user -u server-health-check -n 5
```

If the check itself fails (exit code 3), no alert is sent; the service then shows up in `systemctl --user --failed`.

## Roadmap

- [x] Disk usage
- [x] Memory and CPU load
- [x] CPU temperature
- [x] Laptop battery charge
- [x] HTTP checks for services
- [x] Run on a systemd timer
- [x] Telegram alerts on status change
- [ ] CI with GitHub Actions

## License

MIT

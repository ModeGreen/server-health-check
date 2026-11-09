# server-health-check

A small health check for a Linux server, written in Python. It checks disk usage, prints a short report and exits with a Nagios-style code, so it can be run by cron, a systemd timer or a monitoring system.

Built as part of my DevOps learning path; it runs on my home server.

## What it checks

| Check | Source | Value | Default thresholds (warning / critical) |
|---|---|---|---|
| Disk usage | `findmnt` — real disks only (`/dev/...`, no loop devices) | % used | 75% / 90% |

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
.venv/bin/python health_check.py; echo $?
```

Requires Linux and Python 3.

## Configuration

Thresholds live in `health_check.yaml` next to the script. Another file can be set with the `HEALTH_CHECK_CONFIG` environment variable:

```bash
HEALTH_CHECK_CONFIG=/etc/health_check.yaml .venv/bin/python health_check.py
```

## Roadmap

- [x] Disk usage
- [ ] Memory and CPU load
- [ ] CPU temperature
- [ ] HTTP checks for services
- [ ] Run on a systemd timer
- [ ] Telegram alerts on status change
- [ ] CI with GitHub Actions

## License

MIT
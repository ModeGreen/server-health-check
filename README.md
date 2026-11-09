# server-health-check

A small health check for a Linux server, written in Python. It checks disk usage, memory and CPU load, prints a short report and exits with a Nagios-style code, so it can be run by cron, a systemd timer or a monitoring system.

Built as part of my DevOps learning path; it runs on my home server.

## What it checks

| Check | Source | Value | Default thresholds (warning / critical) |
|---|---|---|---|
| Disk usage | `findmnt` — real disks only (`/dev/...`, no loop devices) | % used | 75% / 90% |
| Memory | `/proc/meminfo` | % in use: `MemTotal` − `MemAvailable` | 80% / 90% |
| CPU load | `/proc/loadavg` | 15-minute load average per CPU, % (100% = all CPUs busy) | 100% / 200% |

## Example

```
$ .venv/bin/python health_check.py; echo $?
Checked: disks (2), memory 41.3%, load 6.3%. Problems: 1
  /var: 91.2% — CRITICAL
2
```

The summary line always shows the current memory and load. Problems are also saved to `alerts.json`, and every run appends one line to `history.log`, so it doubles as a simple history of memory and load:

```
2026-11-09 14:00:02 home-server CRITICAL Checked: disks (2), memory 41.3%, load 6.3%. Problems: 1
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
.venv/bin/python health_check.py; echo $?
```

Requires Linux and Python 3.

## Configuration

Thresholds live in `health_check.yaml` next to the script, one section per check. Another file can be set with the `HEALTH_CHECK_CONFIG` environment variable:

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
```

A missing section or bad thresholds stop the check with exit code `3` and a clear `ERROR:` message.

## Roadmap

- [x] Disk usage
- [x] Memory and CPU load
- [ ] CPU temperature
- [ ] HTTP checks for services
- [ ] Run on a systemd timer
- [ ] Telegram alerts on status change
- [ ] CI with GitHub Actions

## License

MIT
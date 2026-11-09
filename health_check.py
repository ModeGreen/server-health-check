"""health_check.py — a health check for a Linux server.
Prints a short report, saves problems to alerts.json and appends one line per run
to history.log next to the script: time, host, status, result.

Usage:   python3 health_check.py
Config:  health_check.yaml next to the script, or the file from the HEALTH_CHECK_CONFIG
         environment variable. What is checked and the thresholds: see README.md.
Exit codes (Nagios style): 0 — OK, 1 — WARNING, 2 — CRITICAL, 3 — error.
"""

import json
import os
import sys
from pathlib import Path
import subprocess
import yaml
from datetime import datetime

MEMINFO = "/proc/meminfo"
LOADAVG = "/proc/loadavg"

def read_meminfo(path):
    with open(path) as f:
        for line in f:
            line = line.split()
            name = line[0]
            value = line[1]
            if name == "MemTotal:":
                total_kb = int(value)
            elif name == "MemAvailable:":
                available_kb = int(value)
    return total_kb, available_kb

def check_memory(total_kb, available_kb, warning, critical):
    used = total_kb - available_kb
    percent = used / total_kb * 100
    status = get_status(percent, warning, critical)
    return {"name": "memory", "percent": round(percent, 1), "status": status}

def make_history_line(now, host, status, text):
    text = " ".join(text.split())
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')} {host} {status} {text}"

def write_history(path, status, text):
    host = subprocess.run(["hostname"], capture_output=True, text=True)
    log_line = make_history_line(datetime.now(), host.stdout.strip() , status, text)
    with open(path, "a", encoding="utf-8") as f:
        print(log_line, file=f)
    return

def load_config(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data

def get_findmnt_output():
    result = subprocess.run(["findmnt", "-D", "-O", "rw", "-b", "-J"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"findmnt exited with code {result.returncode}: {result.stderr.strip()}")
    return result.stdout

def is_real_disk(source):
    if source.startswith('/dev/') and not source.startswith('/dev/loop'):
        return True
    else:
        return False

def parse_findmnt(data):
    data = json.loads(data)["filesystems"]
    mounts = []
    for mount in data:
        if not is_real_disk(mount["source"]):
            continue
        used_gb = int(mount["used"]) / 1024**3
        total_gb = int(mount["size"]) / 1024**3
        mounts.append({"name": mount["target"], "used_gb": used_gb, "total_gb": total_gb})
    return mounts

def remove_ignored(disks, config):
    ignored_removed = []
    for disk in disks:
        if not disk["name"] in config.get("ignore", []):
            ignored_removed.append(disk)
    return ignored_removed

def get_section(config, name):
    if not isinstance(config, dict) or not isinstance(config.get(name), dict):
        raise ValueError(f"config: section '{name}' is missing")
    return config[name]

def get_thresholds(config, name):
    section = get_section(config, name)
    warning = section.get("warning")
    critical = section.get("critical")
    if type(warning) != int or type(critical) != int:
        raise ValueError(f"{name}: warning and critical must be integers")
    if not critical > warning:
        raise ValueError(f"{name}: warning ({warning}) must be less than critical ({critical})")
    return warning, critical

def get_disk_thresholds(name, config):
    warning = config["default"]["warning"]
    critical = config["default"]["critical"]
    if "disks" in config:
        if name in config["disks"]:
            warning = config["disks"][name].get("warning", config["default"]["warning"])
            critical = config["disks"][name].get("critical", config["default"]["critical"])
    if type(warning) != int or type(critical) != int:
        raise ValueError(f"{name}: warning and critical must be integers")
    if not critical > warning:
        raise ValueError(f"{name}: warning ({warning}) must be less than critical ({critical})")
    return warning, critical

def get_status(percent, warning, critical):
    if percent >= critical:
        return "CRITICAL"
    if percent >= warning:
        return "WARNING"
    return "OK"

def find_alerts(disks, config):
    alerts = []
    for disk in disks:
        warning, critical = get_disk_thresholds(disk["name"], config)
        percent = disk["used_gb"] / disk["total_gb"] * 100
        status = get_status(percent, warning, critical)
        if status != "OK":
            alerts.append({"name": disk["name"], "percent": round(percent, 1), "status": status})
    return alerts

def get_exit_code(alerts):
    code = 0
    for alert in alerts:
        if alert["status"] == "CRITICAL":
            return 2
        code = 1
    return code

def main():
    script_dir = Path(__file__).parent
    journal = script_dir / "history.log"
    
    #Loading config
    try:
        config = load_config(os.environ.get("HEALTH_CHECK_CONFIG", script_dir / "health_check.yaml"))
    except (OSError, yaml.YAMLError) as e:
        message = f"ERROR: {e}"
        print(message, file=sys.stderr)
        write_history(journal, "UNKNOWN", message)
        return 3

    #Checking storage
    try:
        disks = parse_findmnt(get_findmnt_output())
    except RuntimeError as e:
        message = f"ERROR: {e}"
        print(message, file=sys.stderr)
        write_history(journal, "UNKNOWN", message)
        return 3

    try:
        disk_config_section = get_section(config, "disk")
        disks = remove_ignored(disks, disk_config_section)
        alerts = find_alerts(disks, disk_config_section)
        mem_config_section = get_thresholds(config, "memory")
    except ValueError as e:
        message = f"ERROR: {e}"
        print(message, file=sys.stderr)
        write_history(journal, "UNKNOWN", message)
        return 3

    #Checking ram
    total_kb, available_kb = read_meminfo(MEMINFO)
    mem_data = check_memory(total_kb, available_kb, mem_config_section[0], mem_config_section[1])
    if mem_data["status"] != "OK":
        alerts.append(mem_data)

    with open(script_dir / "alerts.json", "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)

    output_text = f"Disks checked: {len(disks)}, with problems: {len(alerts)}"
    print(output_text)
    for alert in alerts:
        print(f"  {alert['name']}: {alert['percent']}% — {alert['status']}")

    exit_code = get_exit_code(alerts)

    if exit_code == 2:
        status = "CRITICAL"
    elif exit_code == 1:
        status = "WARNING"
    else:
        status = "OK"

    write_history(journal, status, output_text)

    return exit_code

if __name__ == "__main__":
    sys.exit(main())

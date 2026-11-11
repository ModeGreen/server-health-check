"""health_check.py — a health check for a Linux server.
Prints a short report, saves problems to alerts.json and appends one line per run
to history.log next to the script: time, host, status, result.
When the status changes, sends a Telegram message (if TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set) and keeps the last status in last_status next to the script.

Usage:   python3 health_check.py
Config:  health_check.yaml next to the script (a copy of health_check.example.yaml),
         or the file from the HEALTH_CHECK_CONFIG environment variable.
         What is checked and the thresholds: see README.md.
Exit codes (Nagios style): 0 — OK, 1 — WARNING, 2 — CRITICAL, 3 — error.
"""

import json
import os
import sys
from pathlib import Path
import subprocess
import yaml
import requests
from datetime import datetime
from telegram_notify import send_telegram, get_token_and_id, TELEGRAM_TIMEOUT

MEMINFO = "/proc/meminfo"
LOADAVG = "/proc/loadavg"
HTTP_TIMEOUT = 5
THERMAL = "/sys/class/thermal"
CPU_SENSOR = "x86_pkg_temp"

def make_message(host, old_status, new_status, report):
    message = f"[{host}] {new_status} (was {old_status})\n{report}"
    return message

def get_hostname():
    hostname = subprocess.run(["hostname"], capture_output=True, text=True)
    return hostname.stdout.strip()

def read_last_status(path):
    try:
        with open(path, encoding="utf-8") as f:
            last_status = f.read().strip()
    except OSError:
        last_status = "OK"
    if last_status not in ("OK", "WARNING", "CRITICAL"):
        last_status = "OK"
    return last_status

def write_last_status(path, status):
    Path(path).write_text(status + "\n", encoding="utf-8")
    return

def read_cpu_temp(path):
    for zone in Path(path).glob("thermal_zone*"):
        try:
            zone_name = (zone / "type").read_text()
            zone_name = zone_name.strip()
        except OSError:
            continue
        if zone_name == CPU_SENSOR:
            try:
                temp = int((zone / "temp").read_text())
            except (ValueError, OSError):
                continue
            temp /= 1000
            return temp
    return None

def check_temperature(temp, warning, critical):
    status = get_status(temp, warning, critical)
    detail = f"{round(temp, 1)} °C"
    return {"name": "temperature", "status": status, "detail": detail}

def get_services(config):
    services = []
    if "services" in config and config["services"] is not None:
        if not isinstance(config["services"], list):
            raise ValueError("config: services must be a list")
        for serv in config["services"]:
            if not isinstance(serv, dict) or not (isinstance(serv.get("name"), str) and isinstance(serv.get("url"), str)):
                raise ValueError("config: every service needs a name and a url")
            services.append(serv)
    return services

def check_service(name, url, timeout):
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return {"name": name, "status": "CRITICAL", "detail": f"no response ({e.__class__.__name__})"}
    if 200 <= r.status_code < 400:
        status = "OK"
    else:
        status = "CRITICAL"
    detail = f"HTTP {r.status_code}"
    return {"name": name, "status": status, "detail": detail}

def read_loadavg(path):
    with open(path) as f:
        load_15 = float(f.read().split()[2])
    return load_15

def check_load(load, cpus, warning, critical):
    percent = load / cpus * 100
    status = get_status(percent, warning, critical)
    return {"name": "load", "percent": round(percent, 1), "status": status}

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
    host = get_hostname()
    log_line = make_history_line(datetime.now(), host, status, text)
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

def format_alert(alert):
    if "percent" in alert:
        return f"{alert['name']}: {alert['percent']}% — {alert['status']}"
    else:
        return f"{alert['name']}: {alert['detail']} — {alert['status']}"

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
    
    # Loading config
    try:
        config = load_config(os.environ.get("HEALTH_CHECK_CONFIG", script_dir / "health_check.yaml"))
    except (OSError, yaml.YAMLError) as e:
        message = f"ERROR: {e}"
        print(message, file=sys.stderr)
        write_history(journal, "UNKNOWN", message)
        return 3

    # Checking storage
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
        mem_warning, mem_critical = get_thresholds(config, "memory")
        load_warning, load_critical = get_thresholds(config, "load")
        temp_warning, temp_critical = get_thresholds(config, "temperature")
        services = get_services(config)
    except ValueError as e:
        message = f"ERROR: {e}"
        print(message, file=sys.stderr)
        write_history(journal, "UNKNOWN", message)
        return 3

    # Checking ram
    total_kb, available_kb = read_meminfo(MEMINFO)
    mem_data = check_memory(total_kb, available_kb, mem_warning, mem_critical)
    if mem_data["status"] != "OK":
        alerts.append(mem_data)

    # Checking cpu load
    cpus = os.cpu_count()
    load = read_loadavg(LOADAVG)
    load_data = check_load(load, cpus, load_warning, load_critical)
    if load_data["status"] != "OK":
        alerts.append(load_data)

    # Checking temperature
    temp = read_cpu_temp(THERMAL)
    if temp is None:
        temp_text = "n/a"
    else:
        cpu_temp = check_temperature(temp, temp_warning, temp_critical)
        temp_text = cpu_temp['detail']
        if cpu_temp["status"] != "OK":
            alerts.append(cpu_temp)

    # Checking services
    for service in services:
        service_health = check_service(service["name"], service["url"], HTTP_TIMEOUT)
        if service_health["status"] != "OK":
            alerts.append(service_health)

    with open(script_dir / "alerts.json", "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)

    report = f"Checked: disks ({len(disks)}), memory {mem_data['percent']}%, load {load_data['percent']}%, temp {temp_text}, services ({len(services)}). Problems: {len(alerts)}"
    history_report = report
    for alert in alerts:
        report+= ("\n  " + format_alert(alert))
    print(report)

    exit_code = get_exit_code(alerts)

    if exit_code == 2:
        status = "CRITICAL"
    elif exit_code == 1:
        status = "WARNING"
    else:
        status = "OK"

    write_history(journal, status, history_report)

    last_status_path = script_dir/"last_status"
    last_status = read_last_status(last_status_path)
    if status != last_status:
        token, chat_id = get_token_and_id()
        if token and chat_id:
            try:
                send_telegram(token, chat_id, make_message(get_hostname(), last_status, status, report), TELEGRAM_TIMEOUT)
            except RuntimeError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return exit_code
            print(f"Alert sent to Telegram: {last_status} → {status}")
            write_last_status(last_status_path, status)
        else:
            write_last_status(last_status_path, status)
            
    return exit_code

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Small local supervisor for the SURF daemon."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:17777"
ROOT = Path(__file__).resolve().parent


def state_dir() -> Path:
    path = Path(os.getenv("SURF_STATE_DIR", Path.home() / ".local" / "state" / "surf"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = Path(os.getenv("SURF_LOG_DIR", Path.home() / ".local" / "state" / "surf" / "logs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def base_url() -> str:
    return os.getenv("SURF_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def request_json(url: str, timeout: float = 1.0) -> dict | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": "surfctl/1.0"}), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return None


def pidfile() -> Path:
    parsed = urlparse(base_url())
    port = parsed.port or 80
    return state_dir() / f"surf-{parsed.hostname or '127.0.0.1'}-{port}.pid"


def read_pid() -> int | None:
    try:
        return int(pidfile().read_text().strip())
    except (OSError, ValueError):
        return None


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def live() -> dict | None:
    return request_json(f"{base_url()}/health/live")


def runtime() -> dict | None:
    return request_json(f"{base_url()}/health/runtime", timeout=2.0)


def status() -> dict:
    pid = read_pid()
    live_data = live()
    runtime_data = runtime() if live_data else None
    return {
        "base_url": base_url(),
        "running": bool(live_data),
        "pid": pid if process_alive(pid) else None,
        "pidfile": str(pidfile()),
        "live": live_data,
        "runtime": runtime_data,
    }


def start_daemon() -> int:
    parsed = urlparse(base_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 17777
    env = os.environ.copy()
    env.setdefault("SURF_HOST", host)
    env.setdefault("SURF_PORT", str(port))
    env.setdefault("SURF_STRICT_PORT", "1")

    log_path = log_dir() / "surf.log"
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        [python_executable(), str(ROOT / "start_surf.py")],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pidfile().write_text(str(process.pid))
    return process.pid


def python_executable() -> str:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def ensure(timeout: float) -> dict:
    current = status()
    if current["running"]:
        current["started"] = False
        return current

    old_pid = read_pid()
    if old_pid and not process_alive(old_pid):
        try:
            pidfile().unlink()
        except OSError:
            pass

    pid = start_daemon()
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = status()
        if current["running"]:
            current["started"] = True
            current["pid"] = pid
            return current
        if not process_alive(pid):
            break
        time.sleep(0.2)

    return {
        "base_url": base_url(),
        "running": False,
        "started": False,
        "pid": pid if process_alive(pid) else None,
        "pidfile": str(pidfile()),
        "error": "SURF did not become ready",
    }


def stop() -> dict:
    pid = read_pid()
    if not process_alive(pid):
        return {"stopped": False, "reason": "not_running", "pidfile": str(pidfile())}

    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not process_alive(pid):
            try:
                pidfile().unlink()
            except OSError:
                pass
            return {"stopped": True, "pid": pid}
        time.sleep(0.2)

    return {"stopped": False, "reason": "still_running", "pid": pid}


def print_json(payload: dict) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("running", payload.get("stopped", True)) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON")
    ensure_parser = subparsers.add_parser("ensure")
    ensure_parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON")
    ensure_parser.add_argument("--timeout", type=float, default=20.0)
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON")
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(status(), indent=2, sort_keys=True))
        return 0
    if args.command == "ensure":
        return print_json(ensure(args.timeout))
    if args.command == "stop":
        return print_json(stop())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

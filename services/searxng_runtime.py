"""Lazy SearXNG runtime — probe health and autostart Docker when down."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_wake_lock = asyncio.Lock()
_last_wake_attempt: float = 0.0
_last_wake_result: Optional[Dict[str, Any]] = None


def _health_url() -> str:
    base = settings.searxng_base_url.rstrip("/")
    return f"{base}/healthz"


async def probe_searxng(timeout: Optional[float] = None) -> Dict[str, Any]:
    """Return reachability status for the configured SearXNG instance."""
    t = timeout if timeout is not None else settings.searxng_health_timeout
    url = _health_url()
    t0 = time.monotonic()
    headers = {"X-Forwarded-For": "127.0.0.1"}
    try:
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.get(url, headers=headers)
            ok = resp.status_code == 200 and resp.text.strip().upper() == "OK"
            return {
                "reachable": ok,
                "url": url,
                "status_code": resp.status_code,
                "body": resp.text.strip()[:32],
                "ms": round((time.monotonic() - t0) * 1000),
            }
    except httpx.ConnectError:
        return {
            "reachable": False,
            "url": url,
            "error": "connect_error",
            "ms": round((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "url": url,
            "error": str(exc),
            "ms": round((time.monotonic() - t0) * 1000),
        }


async def _run_cmd(cmd: list[str], timeout: int) -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"ok": False, "cmd": cmd, "error": f"timeout after {timeout}s"}
    out = (stdout or b"").decode("utf-8", errors="replace").strip()
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    return {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": out[:500],
        "stderr": err[:500],
    }


async def _docker_container_exists(name: str) -> bool:
    if not shutil.which("docker"):
        return False
    result = await _run_cmd(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        timeout=settings.searxng_autowake_cmd_timeout,
    )
    return result.get("ok") and result.get("stdout") in {"true", "false"}


async def _docker_start(name: str) -> Dict[str, Any]:
    return await _run_cmd(
        ["docker", "start", name],
        timeout=settings.searxng_autowake_cmd_timeout,
    )


async def _docker_run() -> Dict[str, Any]:
    config_dir = str(Path(settings.searxng_config_dir).expanduser())
    host_port = settings.searxng_host_port
    name = settings.searxng_container_name
    image = settings.searxng_docker_image
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-p",
        f"{host_port}:8080",
        "-v",
        f"{config_dir}:/etc/searxng:rw",
        image,
    ]
    return await _run_cmd(cmd, timeout=settings.searxng_autowake_cmd_timeout)


async def _wait_healthy() -> Dict[str, Any]:
    deadline = time.monotonic() + settings.searxng_autowake_wait_seconds
    last: Dict[str, Any] = {"reachable": False}
    while time.monotonic() < deadline:
        last = await probe_searxng()
        if last.get("reachable"):
            return last
        await asyncio.sleep(1.0)
    return last


async def ensure_searxng(force: bool = False) -> Dict[str, Any]:
    """Ensure SearXNG is reachable; optionally autostart Docker when configured."""
    global _last_wake_attempt, _last_wake_result

    probe = await probe_searxng()
    if probe.get("reachable"):
        return {"status": "ready", "autowake": False, "probe": probe}

    if not settings.searxng_autowake_enabled and not force:
        return {
            "status": "down",
            "autowake": False,
            "probe": probe,
            "error": "SearXNG unreachable and autowake disabled",
        }

    async with _wake_lock:
        probe = await probe_searxng()
        if probe.get("reachable"):
            return {"status": "ready", "autowake": False, "probe": probe}

        now = time.monotonic()
        if (
            not force
            and _last_wake_result
            and now - _last_wake_attempt < settings.searxng_autowake_cooldown_seconds
        ):
            probe = await probe_searxng()
            if probe.get("reachable"):
                return {**_last_wake_result, "cooldown": True, "probe": probe}
            # Cooldown cache is stale — container went down again; retry wake.

        _last_wake_attempt = now
        actions: list[Dict[str, Any]] = []

        if not shutil.which("docker"):
            result = {
                "status": "down",
                "autowake": True,
                "probe": probe,
                "error": "docker not found on PATH",
                "actions": actions,
            }
            _last_wake_result = result
            return result

        name = settings.searxng_container_name
        if await _docker_container_exists(name):
            start = await _docker_start(name)
            actions.append({"action": "docker_start", **start})
        else:
            run = await _docker_run()
            actions.append({"action": "docker_run", **run})

        healthy = await _wait_healthy()
        if healthy.get("reachable"):
            await asyncio.sleep(settings.searxng_autowake_settle_seconds)
            healthy = await probe_searxng()
        result = {
            "status": "ready" if healthy.get("reachable") else "down",
            "autowake": True,
            "probe": healthy,
            "actions": actions,
        }
        if not healthy.get("reachable"):
            result["error"] = "SearXNG still unreachable after autowake"
            logger.warning("searxng_autowake_failed", actions=actions, probe=healthy)
        else:
            logger.info(
                "searxng_autowake_ok", actions=[a.get("action") for a in actions]
            )
        _last_wake_result = result
        return result

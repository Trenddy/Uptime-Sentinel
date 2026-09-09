"""
Check backends: the actual "is this service alive" probes.

Two check types are supported out of the box:

- http: issues a GET/HEAD request and validates the status code
- tcp:  opens a raw TCP socket to (host, port) and validates it connects

Both return a CheckResult, a small immutable record that storage.py persists
and sla.py aggregates. Keeping the probe logic dependency-free (stdlib only)
means the project runs anywhere Python runs -- no requests, no extra creds,
nothing to explain away in an interview.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CheckResult:
    service: str
    check_type: str
    ok: bool
    status_code: Optional[int]
    latency_ms: float
    error: Optional[str]
    timestamp: float  # unix epoch seconds, UTC

    def to_row(self) -> tuple:
        return (
            self.service,
            self.check_type,
            int(self.ok),
            self.status_code,
            self.latency_ms,
            self.error,
            self.timestamp,
        )


def check_http(
    name: str,
    url: str,
    expected_status: int = 200,
    timeout_seconds: float = 5.0,
    method: str = "GET",
) -> CheckResult:
    """Probe an HTTP(S) endpoint and time the round trip."""
    start = time.monotonic()
    ts = time.time()
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "uptime-sentinel/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            latency_ms = (time.monotonic() - start) * 1000
            status = resp.getcode()
            ok = status == expected_status
            return CheckResult(
                service=name,
                check_type="http",
                ok=ok,
                status_code=status,
                latency_ms=round(latency_ms, 2),
                error=None if ok else f"unexpected status {status} (wanted {expected_status})",
                timestamp=ts,
            )
    except urllib.error.HTTPError as e:
        latency_ms = (time.monotonic() - start) * 1000
        ok = e.code == expected_status
        return CheckResult(
            service=name,
            check_type="http",
            ok=ok,
            status_code=e.code,
            latency_ms=round(latency_ms, 2),
            error=None if ok else f"HTTP {e.code}: {e.reason}",
            timestamp=ts,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        latency_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            service=name,
            check_type="http",
            ok=False,
            status_code=None,
            latency_ms=round(latency_ms, 2),
            error=str(getattr(e, "reason", e)),
            timestamp=ts,
        )


def check_tcp(
    name: str,
    host: str,
    port: int,
    timeout_seconds: float = 3.0,
) -> CheckResult:
    """Probe raw TCP connectivity -- for databases, internal services, anything without HTTP."""
    start = time.monotonic()
    ts = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            latency_ms = (time.monotonic() - start) * 1000
            return CheckResult(
                service=name,
                check_type="tcp",
                ok=True,
                status_code=None,
                latency_ms=round(latency_ms, 2),
                error=None,
                timestamp=ts,
            )
    except OSError as e:
        latency_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            service=name,
            check_type="tcp",
            ok=False,
            status_code=None,
            latency_ms=round(latency_ms, 2),
            error=str(e),
            timestamp=ts,
        )


def run_check(service_cfg: dict) -> CheckResult:
    """Dispatch a single service config dict to the right check backend."""
    check_type = service_cfg.get("type", "http")
    name = service_cfg["name"]
    timeout = float(service_cfg.get("timeout_seconds", 5))

    if check_type == "http":
        return check_http(
            name=name,
            url=service_cfg["url"],
            expected_status=int(service_cfg.get("expected_status", 200)),
            timeout_seconds=timeout,
            method=service_cfg.get("method", "GET"),
        )
    elif check_type == "tcp":
        return check_tcp(
            name=name,
            host=service_cfg["host"],
            port=int(service_cfg["port"]),
            timeout_seconds=timeout,
        )
    else:
        raise ValueError(f"Unknown check type '{check_type}' for service '{name}'")

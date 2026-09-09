"""
Alert backends. Deliberately small and pluggable: an AlertManager holds a
list of backends (anything with a `.send(event)` method) and fans every
event out to all of them. Adding PagerDuty/email/Teams later is "write one
class," not "rewire the monitor loop."
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class AlertEvent:
    service: str
    kind: str  # "down", "recovered", "sla_breach"
    message: str
    timestamp: float


class AlertBackend(Protocol):
    def send(self, event: AlertEvent) -> None: ...


class ConsoleAlertBackend:
    """Always-on fallback: prints a clearly-flagged line. Zero setup, zero deps."""

    ICONS = {"down": "🔴", "recovered": "🟢", "sla_breach": "🟠"}

    def send(self, event: AlertEvent) -> None:
        icon = self.ICONS.get(event.kind, "⚪")
        print(f"{icon} [{event.kind.upper()}] {event.service}: {event.message}")


class SlackAlertBackend:
    """Posts to a Slack incoming webhook. No slack_sdk dependency needed."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, event: AlertEvent) -> None:
        payload = json.dumps({"text": f"*[{event.kind.upper()}]* `{event.service}` — {event.message}"}).encode()
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Alerting must never crash the monitor loop -- fall back to stderr.
            print(f"[uptime-sentinel] Slack alert failed for {event.service}: {e}")


class AlertManager:
    def __init__(self, backends: Optional[list[AlertBackend]] = None):
        self.backends = backends or [ConsoleAlertBackend()]
        self._last_state: dict[str, bool] = {}  # service -> was_ok

    def process(self, service: str, ok: bool, detail: str, timestamp: float) -> None:
        """Fire a down/recovered alert only on state *transitions*, not every check."""
        previous = self._last_state.get(service)
        self._last_state[service] = ok

        if previous is None:
            return  # first check for this service this run -- nothing to compare against
        if previous and not ok:
            self._fire(AlertEvent(service, "down", detail, timestamp))
        elif not previous and ok:
            self._fire(AlertEvent(service, "recovered", "check passing again", timestamp))

    def sla_breach(self, service: str, detail: str, timestamp: float) -> None:
        self._fire(AlertEvent(service, "sla_breach", detail, timestamp))

    def _fire(self, event: AlertEvent) -> None:
        for backend in self.backends:
            backend.send(event)


def build_alert_manager(alerting_cfg: dict) -> AlertManager:
    backends: list[AlertBackend] = []
    if alerting_cfg.get("console", True):
        backends.append(ConsoleAlertBackend())
    slack_cfg = alerting_cfg.get("slack", {}) or {}
    if slack_cfg.get("enabled") and slack_cfg.get("webhook_url"):
        backends.append(SlackAlertBackend(slack_cfg["webhook_url"]))
    return AlertManager(backends or [ConsoleAlertBackend()])

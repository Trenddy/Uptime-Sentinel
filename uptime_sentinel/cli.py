"""
Command-line entrypoint.

    uptime-sentinel check              # run every configured check once, print results
    uptime-sentinel run --once         # same as `check`, but also persists + alerts
    uptime-sentinel run                # loop forever on each service's interval (Ctrl+C to stop)
    uptime-sentinel status             # quick text SLA summary, good for a terminal or a cron email
    uptime-sentinel report             # write docs/report.html from stored history
    uptime-sentinel demo               # seed realistic synthetic history (incl. an outage) for a demo/screenshot
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import yaml

from .alerting import build_alert_manager
from .monitor import CheckResult, run_check
from .report import write_report
from .sla import evaluate
from .storage import Store


def load_config(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        print(
            f"[uptime-sentinel] config file '{path}' not found.\n"
            f"  Copy config.example.yaml to {path} and edit the service list, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    with cfg_path.open() as f:
        return yaml.safe_load(f)


def cmd_check(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    for svc in cfg["services"]:
        result = run_check(svc)
        _print_result(result)


def cmd_run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = Store(args.db)
    alert_manager = build_alert_manager(cfg.get("alerting", {}))
    default_interval = cfg.get("default_interval_seconds", 60)

    def sweep() -> None:
        for svc in cfg["services"]:
            result = run_check(svc)
            store.save(result)
            _print_result(result)
            detail = result.error or "check passing"
            alert_manager.process(result.service, result.ok, detail, result.timestamp)

    if args.once:
        sweep()
        return

    print(f"[uptime-sentinel] monitoring {len(cfg['services'])} service(s) — Ctrl+C to stop")
    try:
        while True:
            sweep()
            time.sleep(default_interval)
    except KeyboardInterrupt:
        print("\n[uptime-sentinel] stopped")


def cmd_status(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = Store(args.db)
    targets = {s["name"]: s.get("sla_target", cfg.get("default_sla_target", 99.9)) for s in cfg["services"]}

    rows = []
    for name, target in targets.items():
        history = store.history(name)
        report = evaluate(name, history, target)
        state = "UP" if history and history[-1]["ok"] else ("DOWN" if history else "NO DATA")
        breach_flag = "BREACH" if report.breached else "ok"
        rows.append((name, state, f"{report.uptime_pct:.3f}%", f"{target:.2f}%", breach_flag, report.incident_count))

    if not rows:
        print("No services configured.")
        return

    widths = [max(len(str(r[i])) for r in rows + [("SERVICE", "STATE", "UPTIME", "TARGET", "SLA", "INCIDENTS")]) for i in range(6)]
    header = ("SERVICE", "STATE", "UPTIME", "TARGET", "SLA", "INCIDENTS")
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def cmd_report(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    store = Store(args.db)
    targets = {s["name"]: s.get("sla_target", cfg.get("default_sla_target", 99.9)) for s in cfg["services"]}

    reports = []
    histories = {}
    for name, target in targets.items():
        history = store.history(name)
        histories[name] = history
        reports.append(evaluate(name, history, target))

    out = write_report(reports, histories, args.out, generated_at=time.time())
    print(f"[uptime-sentinel] wrote {out}")


def cmd_demo(args: argparse.Namespace) -> None:
    """Seed a realistic history: mostly-healthy services plus one clear outage, so `report`
    and `status` have something interesting to show without waiting for real time to pass."""
    store = Store(args.db)
    rng = random.Random(42)
    now = time.time()
    services = [
        ("public-api", "http", 99.9, 45),
        ("docs-site", "http", 99.5, 80),
        ("internal-db", "tcp", 99.95, 6),
    ]

    for name, ctype, _target, base_latency in services:
        results = []
        # 24h of history, one check every 2 minutes = 720 points.
        # Outage placed near the end (not the middle) so it still shows up in the
        # dashboard's "recent checks" strip, which only renders the latest 60.
        total_points = 720
        outage_start = int(total_points * 0.92) if name == "public-api" else None
        outage_len = 9  # ~18 minutes down

        for i in range(total_points):
            ts = now - (total_points - i) * 120
            in_outage = outage_start is not None and outage_start <= i < outage_start + outage_len
            ok = not in_outage
            latency = base_latency + rng.uniform(-base_latency * 0.2, base_latency * 0.5)
            results.append(
                CheckResult(
                    service=name,
                    check_type=ctype,
                    ok=ok,
                    status_code=200 if (ctype == "http" and ok) else (503 if ctype == "http" else None),
                    latency_ms=round(max(1.0, latency), 2),
                    error=None if ok else "connection timed out",
                    timestamp=ts,
                )
            )
        store.save_many(results)

    print(f"[uptime-sentinel] seeded demo history into {args.db}")
    print("  run: uptime-sentinel status --db " + args.db)
    print("  run: uptime-sentinel report --db " + args.db)


def _print_result(result: CheckResult) -> None:
    icon = "OK " if result.ok else "FAIL"
    detail = f"{result.latency_ms}ms"
    if not result.ok:
        detail += f" — {result.error}"
    print(f"[{icon}] {result.service:<20} {detail}")


def build_parser() -> argparse.ArgumentParser:
    # --config/--db are accepted both before AND after the subcommand
    # (`uptime-sentinel --config x.yaml status` and `uptime-sentinel status --config x.yaml`
    # both work) so nobody has to remember which order the flags go in.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yaml", help="path to config file (default: config.yaml)")
    common.add_argument("--db", default="data/uptime_sentinel.db", help="path to sqlite db (default: data/uptime_sentinel.db)")

    parser = argparse.ArgumentParser(
        prog="uptime-sentinel", description="Lightweight service uptime & SLA monitor.", parents=[common]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="run every configured check once, print results, don't persist", parents=[common])
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="run checks on a loop, persisting + alerting on state changes", parents=[common])
    p_run.add_argument("--once", action="store_true", help="run a single sweep instead of looping")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="print a quick SLA summary table", parents=[common])
    p_status.set_defaults(func=cmd_status)

    p_report = sub.add_parser("report", help="write an HTML dashboard from stored history", parents=[common])
    p_report.add_argument("--out", default="docs/report.html", help="output path (default: docs/report.html)")
    p_report.set_defaults(func=cmd_report)

    p_demo = sub.add_parser("demo", help="seed synthetic history (incl. a sample outage) for a demo/screenshot", parents=[common])
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

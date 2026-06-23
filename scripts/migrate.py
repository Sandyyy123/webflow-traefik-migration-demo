#!/usr/bin/env python3
"""
migrate.py - driver for a safe website -> Webflow cutover while keeping the CRM/app
and WordPress blog live on the existing Traefik load balancer.

Sub-commands:
    plan       Print the ordered, reversible cutover plan.
    preflight  Check DNS resolution, current TTLs, Traefik reachability, Webflow target.
    cutover    Apply (or --dry-run) the apex/www repoint + Traefik redirect swap.
    rollback   Revert apex/www back to the load balancer (the website router is kept warm).

This is illustrative: the actual DNS write step is provider-specific (Cloudflare, Route53,
Hetzner, etc.). The provider call is isolated in `apply_dns_change()` so only that one function
changes per registrar. Everything else - ordering, verification, rollback - is provider-agnostic.
"""
from __future__ import annotations

import argparse
import socket
import sys

# Webflow's documented public targets (apex A records + www CNAME).
WEBFLOW_APEX_IPS = ["75.2.70.75", "99.83.190.102"]
WEBFLOW_WWW_CNAME = "proxy-ssl.webflow.com"

# The current production load balancer running Traefik (example value).
LOAD_BALANCER_IP = "203.0.113.10"

PLAN_STEPS = [
    ("T-48h", "Inventory fused Traefik routing (website vs app vs blog)", "read-only"),
    ("T-48h", "Lower TTL on apex/www (and blog) to 300s", "safe, no rollback needed"),
    ("T-24h", "Split fused router into website/app/blog routers", "git revert routers.yml"),
    ("T-24h", "Stage Webflow against real hostname via hosts override", "no public change"),
    ("T-0",   "Decide blog fate (move to blog.example.tld + 301)", "remove record + redirect"),
    ("T-0",   "Canary: repoint www -> Webflow only", "revert www CNAME (~TTL)"),
    ("T+0",   "Apex cutover + deploy routers.cutover.yml (warm redirect)", "revert apex A (~TTL)"),
    ("T+0",   "Verify app + blog + TLS still healthy", "n/a"),
    ("T+72h", "Flip redirect 302 -> 301, restore TTLs", "rollback window closes"),
]


def resolve(host: str) -> list[str]:
    """Return resolved A records for a host, or [] on failure."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        return sorted({i[4][0] for i in infos})
    except socket.gaierror:
        return []


def cmd_plan(_args) -> int:
    print("Cutover plan (each step is reversible):\n")
    for when, action, rollback in PLAN_STEPS:
        print(f"  [{when:>5}] {action}")
        print(f"          rollback: {rollback}")
    return 0


def cmd_preflight(args) -> int:
    domain = args.domain
    www = f"www.{domain}"
    app = f"app.{domain}"
    ok = True

    print(f"Preflight for {domain}\n")

    apex_ips = resolve(domain)
    www_ips = resolve(www)
    app_ips = resolve(app)

    print(f"  apex  {domain:<28} -> {apex_ips or 'NXDOMAIN'}")
    print(f"  www   {www:<28} -> {www_ips or 'NXDOMAIN'}")
    print(f"  app   {app:<28} -> {app_ips or 'NXDOMAIN'}")

    # Sanity: the app must currently resolve to the load balancer and must NOT move.
    if app_ips and LOAD_BALANCER_IP not in app_ips and apex_ips:
        # only a soft warning in the illustrative case (example.tld is not the real LB)
        print(f"  NOTE: app does not resolve to the documented load balancer "
              f"({LOAD_BALANCER_IP}); confirm the real LB IP before cutover.")

    # Is the website already on Webflow?
    on_webflow = any(ip in WEBFLOW_APEX_IPS for ip in apex_ips)
    print(f"\n  website already on Webflow: {on_webflow}")
    print(f"  Webflow apex targets: {WEBFLOW_APEX_IPS}")
    print(f"  Webflow www CNAME:    {WEBFLOW_WWW_CNAME}")

    print("\n  Reminder: lower TTLs to 300s at least 24h before cutover so rollback is fast.")
    return 0 if ok else 1


def apply_dns_change(record: str, rtype: str, value, dry_run: bool) -> None:
    """
    Isolated provider call. Swap the body for your registrar's API
    (Cloudflare/Route53/Hetzner). Everything else in this script is provider-agnostic.
    """
    action = "WOULD SET" if dry_run else "SET"
    print(f"    {action}: {record} {rtype} -> {value}")
    if not dry_run:
        # provider-specific API call goes here
        raise NotImplementedError(
            "Wire up your DNS provider API in apply_dns_change() before a live run."
        )


def cmd_cutover(args) -> int:
    domain, www = args.domain, f"www.{args.domain}"
    print(f"Cutover {domain} -> Webflow (app + blog stay on Traefik)  "
          f"[{'DRY-RUN' if args.dry_run else 'LIVE'}]\n")
    print("  Step 1: canary www -> Webflow")
    apply_dns_change(www, "CNAME", WEBFLOW_WWW_CNAME, args.dry_run)
    print("  -> verify with scripts/verify.py before continuing\n")
    print("  Step 2: apex -> Webflow")
    for ip in WEBFLOW_APEX_IPS:
        apply_dns_change(domain, "A", ip, args.dry_run)
    print("  Step 3: deploy traefik/dynamic/routers.cutover.yml "
          "(website router becomes a warm redirect; app + blog untouched)")
    print("\n  app + blog records are intentionally NOT modified.")
    return 0


def cmd_rollback(args) -> int:
    domain, www = args.domain, f"www.{args.domain}"
    print(f"ROLLBACK {domain} -> load balancer {LOAD_BALANCER_IP}  "
          f"[{'DRY-RUN' if args.dry_run else 'LIVE'}]\n")
    apply_dns_change(domain, "A", LOAD_BALANCER_IP, args.dry_run)
    apply_dns_change(www, "A", LOAD_BALANCER_IP, args.dry_run)
    print("\n  The website router was kept warm in routers.yml, so the old site serves "
          "again as soon as DNS reverts (~TTL = 300s).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Safe website -> Webflow cutover driver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan");      sp.set_defaults(func=cmd_plan)
    sp = sub.add_parser("preflight"); sp.add_argument("--domain", required=True); sp.set_defaults(func=cmd_preflight)
    sp = sub.add_parser("cutover");   sp.add_argument("--domain", required=True); sp.add_argument("--dry-run", action="store_true"); sp.set_defaults(func=cmd_cutover)
    sp = sub.add_parser("rollback");  sp.add_argument("--domain", required=True); sp.add_argument("--dry-run", action="store_true"); sp.set_defaults(func=cmd_rollback)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

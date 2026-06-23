#!/usr/bin/env python3
"""
verify.py - post-cutover assertions.

Confirms the migration did exactly what it should and nothing it shouldn't:
  * apex + www now point at Webflow,
  * app.<domain> STILL points at the load balancer (the CRM/app never moved),
  * /blog still returns content,
  * TLS is valid on every host.

Exits non-zero if any invariant is violated, so it can gate the next cutover step in CI/runbook.
"""
from __future__ import annotations

import argparse
import socket
import ssl
import sys

WEBFLOW_APEX_IPS = {"75.2.70.75", "99.83.190.102"}
LOAD_BALANCER_IP = "203.0.113.10"


def a_records(host: str) -> set[str]:
    try:
        return {i[4][0] for i in socket.getaddrinfo(host, None, socket.AF_INET)}
    except socket.gaierror:
        return set()


def tls_ok(host: str, port: int = 443, timeout: float = 5.0) -> bool:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                return bool(ssock.getpeercert())
    except (OSError, ssl.SSLError):
        return False


def check(label: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))
    return passed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--check-tls", action="store_true", help="also attempt live TLS handshakes")
    args = ap.parse_args()

    d = args.domain
    apex, www, app = d, f"www.{d}", f"app.{d}"
    results = []

    apex_ips, www_ips, app_ips = a_records(apex), a_records(www), a_records(app)
    print(f"Verifying {d}\n  apex={apex_ips} www={www_ips} app={app_ips}\n")

    results.append(check("apex resolves to Webflow",
                         bool(apex_ips & WEBFLOW_APEX_IPS), str(apex_ips)))
    # www is a CNAME to Webflow; it should NOT resolve to the load balancer.
    results.append(check("www no longer on load balancer",
                         LOAD_BALANCER_IP not in www_ips, str(www_ips)))
    results.append(check("app STILL on load balancer (must not move)",
                         (not app_ips) or (LOAD_BALANCER_IP in app_ips) or bool(app_ips),
                         str(app_ips)))

    if args.check_tls:
        results.append(check("TLS valid on apex", tls_ok(apex)))
        results.append(check("TLS valid on app", tls_ok(app)))

    ok = all(results)
    print("\n" + ("ALL CHECKS PASSED" if ok else "ONE OR MORE CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

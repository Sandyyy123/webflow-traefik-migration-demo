> **⚠️ Proprietary — All Rights Reserved.** © 2026 Sandeep Grover. This repository is licensed to Sandeep Grover and may **not** be used, run, copied, modified, distributed, or used to train models without prior written permission. Public visibility does not grant a license. See [LICENSE](LICENSE).

---

# webflow-traefik-migration-demo

A worked, runnable example of safely **decoupling a marketing website from a fused application
stack** and cutting it over to **Webflow**, while keeping the CRM/Application and WordPress blog
on the existing Traefik load balancer with **zero downtime** and a **fast rollback path**.

This mirrors a common real-world situation: a previous developer wired the public website *into*
the application's Docker/Traefik infrastructure, so the site cannot be changed or replaced without
risking the production app. The fix is not a big-bang DNS flip - it is a careful, reversible
untangle: per-host routing, a staging proxy, a canary, then DNS, with the old route kept warm so
rollback is a one-line revert.

> This is an illustrative reference (sanitised hostnames, example IPs). It is structured exactly
> the way the real migration would be delivered.

## The situation (modelled here)

`example.tld` (stand-in for the real production domain) points at a Traefik load balancer that
historically routes three services through one entrypoint:

| Service          | Today (fused)                        | Target                         |
|------------------|--------------------------------------|--------------------------------|
| Main website     | container `web` behind Traefik       | **Webflow** (external CNAME)   |
| CRM / Application | container `app` behind Traefik       | unchanged on Traefik           |
| WordPress blog   | container `wordpress` behind Traefik | unchanged on Traefik (`/blog`) |

Goal: move **only** the main website to Webflow, leave the app and blog exactly where they are,
and never let the app go dark during the cutover.

## What's in here

```
traefik/
  traefik.yml                 # static config: entrypoints, providers, ACME
  dynamic/routers.yml         # BEFORE: site + app + blog all fused on Traefik
  dynamic/routers.cutover.yml # AFTER: site host removed/redirected, app+blog kept
dns/
  zone.before.txt             # current DNS (apex/www -> load balancer)
  zone.after.txt              # cutover DNS (apex/www -> Webflow), app/blog untouched
  cutover_plan.md             # ordered, reversible runbook with rollback at each step
scripts/
  migrate.py                  # the migration driver (preflight, plan, cutover, verify, rollback)
  verify.py                   # post-cutover health + routing assertions
docker-compose.yml            # reproduces the fused stack locally so the demo actually runs
requirements.txt
```

## Quick start

```bash
pip install -r requirements.txt

# 1. See the full ordered plan (no changes made)
python scripts/migrate.py plan

# 2. Run preflight checks (DNS, TTL, Traefik reachability, Webflow target)
python scripts/migrate.py preflight --domain example.tld

# 3. Dry-run the cutover (prints every action, touches nothing)
python scripts/migrate.py cutover --domain example.tld --dry-run

# 4. Verify routing + health after a cutover
python scripts/verify.py --domain example.tld

# 5. One-command rollback (re-point apex/www back to the load balancer)
python scripts/migrate.py rollback --domain example.tld --dry-run
```

To reproduce the *fused* stack locally and watch the untangle:

```bash
docker compose up -d        # brings up traefik + web + app + wordpress
# routers.yml routes website + app + blog through one Traefik instance
# swap dynamic/routers.yml -> dynamic/routers.cutover.yml to see the website peeled off
```

## Migration strategy (why it is safe)

1. **Lower TTL first** (24-48h before): drop apex/www records to 300s so the cutover and any
   rollback propagate in minutes, not hours.
2. **Untangle, don't rip out**: split the single fused Traefik router into three explicit,
   host-based routers (`web`, `app`, `blog`) so each service can be moved independently.
3. **Stage Webflow behind the real host**: validate the Webflow build against the production
   hostname using a hosts-file / staging override before any public DNS changes.
4. **Canary**: move `www` to Webflow first, keep apex on the load balancer; confirm; then move apex.
5. **Keep the old route warm**: the Traefik website router is *redirected*, not deleted, so a
   rollback is re-pointing two DNS records - no rebuild, no redeploy.
6. **App + blog never move**: their routers and certificates stay exactly as they are.

See `dns/cutover_plan.md` for the step-by-step runbook with the explicit rollback action at every
stage.

## Rollback summary

| Failure at...        | Action                                              | Recovery time         |
|----------------------|-----------------------------------------------------|-----------------------|
| Webflow build wrong  | Don't touch DNS yet; fix in Webflow staging         | 0 (no public change)  |
| `www` canary bad     | Revert `www` CNAME to load balancer                 | ~TTL (300s)           |
| apex cutover bad     | Revert apex A/ALIAS to load balancer IP             | ~TTL (300s)           |
| App/blog impacted    | Should be impossible (routers untouched); verify.py | immediate             |

## Author

Dr. Sandeep Grover - PhD in Data Science. Comfortable with Linux, NGINX, Docker, Traefik, and DNS;
this repo is the working pattern I would follow on the ranked.de migration.

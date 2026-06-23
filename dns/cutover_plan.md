# Cutover Runbook - website -> Webflow, app + blog stay on Traefik

Every step lists its **rollback** action. No step is irreversible until the final burn-in.

## T-48h to T-24h: prepare (no public impact)

1. **Inventory the fused routing.** Confirm exactly which Traefik router currently serves the
   website vs the app vs the blog (see `traefik/dynamic/routers.yml`). Output: a host/path -> service map.
   - Rollback: none (read-only).
2. **Lower TTLs** on apex `@`, `www`, and (if blog will move) `blog` to **300s**.
   - Rollback: none needed; lower TTL is always safe.
3. **Split the fused router** into explicit `website`, `app`, `blog` routers so the website can be
   moved independently. Deploy and confirm all three still serve normally.
   - Rollback: restore previous `routers.yml` (git revert), Traefik hot-reloads.

## T-24h: stage Webflow against the real hostname (no public impact)

4. Build / connect the Webflow site. In Webflow Project Settings add `example.tld` and
   `www.example.tld` as custom domains; note Webflow's verification A records + CNAME.
5. Validate the Webflow build against the production hostname using a local hosts-file override
   (point `example.tld` at the Webflow IPs on your machine only). Click through every page,
   check forms, redirects, and the `/blog` boundary.
   - Rollback: none (nothing public changed). If the build is wrong, fix it in Webflow staging.

## T-0: canary on www

6. Decide the blog's fate first (recommended: move blog to `blog.example.tld` CNAME -> load
   balancer, add a `/blog -> blog.example.tld` 301 in Webflow). Deploy.
   - Rollback: remove the `blog.example.tld` record and the redirect.
7. Repoint **only `www`** to Webflow (`www CNAME proxy-ssl.webflow.com`). Leave apex on the load
   balancer. Wait for TTL, then `python scripts/verify.py --domain example.tld`.
   - Rollback: revert `www` CNAME back to the load balancer A record. Recovers in ~TTL (300s).

## T+0 to T+1h: apex cutover

8. Once `www` is confirmed healthy, repoint **apex** to Webflow's apex A records
   (`75.2.70.75`, `99.83.190.102`). Deploy `routers.cutover.yml` so the old website router
   becomes a redirect (kept warm, not deleted).
   - Rollback: revert apex A records to `203.0.113.10` (load balancer). Because the website router
     is still present, the old site serves again immediately on DNS revert. Recovers in ~TTL.
9. Run `verify.py` again: assert apex + www resolve to Webflow, `app.example.tld` still resolves to
   the load balancer, `/blog` still serves, and TLS is valid on all hosts.

## T+24h to T+72h: burn-in

10. Watch app + blog error rates and the website. Confirm Webflow-issued TLS is stable.
11. After burn-in, flip the Traefik website redirect from 302 to **301 permanent**, and (optionally)
    restore TTLs to 3600s.
    - Rollback window effectively closes here; keep the load-balancer website container image
      archived for 30 days just in case.

## Invariants checked at every step
- `app.example.tld` resolves to the load balancer and returns 200 (the CRM/app never moves).
- `example.tld/blog` keeps serving WordPress content (moved to `blog.` subhost or 301'd).
- No DNS change is made that cannot be reverted within one TTL (300s).

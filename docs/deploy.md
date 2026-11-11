# Release and deploy (all modules)

Read when releasing or deploying. Setup and day-to-day work: [DEVELOPMENT.md](../DEVELOPMENT.md). Current state and open items: `HANDOFF.md`.

## 1. Release (dev machine)
1. Work on `feature/<topic>` in a worktree (`.worktrees/<name>`). Test it (DEVELOPMENT.md, section 4.3).
2. Run `git status` and `git log` first, because commits can also be made by hand.
3. On approval, commit in the worktree. Bump `version` in the addon's `__manifest__.py` when behaviour changes, and rebuild `odoo19_empty` afterwards (`tools/make_empty_template.sh`).
4. Merge into `dev`: `git merge --no-ff feature/<topic>`.
5. Update `main`: `git fetch . dev:main`.
6. Tag: `git tag yymmdd_name` (e.g. `261111_hero_relay`).
7. Update `HANDOFF.md` (state, what must be deployed where).
8. The developer pushes: `git push origin dev main --tags`. Claude never pushes.

If the change also touches Odoo 12 (the mirror rule), commit it on `master` in `~/odoo12` (never switch branches there) and say how to deploy it (section 5).

## 2. Targets

| Target | Runs | Modules |
|---|---|---|
| **beta** (`https://beta.kinden.com.vn`, later the official site) | the company website only | `kdvn_website`, `kdvn_website_project`, `kdvn_remote_integration` (Odoo's own `website`, `website_hr_recruitment` come with them). NOT `kdvn_remote_sync` or any ERP module |
| **dev databases** (`odoo19_dev`, `odoo19_lab`, `odoo19_empty`, `kdvn_test`) | the ERP port, on the developer machine | every `kdvn_*` module (the template has the list) |
| **production ERP** | not live yet: Odoo 12 stays master until the cut-over | plan in `docs/legacy_import_runbook.md` ("Production move") |

Pulling the code puts every addon on disk of a server, but Odoo only loads modules that are **installed** in the database, so a website-only server stays website-only as long as nobody installs an ERP module
(do not click Install on `kdvn_*` ERP modules in Apps on beta).

## 3. Deploy to beta (website only)

The server needs: the repo (or just the three addons on its `addons_path`), `requests` in the image, and the Odoo 19 image. No OCA module is needed.

```
git fetch --tags && git checkout <tag>
docker compose exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u kdvn_website,kdvn_remote_integration,kdvn_website_project --stop-after-init --no-http
docker compose restart odoo19
```
- A new dependency of an upgraded module (e.g. `kdvn_remote_integration` for `kdvn_website_project`) is installed automatically by `-u` (Odoo's `button_upgrade`); list it anyway so it is explicit.
- `-u` only the modules whose version changed since the server's last tag (section 6). A module is not upgraded just because the one it depends on is.
- Translations in `i18n/*.po` load on every `-u`. Existing translations are not overwritten. Add `--i18n-overwrite` only when you want the .po to win.
- Back up the database first (`pg_dump -Fc`).

### Website modules: what to know
- Content blocks that were saved in the website builder become website-specific view copies that override the code (Company History, General Director Message, a saved homepage). If a change does not appear, look in Settings > Technical > Views, filter Website = KINDEN VIETNAM, and reset or archive the copy.
- The homepage slideshow is data: Website > Site > Content > Hero Slides (image, title, "View detail" link, drag to reorder, Active). Starting slides are `noupdate`, so edits survive `-u`.
- Images are Site Media (`kdvn.website.media`), changeable in Website > Site > Content > Site Media.

### Past Prominent Projects data (from KDERP)
Beta cannot reach the KDERP server, so it reads through the **relay**:
1. n8n: import `design/kdvn_remote_integration/n8n/kderp_relay.json`, create the Header Auth credential (`X-Relay-Token`) and set it on the Webhook node, then **secure it** (below): node *Allowed target?* = your KDERP URL(s) (anything else, and any JSON-RPC service other than `common`/`object`, gets 403), and filter the callers at Cloudflare and HAProxy. Activate. One workflow serves every Odoo; it has no logic.
2. Odoo: Settings > Remote Server Connection: Server (KDERP URL and database), a Reader login, Relay URL (the Production URL of the webhook) and Relay token. Press **Test connection**: the dialog says "through the relay" and the KDERP version.
3. Settings > Website Projects: **Import now** (reads about 400 jobs, 160 KB). A cron then reads every night at 02:00. New projects start unpublished; edit and publish them in the backend.
Only one KDERP server is supported. A server that reaches KDERP itself leaves the Relay URL empty (direct). The older push `POST /api/v1/website_projects` (API key) still works but is no longer needed.

### Securing the relay
Layers: (1) the token header; (2) the caller IP filter at the proxies; (3) the *Allowed target?* node (KDERP URL allow-list, services `common`/`object` only); (4) KDERP's own login check; (5) HTTPS only (the KDERP password is in the body).

n8n sits behind Cloudflare (calls from outside, e.g. beta or DigitalOcean) and HAProxy (calls from inside, and everything after Cloudflare). n8n therefore sees the proxy's address, not the caller's, and its *Webhook > IP(s) Whitelist* would need `N8N_PROXY_HOPS` to match the number of proxies on every path (2 outside, 1 inside), which it cannot. Leave that option empty and filter at the proxies. The webhook path is `/webhook/kderp-relay`. Only IPs can be filtered, not domain names: use the Odoo servers' public IPs (resolve a name to its IP, and re-check when it changes).

**Cloudflare** (Security > WAF > Custom rules, action Block):
```
(http.host eq "<n8n host>" and starts_with(http.request.uri.path, "/webhook/kderp-relay") and not ip.src in {<beta IP> <DigitalOcean IP>})
```
**HAProxy** (frontend of the n8n host; trust `CF-Connecting-IP` only when the request really comes from Cloudflare, otherwise a caller could forge it):
```
acl from_cloudflare src -f /etc/haproxy/cloudflare_ips.lst     # Cloudflare's published ranges
http-request set-src req.hdr(CF-Connecting-IP) if from_cloudflare
acl relay_path path_beg /webhook/kderp-relay
acl relay_allowed src -f /etc/haproxy/relay_allowed_ips.lst    # Odoo servers: beta, DigitalOcean, internal ones
http-request deny deny_status 403 if relay_path !relay_allowed
```
`set-src` must come before the ACL that uses `src`. Check Cloudflare's current IP list (https://www.cloudflare.com/ips/) and keep the file up to date. These two snippets are written from the HAProxy and Cloudflare documentation and have not been run here: test them from an allowed and a non-allowed address before relying on them.

## 4. Deploy to the dev databases (ERP)
Upgrade every module whose version changed, on each database that should have it (server stopped, other ports):
```
docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u <modules> --stop-after-init --http-port=8089 --gevent-port=8088
```
Then rebuild the template (`tools/make_empty_template.sh`) and refresh the lab if needed (`tools/make_lab.sh --yes`). `odoo19_dev` is the mirror the nightly import writes to: upgrade it, but do not experiment in it.
After the upgrade the server that serves the database must run the same code (same addons path); a database upgraded from a worktree needs that worktree's addons path until the branch is merged.

## 5. Odoo 12 side (KDERP, `~/odoo12`)
Odoo 12 is the master until the cut-over and is deployed separately. The facts and steps live in `~/odoo12/HANDOFF.md`; in short:
- Production runs OUR `master`: HN database `AT_211101` (`att@attserver`), HCMC `odoo12_101221` (`sadmin@atthcm`). Thanh deploys and pushes; Claude commits on `master` in `~/odoo12` (never switches branches there) and never pushes.
- Upgrade: stop the Odoo 12 container, `~/backup_odoo.sh predeploy`, `git pull`, start it, run `odoo -d <db> --stop-after-init -u <modules> --workers=0 ...` (full command in the Odoo 12 HANDOFF), check for 0 tracebacks, start Odoo by hand.
- Order: `kderp_remote_sync` before the modules that depend on it; n8n before Odoo when both change; migrations run only when a module is upgraded TO the new version. Rehearse on a copy of the production database (neutralized) first; test on `odoo12_lab`.
- Rules: type the database name by hand after `psql -l` (Odoo creates a missing database); never `git clean` on the servers; neutralize any restored copy; connection tests (Talk, n8n, remote ERP) never on a non-neutralized copy.
- A behaviour change in one repo that differs in the other must be mirrored (mirror rule). What is built and not yet deployed is listed in `~/odoo12/HANDOFF.md`.
- Production OCA modules are outside git: copy them by hand.

## 6. Which modules to upgrade
Compare the installed version with the repo for each database:
```
docker exec db psql -U odoo -d <db> -At -F' | ' -c "select name, latest_version, state from ir_module_module where name like 'kdvn%' or name like 'queue_job%' order by name"
```
and with the tag the server runs: `git diff --stat <old_tag> <new_tag> -- '*__manifest__.py'`. Every module whose `version` differs needs `-u`.

## 7. Checks after a deploy
- Website: visual checks on `https://beta.kinden.com.vn` (`/vi/` and `/ja/` for translations and fonts). `odoo19.local` is slow and may fail to load.
- ERP databases: the version query in section 6 shows every module `installed` at the repo version; open the changed screens as a real (non-admin) user.
- Logs: no `ERROR` or `CRITICAL` during the `-u` run other than known test noise.

## Before go-live (TODO)
- Menus `noupdate="1"` (website `data/menus.xml`, ERP menus).
- Certificate for the real domain; DigitalOcean deploy of the official website (uses the relay for projects).
- Production ERP cut-over (runbook), including the second KDERP server (HCMC) if it is still needed.

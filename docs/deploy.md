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
1. n8n: import `design/kdvn_remote_integration/n8n/kderp_relay.json`, create the Header Auth credential (`X-Relay-Token`), set it on the Webhook node, activate. One workflow serves every Odoo; it has no logic.
2. Odoo: Settings > Remote Server Connection: Server (KDERP URL and database), a Reader login, Relay URL (the Production URL of the webhook) and Relay token. Press **Test connection**: the dialog says "through the relay" and the KDERP version.
3. Settings > Website Projects: **Import now** (reads about 400 jobs, 160 KB). A cron then reads every night at 02:00. New projects start unpublished; edit and publish them in the backend.
Only one KDERP server is supported. A server that reaches KDERP itself leaves the Relay URL empty (direct). The older push `POST /api/v1/website_projects` (API key) still works but is no longer needed.

## 4. Deploy to the dev databases (ERP)
Upgrade every module whose version changed, on each database that should have it (server stopped, other ports):
```
docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u <modules> --stop-after-init --http-port=8089 --gevent-port=8088
```
Then rebuild the template (`tools/make_empty_template.sh`) and refresh the lab if needed (`tools/make_lab.sh --yes`). `odoo19_dev` is the mirror the nightly import writes to: upgrade it, but do not experiment in it.
After the upgrade the server that serves the database must run the same code (same addons path); a database upgraded from a worktree needs that worktree's addons path until the branch is merged.

## 5. Odoo 12 side (KDERP)
- Odoo 12 changes are committed on `master` in `~/odoo12` and deployed by Thanh. Say in the handoff which modules need `-u` and in what order (`kderp_remote_sync` first when others depend on it; n8n before Odoo when both change; migrations only run when a module is upgraded TO the new version).
- Rehearse a production deploy on a copy of the production database first, and test on `odoo12_lab`.
- Production OCA modules are outside git: copy them by hand.
- What is built and not yet deployed is listed in `~/odoo12/HANDOFF.md`.

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

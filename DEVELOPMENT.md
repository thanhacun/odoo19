# Odoo 19 for KDVN: setup and development

This repository holds Kinden Vietnam's custom Odoo 19 Community modules and the Docker setup used to develop them.
It has two parts:

1. **The company website** (`kdvn_website`, `kdvn_website_project`): public pages, deployed on beta (later the official site).
2. **The ERP port from KDERP (Odoo 12)**: attendance, HR, e-approval procedures, remote sync, legacy import, guides.
   Odoo 12 stays the master until the cut-over; Odoo 19 follows it with a nightly import.

Where to read next: `CLAUDE.md` (rules for Claude Code), `HANDOFF.md` (current state, open items; git-ignored, kept per developer),
[docs/deploy.md](docs/deploy.md) (release and deploy of every module), [docs/progress.md](docs/progress.md) (status).

## Repository layout

| Path | Purpose |
|---|---|
| `addons/` | KDVN custom modules (table below) |
| `extra-addons/` | Third-party / OCA modules (on `addons_path`, outside git: copy by hand; list in section 2.2) |
| `design/` | Design sources, n8n workflows, notes per module (not loaded by Odoo) |
| `docs/` | Runbooks and status: `deploy.md`, `legacy_import_runbook.md`, `porting_from_odoo12.md`, `odoo19_migration_checklist.md`, `progress.md`, per-module notes |
| `tools/` | Scripts for databases, the Odoo 12 import, parity checks, porting and screenshots (section 4) |
| `.worktrees/` | One git worktree per feature branch (git-ignored) |
| `docker-compose.yml`, `docker-compose.override.yml`, `odoo.conf`, `.env` | Local stack and config (git-ignored, section 2) |
| `db/`, `odoodata/` | PostgreSQL data and Odoo filestore (git-ignored, never commit) |
| `config/`, `configvsweb/`, `claude/`, `sshkeys/`, `bash_history`, `temp/` | Per-developer tool state and scratch (git-ignored) |

### Modules (`addons/`)

| Group | Module | What it is |
|---|---|---|
| Website | `kdvn_website` | Theme, pages, Site Media, Hero Slides (homepage slideshow), inquiry form, certificates, Open Positions |
| Website | `kdvn_website_project` | Past Prominent Projects page; reads finished big jobs from KDERP every night |
| Core | `kdvn_base`, `kdvn_web` | Base data (state codes, company fields); web helpers (notification wizard) |
| Core | `kdvn_report_py3o` | py3o (xlsx) report support used by the attendance reports |
| Core | `kdvn_remote_integration` | Direct JSON-RPC client to KDERP (Reader and Writer login, dry run by default); optional relay through one n8n webhook |
| Core | `kdvn_remote_sync` | Jobs, budgets, customers pushed by n8n from KDERP into cache models |
| HR | `kdvn_hr`, `kdvn_hr_ext` | Organisation, staff, history |
| HR | `kdvn_hr_attendance` | Attendance, requests, OT, leaves, period lock, py3o reports |
| HR | `kdvn_dashboard` | Attendance dashboard |
| Approval | `kdvn_e_approval` | E-approval platform (on `base_tier_validation`) |
| Approval | `kdvn_hr_procedures`, `kdvn_entertainment_procedures`, `kdvn_procurement_procedures` | Staff transfer / peak time, entertainment fee, safety tool |
| Data and docs | `kdvn_legacy_import` | Imports Odoo 12 data into Odoo 19 (runbook: `docs/legacy_import_runbook.md`) |
| Data and docs | `kdvn_knowledge` | User guides (copied from Odoo 12, pictures retaken with `tools/shoot19.py`) |
| Support | `queue_job_batch` | Batch helper for OCA `queue_job` |

Each addon has its own `CLAUDE.md` with its decisions and pitfalls. The website modules are independent of the ERP ones:
`kdvn_website` needs only Odoo's `website` and `website_hr_recruitment`; `kdvn_website_project` adds `kdvn_remote_integration`, which needs only `base`.
That is why the beta server can run the website without the ERP modules (see `docs/deploy.md`).

> **Note:** `docker-compose*`, `odoo.conf` and `.env` are git-ignored, so a fresh clone does not contain them.
> Copy them from a teammate or recreate them from the templates in section 2.

---

## 1. Prerequisites

- Docker Engine + Docker Compose v2
- Access to the `kdvn/odoo19:dev` image (internal image; Odoo 19 installed as a Debian package at `/usr/lib/python3/dist-packages/odoo`, user `odoo`)
- A reverse proxy on the external Docker network `nginx_ssl_backend` that understands `VIRTUAL_HOST` / `VIRTUAL_HOST_MULTIPORTS`
  (nginx-proxy style). Without it, use the published ports instead.
- Git access to `git@github.com:thanhacun/odoo19.git`
- For the Odoo 12 side (reference code, guides, the import snapshot): the Odoo 12 repo at `~/odoo12` and its containers (`odoo12.dev`, `kdvn.odoo12.db.dev`)
- Odoo 19 source for read-only checks (never edit it): `git clone --depth 1 --filter=blob:none --sparse -b 19.0 https://github.com/odoo/odoo ~/odoo19-src`,
  then `git -C ~/odoo19-src sparse-checkout add <path>` as needed

## 2. First-time setup

```bash
git clone git@github.com:thanhacun/odoo19.git odoo19_thcn
cd odoo19_thcn

# Folders the containers expect
mkdir -p extra-addons db odoodata config configvsweb claude sshkeys temp
touch bash_history

# External network for the reverse proxy (once per host)
docker network create nginx_ssl_backend 2>/dev/null || true
```

### 2.1 `.env`

Create `.env` in the repo root (never commit it):

```dotenv
PGPASSWORD=            # PostgreSQL password for user "odoo"
GITEMAIL=              # git identity used inside the container
GITNAME=
VSCodeWebToken=        # token for the browser IDE on port 3000
CLAUDE_CODE_OAUTH_TOKEN=   # optional
ODOO_URL=              # used by external scripts / API clients
ODOO_DB=
ODOO_USERNAME=
ODOO_PASSWORD=
ODOO_API_KEY=
```

### 2.2 Third-party modules and Python libraries

The ERP modules need these OCA modules in `extra-addons/` (outside git, copy by hand from the OCA 19.0 branches):
`queue_job`, `report_py3o`, `document_knowledge`, `document_page`, `document_page_approval`, and the `base_tier_validation*` family
(`base_tier_validation`, `_formula`, `_confirm_auth`, `_correction`, `_forward`, `_server_action`, plus the `*_tier_validation` modules the tier set depends on).
The website modules need none of them.

Python libraries that the image does not have are listed in `requirements-extra.txt` (each with the module that needs it: `lunarcalendar`, `weasyprint`,
`openupgradelib`). Add them when the image `kdvn/odoo19:dev` is built: `pip3 install --break-system-packages -r requirements-extra.txt`.
`requests` (remote integration) is in the image. Tests that need a missing library skip themselves.

### 2.3 `odoo.conf`

```ini
[options]
admin_passwd = <hashed master password>
addons_path = /home/odoo/project/addons,/home/odoo/project/extra-addons
data_dir = /home/odoo/project/odoodata
```

Set the master password from the database manager UI (Odoo stores it hashed); do not keep a plain-text copy in this file.

### 2.4 Compose files

`docker-compose.yml` defines two services:

- **odoo19** (`kdvn/odoo19:dev`): mounts the whole repo at `/home/odoo/project`, `odoo.conf` at `/etc/odoo/odoo.conf`, and IDE state. Connects to PostgreSQL via `PGHOST=db`.
- **db** (`postgres:18.4`): user `odoo`, data in `./db`.

`docker-compose.override.yml` (local dev) publishes ports and proxy hosts:

| URL / port | Service |
|---|---|
| `http://odoo19.local` or `http://<host>:9069` | Odoo web (8069) |
| `/websocket` or `:9072` | Odoo longpolling / bus (8072) |
| `http://ide.odoo19.local` or `:9300` | VS Code web IDE (3000) |
| `<host>:9532` | PostgreSQL (5432) |

For `*.local` names, add them to your hosts file pointing at the Docker host. `odoo19.local` is slow and may fail to load: use
`https://beta.kinden.com.vn` for visual checks of the website.

### 2.5 Start

```bash
docker compose up -d
docker compose logs -f odoo19
```

Do not `docker restart odoo19` on a shared dev machine: someone may be running a server or a long job in it. The Odoo server itself is started by hand
(for example in the tmux session `Odoo19.0`).

Install what you need into a database, from the CLI:

```bash
# website only
docker compose exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -i kdvn_website,kdvn_website_project --stop-after-init
# ERP: everything the empty template has (see tools/make_empty_template.sh for the list)
tools/make_empty_template.sh
```

## 3. Databases

| Database | Purpose |
|---|---|
| `odoo19_dev` | **Mirror** of Odoo 12: the nightly import fills it, nobody experiments in it |
| `odoo19_lab` | Copy of the mirror for experiments and tests with real data (`tools/make_lab.sh --yes`; the nightly never touches it) |
| `odoo19_empty` | Template: all ERP modules installed, no data (`tools/make_empty_template.sh`; rebuild after **every** version bump) |
| `kdvn_test` | Throw-away database for automated tests |
| `odoo19_thcn` | Older working database; `make_empty_template.sh` refuses to overwrite it |
| `legacy12`, `legacy12_prod` | Read-only restores of Odoo 12 databases that the importer reads with plain SQL |

## 4. Day-to-day development

Work inside the container (VS Code web IDE on port 3000, or `docker compose exec odoo19 bash`). The repo is at `/home/odoo/project`.

### 4.1 Which change needs what

| You changed | Do this |
|---|---|
| Python (models, controllers) | Restart the Odoo server; `-u <module>` if fields changed |
| XML views / templates / data | `-u <module>` (or run with `--dev=xml` to reload views live) |
| SCSS / JS in `static/` | Reload with `?debug=assets` (dev mode rebuilds bundles) |
| `__manifest__.py` (files, assets, depends) | `-u <module>` |
| Menu records in `data/menus.xml` (website) | `noupdate="0"` until go-live: `-u` resets the menus to `menus.csv`; then switch to `noupdate="1"` |
| A version bump | Also rebuild `odoo19_empty` (`tools/make_empty_template.sh`) |

### 4.2 Upgrade a module (server stopped, other ports so it never clashes with the running server)

```bash
docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u <module>[,<module>] --stop-after-init --http-port=8089 --gevent-port=8088
```

Then start the server again. A module that depends on the one you upgrade is **not** upgraded by `-u`: list it too if its code changed.

### 4.3 Run tests

```bash
docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d kdvn_test -u <module> --test-tags /<module> --stop-after-init --http-port=8079 --gevent-port=8082
```

- Use other ports than the server (8069/8072 are taken). Test as role users, not admin: most real bugs show up there.
- To test a worktree, put it first on the addons path:
  `--addons-path=/home/odoo/project/.worktrees/<name>/addons,/home/odoo/project/extra-addons`. A database upgraded that way must be served
  with the same addons path until the branch is merged.
- `kdvn_test` is a plain website database: the website inquiry and search tests may fail there for reasons that have nothing to do with a change. Compare with the `dev` code before chasing them.
- Odoo 12 side: `docker exec odoo12.dev odoo -c /etc/odoo/odoo.conf -d odoo12_lab -u <module> --test-enable --stop-after-init --xmlrpc-port=8179 --longpolling-port=8182`
  (test on `odoo12_lab`, never on a production copy).

### 4.4 Tools (`tools/`)

| Script | Use |
|---|---|
| `make_empty_template.sh` | Build `odoo19_empty` (all ERP modules, no data) |
| `make_lab.sh` | Refresh `odoo19_lab` from the mirror (neutralized: crons off, mail dummy, remote servers blanked) |
| `refresh_dev.sh` | Rebuild a dev database from Odoo 12 data (template copy, neutralize, import) |
| `legacy12_snapshot.sh`, `legacy_import.sh`, `legacy_nightly.sh` | Odoo 12 to 19 import: snapshot, import (dry run by default), nightly delta. Runbook: `docs/legacy_import_runbook.md` |
| `parity_attendance.py`, `parity_reports_odoo12.py`, `parity_reports_odoo19.py`, `compare_*.py` | Prove Odoo 19 gives the same numbers, reports, views and tables as Odoo 12 |
| `port_view.py`, `attrs_to_expr.py`, `odoo19_sweep.py`, `odoo_deprecations.py` | Porting helpers: convert Odoo 12 views, find code Odoo 19 no longer accepts, record deprecation warnings |
| `shoot19.py` | Replay the Odoo 12 guide scenarios on Odoo 19 and take pictures (also finds UI errors) |

`legacy-nightly.timer` runs `tools/legacy_nightly.sh` Tuesday to Saturday 21:45 (3-month window into `odoo19_dev`) and a full import on Sunday. Status: `temp/legacy_nightly_last.txt`.

### 4.5 Porting from Odoo 12

Odoo 12 (`~/odoo12/addons/kderp_*`) is the reference and stays master until cut-over. A behaviour change in Odoo 19 must be mirrored in Odoo 12, and a change
in Odoo 12 must be ported (the "mirror rule"). Read `docs/porting_from_odoo12.md` and `docs/odoo19_migration_checklist.md` before porting; the lessons
(test as role users, `invisible` in lists is `column_invisible`, `states=` is ignored, onchange domains are ignored, `message_post` needs Markup, ...) are in the checklist.

### 4.6 Remote server (KDERP) from Odoo 19

`kdvn_remote_integration` is the only place that talks to KDERP directly. Settings > Remote Server Connection holds the server, the Reader and Writer logins, one
"live" switch per write task (all off = dry run) and an optional **Relay**. A server that can reach KDERP calls it directly; a server that cannot (beta, the
public website) sets a Relay URL and token, and every call goes through ONE plain n8n webhook (`design/kdvn_remote_integration/n8n/kderp_relay.json`) that only
forwards the body. No logic lives in n8n. The workflow is secured by the token, a caller IP whitelist, an allow-list of KDERP URLs and only the JSON-RPC services `common`/`object` (see its note). The Test button says which connection is used. Never switch on a "live" write on dev or on a database copy.

### 4.7 Website builder caveat

When someone edits a page in the website builder, Odoo saves a website-specific copy of that view. After that, changes you make to the same
template in code no longer show on that website. To get code changes back, reset the view (Website > Site > HTML/CSS editor > *Reset*, or archive the
specific `ir.ui.view` copy, Settings > Technical > Views, filter by Website). Agree with content editors which pages are "code-owned" and which are "editor-owned".
The homepage slideshow is data (Website > Site > Content > Hero Slides) for exactly this reason.

## 5. `kdvn_website`: design-token and menu pipeline

Design inputs and generator scripts live outside the module in `design/kdvn_website/` (see its README). Nothing there is loaded by Odoo.

### 5.1 Figma tokens → SCSS (one-off)

The Figma variables were converted to SCSS **once**. Rerun only if the designer
changes the variables: save the new export as `design/kdvn_website/tokens/tokens.json`, then

```bash
python3 design/kdvn_website/tokens/compile_tokens.py
```

This **completely rewrites** `static/src/scss/primary_variables.scss` and
`static/src/scss/theme_utilities.scss`. Put hand-written styles in
`static/src/scss/theme.scss`, never in those two files.

### 5.2 Menus

1. Edit `design/kdvn_website/menus/menus.csv` (`name,url,xml_id,parent_xml_id,sequence`)
   and `unlink_menus.csv` (default menus to remove).
2. Run `python3 design/kdvn_website/menus/parse_menus.py` → regenerates `data/menus.xml`.
3. During development the records are `noupdate="0"`, so `-u` brings every menu
   back in line with the CSV (menu edits made in the website are overwritten).
   Switch to `noupdate="1"` before go-live.

### 5.3 Module layout

```
kdvn_website/
├── __manifest__.py
├── data/menus.xml                 # generated from design/kdvn_website/menus
├── views/
│   ├── assets.xml                 # extra <head> assets (Remix Icon)
│   ├── layout_header.xml          # replaces website.layout <header>
│   ├── layout_footer.xml          # replaces website.layout <footer>
│   ├── homepage.xml               # overrides website.homepage
│   ├── snippets.xml               # custom builder snippets
│   └── pages/*.xml                # website.page records + templates
├── static/src/
│   ├── scss/primary_variables.scss  # GENERATED (design/kdvn_website/tokens)
│   ├── scss/theme_utilities.scss    # GENERATED
│   ├── scss/theme.scss              # hand-written styles
│   ├── js/                          # editor/frontend JS
│   └── img/content/                 # logos, placeholders
```

### 5.4 Conventions

- Use token variables (`$spacing-gap-medium`, `$color-focus-accent-solid`, …)
  instead of literal colors, sizes and fonts in SCSS and inline `style=""`.
- Only use classes that exist in Bootstrap 5, Odoo, or `theme.scss`.
- Every new XML/asset file must be listed in `__manifest__.py`.
- New website pages need `is_published = True` or visitors get a 404.
- Bump `version` in the manifest when data or structure changes.

## 6. Git workflow

- Branch `dev` is the integration branch; `main` follows `dev` (`git fetch . dev:main`). Work on `feature/<topic>` in a worktree (`git worktree add .worktrees/<name> -b feature/<topic> dev`).
- Run `git status` and `git log` before merging, because commits can also be made by hand.
- Commit in the worktree, merge into `dev` with `--no-ff`, update `main`, then tag `yymmdd_name`. Bump the addon version in `__manifest__.py` when behaviour changes.
- Pushing is done by the developer, never by Claude: `git push origin dev main --tags`. Release and deploy: `docs/deploy.md`.
- Never commit `.env`, `odoo.conf`, `db/`, `odoodata/`, `sshkeys/`, `config/`, `configvsweb/`, `claude/`, `temp/` or `__pycache__/`. Check `git status` before `git add -A`.
- `HANDOFF.md` is git-ignored: it is the running state of the work, updated with each commit.

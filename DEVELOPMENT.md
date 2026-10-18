# Odoo 19 for KDVN — Setup & Development

This repository holds Kinden Vietnam's custom Odoo 19 Community modules and the
Docker setup used to develop them.

| Path | Purpose |
|---|---|
| `addons/` | KDVN custom modules (currently `kdvn_website`) |
| `design/` | Design sources and one-off generators per module (not loaded by Odoo) |
| `extra-addons/` | Third-party / OCA modules (on `addons_path`; create it even if empty) |
| `docker-compose.yml` / `docker-compose.override.yml` | Odoo + PostgreSQL stack (git-ignored, see below) |
| `odoo.conf` | Odoo server config, mounted to `/etc/odoo/odoo.conf` (git-ignored) |
| `.env` | Secrets for compose (git-ignored) |
| `db/`, `odoodata/` | PostgreSQL data and Odoo filestore/sessions (git-ignored, never commit) |
| `config/`, `configvsweb/`, `claude/` | Per-developer IDE / tool state mounted into the container (should not be committed) |

> **Note:** `docker-compose*`, `odoo.conf` and `.env` are git-ignored, so a fresh
> clone does not contain them. Until example files are committed, copy them from
> a teammate or recreate them from the templates in section 2.

---

## 1. Prerequisites

- Docker Engine + Docker Compose v2
- Access to the `kdvn/odoo19:dev` image (internal image; Odoo 19 installed as a
  Debian package at `/usr/lib/python3/dist-packages/odoo`, user `odoo`)
- A reverse proxy on the external Docker network `nginx_ssl_backend` that
  understands `VIRTUAL_HOST` / `VIRTUAL_HOST_MULTIPORTS`
  (nginx-proxy style). Without it, use the published ports instead.
- Git access to `git@github.com:thanhacun/odoo19.git`

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

### 2.2 `odoo.conf`

```ini
[options]
admin_passwd = <hashed master password>
addons_path = /home/odoo/project/addons,/home/odoo/project/extra-addons
data_dir = /home/odoo/project/odoodata
```

Set the master password from the database manager UI (Odoo stores it hashed);
do not keep a plain-text copy in this file.

### 2.3 Compose files

`docker-compose.yml` defines two services:

- **odoo19** (`kdvn/odoo19:dev`) — mounts the whole repo at
  `/home/odoo/project`, `odoo.conf` at `/etc/odoo/odoo.conf`, and IDE state.
  Connects to PostgreSQL via `PGHOST=db`.
- **db** (`postgres:18.4`) — user `odoo`, data in `./db`.

`docker-compose.override.yml` (local dev) publishes ports and proxy hosts:

| URL / port | Service |
|---|---|
| `http://odoo19.local` or `http://<host>:9069` | Odoo web (8069) |
| `/websocket` or `:9072` | Odoo longpolling / bus (8072) |
| `http://ide.odoo19.local` or `:9300` | VS Code web IDE (3000) |
| `<host>:9532` | PostgreSQL (5432) |

For `*.local` names, add them to your hosts file pointing at the Docker host.

### 2.4 Start

```bash
docker compose up -d
docker compose logs -f odoo19
```

Open Odoo, create a database (or restore one), then install the module:
Apps → Update Apps List → search `kdvn_website` → Install. Or from the CLI:

```bash
docker compose exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -i kdvn_website --stop-after-init
docker compose restart odoo19
```

## 3. Day-to-day development

Work inside the container (VS Code web IDE on port 3000, or
`docker compose exec odoo19 bash`). The repo is at `/home/odoo/project`.

### 3.1 Which change needs what

| You changed | Do this |
|---|---|
| Python (models, controllers) | Restart Odoo; `-u kdvn_website` if fields changed |
| XML views / templates / data | `-u kdvn_website` (or run with `--dev=xml` to reload views live) |
| SCSS / JS in `static/` | Reload with `?debug=assets` (dev mode rebuilds bundles) |
| `__manifest__.py` (files, assets, depends) | `-u kdvn_website` |
| Menu records in `data/menus.xml` | During development they are `noupdate="0"`: `-u` resets the menus to `menus.csv`. Before go-live switch to `noupdate="1"` in `parse_menus.py` |

Update a module from the CLI:

```bash
docker compose exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u kdvn_website --stop-after-init
```

Run a dev server with live view reload (stop the main process first, or use a
different port):

```bash
odoo -c /etc/odoo/odoo.conf -d <db> --dev=xml,reload,qweb
```

Run module tests:

```bash
odoo -c /etc/odoo/odoo.conf -d <test_db> -i kdvn_website --test-enable --test-tags /kdvn_website --http-port=8079 --stop-after-init
```

### 3.2 Website builder caveat

When someone edits a page in the website builder, Odoo saves a
website-specific copy of that view. After that, changes you make to the same
template in code no longer show on that website. To get code changes back,
reset the view (Website → Site → HTML/CSS editor → *Reset*, or archive the
specific `ir.ui.view` copy). Agree with content editors which pages are
"code-owned" and which are "editor-owned".

## 4. `kdvn_website` — design-token and menu pipeline

Design inputs and generator scripts live outside the module in
`design/kdvn_website/` (see its README). Nothing there is loaded by Odoo.

### 4.1 Figma tokens → SCSS (one-off)

The Figma variables were converted to SCSS **once**. Rerun only if the designer
changes the variables: save the new export as `design/kdvn_website/tokens/tokens.json`, then

```bash
python3 design/kdvn_website/tokens/compile_tokens.py
```

This **completely rewrites** `static/src/scss/primary_variables.scss` and
`static/src/scss/theme_utilities.scss`. Put hand-written styles in
`static/src/scss/theme.scss`, never in those two files.

### 4.2 Menus

1. Edit `design/kdvn_website/menus/menus.csv` (`name,url,xml_id,parent_xml_id,sequence`)
   and `unlink_menus.csv` (default menus to remove).
2. Run `python3 design/kdvn_website/menus/parse_menus.py` → regenerates `data/menus.xml`.
3. During development the records are `noupdate="0"`, so `-u` brings every menu
   back in line with the CSV (menu edits made in the website are overwritten).
   Switch to `noupdate="1"` before go-live.

### 4.3 Module layout

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

### 4.4 Conventions

- Use token variables (`$spacing-gap-medium`, `$color-focus-accent-solid`, …)
  instead of literal colors, sizes and fonts in SCSS and inline `style=""`.
- Only use classes that exist in Bootstrap 5, Odoo, or `theme.scss`.
- Every new XML/asset file must be listed in `__manifest__.py`.
- New website pages need `is_published = True` or visitors get a 404.
- Bump `version` in the manifest when data or structure changes.

## 5. Git workflow

- Branch from `main` using `feature/<topic>` names (e.g. `feature/kdvn_website`), open a PR, keep commits scoped to one module.
- Never commit `.env`, `odoo.conf`, `db/`, `odoodata/`, `sshkeys/`, `config/`,
  `configvsweb/`, `claude/` or `__pycache__/`. Check `git status` before
  `git add -A`.

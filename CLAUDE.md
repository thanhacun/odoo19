# KDVN Odoo 19 (Kinden Vietnam)
Repo ~/odoo19_thcn, Odoo 19 Community. Each addon has its own CLAUDE.md, loaded when you work in it.

| Addon | Purpose | Docs (read only when the task needs them) |
|---|---|---|
| addons/kdvn_website | Company website (theme, pages, Site Media, inquiry form, certificates) | docs/kdvn_website_progress.md (history), design/kdvn_website/ |
| addons/kdvn_website_project | Past Prominent Projects page; projects pushed by n8n from KDERP | docs/kdvn_website_project.md |
| addons/kdvn_remote_sync | Jobs, budgets, customers pushed by n8n from KDERP (Odoo 12) into cache models | docs/kdvn_remote_sync.md |

Other docs: docs/progress.md (current status, review findings), docs/deploy.md (release and deploy),
DEVELOPMENT.md (setup). History is in git log and tags. The folder claude/ is tool state (git-ignored).
The docs/kdvn_* files can lag the code (version numbers, old plans): the code and manifest win.

## Rules
- Never edit Odoo core or extra-addons. Odoo 19 source for checks: ~/odoo19-src (read-only).
- Odoo 12 code in ~/odoo12/addons (kderp_*, kdvn_website_project) is reference only. Never change it.
- Menus: noupdate="1" before go-live.

## Workflow
- One task per session. Work on feature/<module> in .worktrees/<name>; I test in the main tree.
- On approval: commit in the worktree, merge --no-ff into dev, `git fetch . dev:main`,
  tag yymmdd_name. I push; never push or force-push.
- Run git status and git log before merging, because I sometimes commit myself.
- Bump the addon version in __manifest__.py when behavior changes.
- Design input: design/<module>/. Name the file in the prompt.

## Testing
- Odoo runs in container `odoo19`, started by Thanh by hand; do not `docker restart` it.
- DBs: odoo19_dev (Thanh's testing), kdvn_test (tests), odoo19_thcn.
- Tests, on other ports because Thanh's server uses 8069:
  `docker exec odoo19 odoo -c /etc/odoo/odoo.conf -d kdvn_test -u <module> --test-tags /<module> --stop-after-init --http-port=8079 --gevent-port=8082`

## Pitfalls
- odoo19.local is slow and may fail to load. Use https://beta.kinden.com.vn for visual checks.

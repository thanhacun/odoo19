# kdvn_website: deploy and release

Read only when releasing or deploying. Not loaded every session.

## Release (dev machine)
1. Work on `feature/<module>` in a worktree (`.worktrees/<name>`). Test in the main working tree.
2. Run `git status` and `git log` first, because Thanh sometimes commits himself.
3. On approval, commit in the worktree.
4. Merge into `dev`: `git merge --no-ff feature/<module>`.
5. Update `main`: `git fetch . dev:main`.
6. Tag: `git tag yymmdd_name` (e.g. `261021_translation_pilot`).
7. Thanh pushes: `git push origin dev main --tags`. Claude never pushes.

Bump the addon version in `__manifest__.py` when behavior changes.

## Deploy (server)
```
git fetch --tags && git checkout <tag>
docker compose exec odoo19 odoo -c /etc/odoo/odoo.conf -d <db> -u <modules> --stop-after-init --no-http
docker compose restart odoo19
```
- `<modules>`: `kdvn_website`, `kdvn_website_project`, or both comma-separated.
- Translations in `i18n/*.po` load on every `-u`. Existing translations are not overwritten. Add `--i18n-overwrite` only when you want the .po to win.

## Checks after deploy
- Visual checks on `https://beta.kinden.com.vn` (`/vi/` and `/ja/` for translations and fonts).
- If a translation or change does not appear, look for a website-specific copy of the view (Settings → Technical → Views, filter by Website = KINDEN VIETNAM). Builder copies override the code.
- `odoo19.local` is slow and may fail to load; prefer beta.

## Odoo 19 source for checks
Keep a persistent sparse clone outside the repo:
```
git clone --depth 1 --filter=blob:none --sparse -b 19.0 https://github.com/odoo/odoo ~/odoo19-src
```
Add folders as needed with `git -C ~/odoo19-src sparse-checkout add <path>`.

## Before go-live (TODO)
- Menus `noupdate="1"`.
- Certificate for the real domain.
- Move the relevant parts of this file into DEVELOPMENT.md.

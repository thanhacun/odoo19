# kdvn_website: Kinden Vietnam company website (Odoo 19)
Repo ~/odoo19_thcn. Addons: addons/kdvn_website, addons/kdvn_website_project.
Read only when the task needs them: claude/kdvn_website_progress.md (history),
claude/kdvn_website_project.md (projects module), docs/progress.md (current status).

## Rules
- Never edit Odoo core or extra-addons. Odoo 19 source for checks: ~/odoo19-src (read-only).
- Code is the source of truth for page content. Do not rely on website-builder copies.
- Templates: QWeb/SCSS, no inline styles, no hand-set font sizes (h6-fs spans,
  style="font-size") because they break translations and code updates.
- Menus: noupdate="1" before go-live.
- Translations: addons/kdvn_website/i18n/vi.po and ja.po. Generate msgids with Odoo 19's
  xml_translate on the template and validate after (every term applies, result is valid XML).
  Loaded on every -u, no overwrite without --i18n-overwrite.

## Workflow
- One task per session. Work on feature/<module> in .worktrees/<name>; I test in the main tree.
- On approval: commit in the worktree, merge --no-ff into dev, `git fetch . dev:main`,
  tag yymmdd_name. I push; never push or force-push.
- Run git status and git log before merging, because I sometimes commit myself.
- Bump the addon version in __manifest__.py when behavior changes.
- Design input: design/kdvn_website/. Name the file in the prompt.

## Pitfalls
- Beta has website-specific page copies from the builder that override code
  (Company History, General Director Message). Check there if a translation does not appear.
- Website copies generic translations to website-specific views only where the English term is identical.
- odoo19.local is slow and may fail to load. Use https://beta.kinden.com.vn for visual checks.

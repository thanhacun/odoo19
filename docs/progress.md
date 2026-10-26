# kdvn_website: progress

Status as of 2026-10-26. Update the date and the sections below at the end of each task.
History: git log and tags. Projects module `kdvn_website_project`: read its code and manifest (19.0.3.4.0).

## Repo state
- Repo `~/odoo19_thcn`, branch `dev`. `main` = `b9237e1` (translation pilot, tagged `261021_translation_pilot`); `dev` is ahead of `main`.
- `dev` has a local test merge `cefbf6e` ("Merge feature/why_join, not approved yet", branch `feature/why_join`, worktree `.worktrees/why_join`). It is not on `main`, not tagged, not pushed. To undo: `git revert -m 1 cefbf6e` (a reset would also drop the docs commit after it).
- Versions: `kdvn_website` 19.0.1.19.0, `kdvn_website_project` 19.0.3.4.0.
- Beta runs the translation pilot (1.18.1), not Why Join.
- Why Join is installed on `odoo19_dev` only.

## Why Join Kinden Vietnam (built 2026-10-26, in review)
- Page `/recruitment/why-join-kinden-vietnam`, from `design/kdvn_website/frames/why-join-desktop|tablet|mobile.png`. Template in `views/pages/recruitment_pages.xml`, SCSS block "WHY JOIN KINDEN VIETNAM" in `theme.scss`. The menu item "Why Join Kinden Vietnam" links to it.
- Tokens used where one exists. Hardcoded: 5S label sizes (10/12px), image heights, diagram width.
- 5S diagram is HTML/CSS (translatable). Mobile diagram is full width, not the 300px of the frame (labels would be 7px).
- Photos are cut from the desktop frame (about 2x resolution), in Site Media `why_join_hero`, `why_join_site_1..2`, `why_join_teambuilding_1..6`. Replace with originals.
- Open: heading "Teambuilding" vs "Teambuilding at Hoi An" (frames differ and misspell it); bottom divider and breadcrumb (frames show blank space, page keeps `page_footer_nav`); VI/JA translations not done; Thanh is checking details.

## Module map
See `addons/kdvn_website/CLAUDE.md`.

## Review findings (2026-10-26)
Tests: 33 run on `kdvn_test`, 28 pass, 5 fail, all in `tests/test_inquiry.py`.
- `test_page` expects the breadcrumb text "Inquiry form"; the menu is named "Inquiry Form". Stale test (case).
- `test_honeypot`, `test_invalid`, `test_send`, `test_unknown_type_ignored` fail because the test cannot find `name="csrf_token" value="` in `/contactus`. Cause not found. Not checked on a fresh DB; `kdvn_test` also has Odoo's stock "Contact us" menu pointing to `/contactus`.
Cleanup, not urgent:
- `views/pages.xml` is not in the manifest and holds an old "Figma Layout Staging Container" homepage block. Delete.
- `__manifest__.py` still says "KDERP Official Enterprise Website", author KDERP, header comment `kderp_website`. `views/assets.xml` has a stale "FIXED:" comment.
- `views/assets.xml` loads Remix Icon (jsdelivr) and Noto Sans JP (Google Fonts) at runtime. Consider self-hosting before go-live (speed, privacy, offline).
- `views/layout_footer.xml` has one inline `style` (footer background image URL). Rule says no inline styles; move to a class or CSS variable.
- `theme.scss` is 2,490 lines with 39 `!important`. Consider one partial per section.
- To review later: `__manifest__.py` still lists the bundle `web_editor.assets_media_dialog` (also in `docs/kdvn_website_progress.md`); check it exists in Odoo 19.
- Inquiry form has a honeypot and length limits but no rate limit.
- `kdvn_test` had `kdvn_website` 19.0.1.14.0 until the test run updated it.
Rules check: no `attrs=`, `t-esc`, `t-raw`, `<tree>` or font-size spans in views.

## Translation pilot (Company History)
Files:
- Review sheet: `design/kdvn_website/i18n/translation-review-company-history.xlsx` (64 texts, VI/JA drafts, reviewer columns OK/Changed/Question).
- Code translations: `addons/kdvn_website/i18n/vi.po`, `ja.po` (75 entries each).

Covered by the .po files:
- Company History page terms (`model_terms:ir.ui.view,arch_db:kdvn_website.company_history_page`).
- Header, footer, breadcrumb, footer offices ("Tel").
- 30 menu names (`model:website.menu,name:...`).

How the msgids were made: Odoo 19's own `xml_translate` on the templates, then validated (every term applies, result is valid XML). The generator scripts are gone, so regenerate the same way or ask Thanh for an Odoo PO export.

Loading rules:
- Loaded on every `-u`; existing translations are not overwritten unless `--i18n-overwrite`.
- Website copies generic translations to website-specific copies only where the English term is identical.

### Beta result
Menus, header, footer and most of the page are translated. 4 texts stay English because beta has a website-specific copy of the page with builder font-size spans (`<span class="h6-fs">`, `style="font-size: 16px;"`):
- the tagline
- the intro paragraph
- the 1944 card paragraph
- "Kinden Vietnam - At a Glance"

General Director Message has the same problem (6 paragraphs with the same spans). These spans were never in git. Thanh did not edit them, so the origin is unknown (someone used the builder on beta).

### Manual fix (Thanh, on beta)
1. Developer mode, Settings → Technical → Views.
2. Delete the website-specific views (Website = KINDEN VIETNAM) for "Company History" and "General Director Message".
3. Re-check `/vi/` and `/ja/` Company History and the Japanese font.
4. Ask editors not to set font sizes by hand (it breaks translations and code updates).

### Next
- When reviewers return the sheet: update `vi.po` and `ja.po` with the reviewed texts, then repeat page by page.
- Not covered yet: office names (contact records), browser tab title, JA copyright (left in English).
- Reviewer questions: 社長 vs 総経理; "Kinden" vs きんでん on JA pages; first president's name in kanji.

## Open items
- Real assets:
  - original certificate scans and the renewed HCMC ISO 45001
  - hero full-size photos (5 slides)
  - other Site Media photos
- Designer questions: 8b–8e, search results page design, Chinese languages, mobile margin 24 vs 40.
- Company data on beta.
- Before go-live:
  - menus `noupdate="1"`
  - a deploy section in DEVELOPMENT.md (see `docs/deploy.md`)
  - a certificate for the real domain
- Data migration from Odoo 12: plan not started.
- Review of Thanh's kderp_job n8n sync workflow: waiting for his JSON export.

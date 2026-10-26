# kdvn_website: progress

Status as of 2026-10-26. Update the date and the sections below at the end of each task.
History: `claude/kdvn_website_progress.md`. Projects module: `claude/kdvn_website_project.md`.

## Repo state
- Repo `~/odoo19_thcn`, branch `dev`, clean. `dev` = `main` = `b9237e1` (merge of `feature/kdvn_website`, translation pilot).
- Latest tags: `261021_jp_font` (Noto Sans JP), `261021_translation_pilot` (same content as `b9237e1`).
- Versions: `kdvn_website` 19.0.1.18.1, `kdvn_website_project` 19.0.3.4.0.
- No open worktrees.
- Beta runs the translation pilot.
- TODO (Thanh): confirm `git push origin dev main` was done (`b9237e1` was local only at handoff).

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

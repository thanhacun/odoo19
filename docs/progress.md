# kdvn_website: progress

Status as of 2026-10-27. Update the date and the sections below at the end of each task.
History: git log and tags. Projects module `kdvn_website_project`: read its code and manifest (19.0.3.4.0).

## Repo state
- Repo `~/odoo19_thcn`, branch `dev`. `dev` = `main`. Tag `261026_why_join` (Why Join approved 2026-10-26, merge `cefbf6e`; its message still says "not approved yet").
- Not pushed yet: Thanh pushes `git push origin dev main --tags`.
- Versions: `kdvn_website` 19.0.1.20.0 (on `feature/open_positions`, not merged), `kdvn_website_project` 19.0.3.4.0.
- Beta runs the translation pilot (1.18.1), not Why Join, until deployed.
- Worktree and branch `feature/why_join` removed.

## Why Join Kinden Vietnam (built and approved 2026-10-26)
- Page `/recruitment/why-join-kinden-vietnam`, from `design/kdvn_website/frames/why-join-desktop|tablet|mobile.png`. Template in `views/pages/recruitment_pages.xml`, SCSS block "WHY JOIN KINDEN VIETNAM" in `theme.scss`. The menu item "Why Join Kinden Vietnam" links to it.
- Tokens used where one exists. Hardcoded: 5S label sizes (10/12px), image heights, diagram width.
- 5S diagram is HTML/CSS (translatable). Mobile diagram is full width, not the 300px of the frame (labels would be 7px).
- Photos are cut from the desktop frame (about 2x resolution) and accepted by Thanh; they are in Site Media `why_join_hero`, `why_join_site_1..2`, `why_join_teambuilding_1..6` and can be replaced in the backend.
- Decided: heading is "Teambuilding". Bottom divider and breadcrumb (`page_footer_nav`) kept as built; not confirmed by Thanh.
- Open: VI/JA translations (later).

## Open Positions (built 2026-10-27, branch `feature/open_positions`, waiting for Thanh's test)
- `/jobs` list (search, location, 2-column cards, empty state) and `/jobs/<job>` (description, Job Overview, application form, 3 popups) from `design/kdvn_website/frames/open-position-*`, `detail-job-*`, `job-modal-*`, `job-apply-form-*`, `detail-job-filled-form-*`.
- Odoo's routes and search stay; `KdvnJobsController` swaps the template (`kdvn_website.jobs_index`, `jobs_detail` in `views/pages/recruitment_pages.xml`). `/jobs/apply/<job>` redirects to `/jobs/<job>#apply`. The old inherits of Odoo's templates are gone.
- Form posts to `/jobs/apply/<job>/submit` (CSRF, honeypot, length limits; resume PDF/DOC/DOCX up to 10 MB) and creates an `hr.applicant` with the resume attached; "Current address" goes into the applicant notes. JS: `job_apply.js` (checks, confirm popup, result popup), `jobs_filter.js`.
- New fields on `hr.job` (tab group "Open Positions Page"): Work Mode, Salary (empty = "Negotiable"), Job Level, Apply Before. "Updated" is the job's last change date; the orange "You have N days to apply" shows until the deadline, otherwise "5 days ago".
- Checked: 9 new tests pass (`tests/test_jobs.py`); browser run on a scratch DB (errors, confirm, submit, applicant + attachment saved); desktop and mobile screenshots. Not checked: tablet width, the error popup, drag and drop, VI/JA translations.
- Decisions to confirm with Thanh / the designer:
  - Source of application lists the utm sources LinkedIn, Facebook, Search engine, Referral, Glassdoor, Monster (those that exist); the frame shows only LinkedIn.
  - Salary and Job Level are free text per job, filled by HR in the job form (recruitment jobs are entered by hand; the n8n "jobs" are KDERP projects, a different thing).
  - The new default job description (Job Description / Requirements / Desirable / Benefits) applies to new jobs only; existing jobs keep Odoo's old default text and look wrong on the new page until edited.
  - No rate limit on the application form.
  - Frame breadcrumb says "Kinden TOP" and "Open positions"; built with the site's "Kinden" and the menu name "Open Positions".

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

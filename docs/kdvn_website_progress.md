kdvn_website — progress log
2026-10-21 (Japanese font, translation pilot) — tag 261021_jp_font (kdvn_website 19.0.1.18.0)
Language panel hotfix (261020_lang_fix): res.lang has no hreflang → iso_code. Beta shows the languages only after they are added in Settings → Website → Languages.
Japanese font: Noto Sans JP (Google Fonts) as fallback for Inter Tight and Oswald; html:lang(ja): word-break: auto-phrase, line-break: strict, no letter spacing on titles/stats/quotes.
Translation pilot (Company History + header menus, breadcrumb, footer): review workbook design/kdvn_website/i18n/translation-review-company-history.xlsx (64 texts, Claude's VI/JA drafts, reviewer columns + OK/Changed/Question). After review: code/menu/footer strings → addons/kdvn_website/i18n/vi.po / ja.po (start from an Odoo PO export of kdvn_website so msgids match); page texts → website Translate mode on beta. Then repeat page by page.
Open reviewer questions: 社長 vs 総経理; "Kinden" vs きんでん on JA pages; first president's name in kanji.
2026-10-20 (beta checks, homepage projects, certificates, search & language) — tags up to 261020_search_language
Beta visual check against frames (in-app browser, 1440/1280/390): fixes for h2/h3 using the display font (Inter Tight now), mobile spacing on business pages, inquiry form spacing, Company History (photo 620x320, card padding, 85px timeline rows), General Director Message (new frames gd-message-*; quote/name/role sizes, mobile spacing), mobile page header for all inner pages (title 48px below crumbs, divider inset 16px, wrapped crumbs 20px apart).
Homepage Past Prominent Projects section (kdvn_website_project, homepage_templates.xml): green grid band, editable head + "View all", 4 cards; projects have Show on Homepage (featured first, topped up with newest published).
Hero crash fixed: editor-duplicated slides had no indicators → hero_indicators.js keeps one indicator per slide. Header: .top_menu + o_no_autohide_menu (Odoo auto-hide script error).
Builder behaviour (Odoo 19, verified in source): saving an edited oe_structure stores it as a small website-specific view and COWs the outline view; outline/default content changes in code then stop applying on that website, but t-call data blocks, styles and new inheriting views still apply. homepage.xml note corrected.
Licenses & Certifications page (/company-profile/licenses-certifications): model kdvn.website.certificate (scan, issuer, number, holder, valid from/until, responsible; Website > Site > Content > Licenses & Certificates). Expired = hidden automatically; daily cron gives a "Renew certificate" to-do 60 days before expiry (kdvn_website.certificate_remind_days). Slider (452x640 current / 297x420 others; mobile 240x340) + full-size view. 5 certificates seeded from the frames (HCMC ISO 45001 OHS 725063 expired 9 Sep 2026 → hidden; scans are low-res cuts, replace with originals).
Search & Language panels (frames search-, languages-): header buttons open a 480px glass box (mobile full screen). Search → /website/search (pages, jobs, and now published projects). Language list = installed website languages in native script, design order (vi, ja, en, zh_TW, zh_CN); Chinese not in plan yet (designer question 8e).
Hero slides: designer component shows 5 slides (team building, Nippon Shokken, CMC Creative Space, Panasonic, Kona Village) — full-size photos needed; slides are editor content.
2026-10-19 (Electrical, AC & Sanitary, Inquiry Form) — 19.0.1.15.0
Built from the new frames (electrical-system-*, ac-sanitary-*, inquiry-form-01/02-*). Applied to dev's working tree (not committed yet); also staged in worktree ~/wt_web on feature/kdvn_website.
Business area pages: shared kdvn-bizpage-* layout (intro + wide photo, Feature columns 2–3, numbered Business items with sticky title on desktop). All content in oe_structure (builder-editable). 17 starting photos cut from the frames → Site Media electrical_*, ac_sanitary_*. AC page at /business/air-conditioning-sanitary-system (menus.csv updated, menus.xml regenerated).
Inquiry form (/contactus): custom form (not the Odoo form snippet) → model kdvn.website.inquiry (mail.thread, states New/Handled; menu Website > Inquiries) + kdvn.website.inquiry.type (translatable, Website > Configuration > Inquiry Types). Controller POST /contactus/send: CSRF, honeypot field, server-side checks, mail template mail_template_website_inquiry to Settings > Website > "Inquiry Form" recipients (config param kdvn_website.inquiry_email, fallback company email), redirect ?sent=1 → "Got it!" popup (Interaction inquiry_modal.js). Contact details from company/head office data.
Tests: test_business_pages.py, test_inquiry.py (not run yet). SCSS compile-checked with libsass.
Designer questions added (sections 8b/8c): title case, missing message field, inquiry types, "[X] business days" (built 2), footer breadcrumb, AC layout offsets.
Not done: reCAPTCHA / rate limit on the form; JA/VI translations of the new texts.
2026-10-19 (first demo release)
main fast-forwarded to dev and tagged 261019_first_demo. The tag holds kdvn_website 19.0.1.14.0, kdvn_remote_sync 19.0.1.2.0 and kdvn_website_project 19.0.1.0.0.
Branches:
feature/kdvn_website, feature/kdvn_remote_sync and feature/kdvn_website_project hold the work for each module.
dev merges them and is the branch Thanh runs locally.
main is what the server deploys, from tags.
Server plan: the production DigitalOcean VM runs Odoo 19 under a demo domain. After the BOD approves:
the domain switches to the real one and the old site is stopped;
web.base.url is set and frozen;
robots.txt Disallow is removed;
301 redirects are added from the old site's URLs.
Server setup:
One database with dbfilter and list_db = False, proxy_mode, workers.
Backups of the database and the filestore.
A read-only GitHub deploy key on the VM (not inside the container).
Demo domains: beta.kinden.com.vn (site) and idebeta.kinden.com.vn (web IDE), served by nginx-proxy (VIRTUAL_HOST / VIRTUAL_HOST_MULTIPORTS in the server's docker-compose.override.yml).
At first HTTPS failed because nginx-proxy had no certificate for these names (ssl_reject_handshake on).
Fixed by Thanh's colleague with CERT_NAME: kinden, which makes nginx-proxy use the existing certificate files kinden.crt / kinden.key (presumably a *.kinden.com.vn wildcard).
That certificate is renewed by hand.
The real domain at go-live needs a certificate that covers it, or CERT_NAME again.
IDE exposure: the web IDE on idebeta is reachable from the internet. Use a strong VSCodeWebToken or restrict it by IP.
No CDN for now. DigitalOcean CDN needs Spaces storage, which Odoo Community doesn't support natively. Add Cloudflare later if PageSpeed shows a need.
Past Prominent Projects page built in a new module, kdvn_website_project. See docs/kdvn_website_project.md.
Category menus link to /prominent-projects?category=<slug>.
Figma: the prototype link and the design frames differ slightly. Rule until the designer answers: build from the exported design frames; take only interactions from the prototype. The question is added as section 0 of designer-questions.md (not committed yet, on dev's working tree).
2026-10-18 (homepage: Business Information)
Built (19.0.1.14.0):
Code block kdvn_website.home_business_list (views/components/home_business.xml). Items = sub-items of the Business Information menu (website.menu._kdvn_children_of).
Photo per item from Site Media business_<menus.csv name> (_kdvn_media_key); 7 records share one starting illustration.
Desktop: hover/focus switches the right-hand photo. Mobile: accordion; tap opens an item, tap again or the arrow opens its page. JS static/src/js/home_business.js.
Homepage restructured: #wrap is no longer editable as a whole. It holds editable areas (oe_structure_kdvn_home_hero, _business, _bottom) with the data block outside them, so saving in the builder doesn't freeze the list.
Tests passed (Thanh) before this round; new test test_homepage_business_list. Test command now has --http-port=8079 (DEVELOPMENT.md).
2026-10-18 (homepage: hero slider)
Designer homepage found; frames home-desktop|tablet|mobile.png; spec design/kdvn_website/specs/home.md. Plan: hero slider (builder carousel) → Business Information (list from the Business Information menu + Site Media photo per item; accordion on mobile) → Past Prominent Projects (small project model now, extended in Phase 3).
Hero built (19.0.1.13.0):
Thanh's carousel snippet reworked into kdvn_website.s_kdvn_hero, based on Odoo's carousel classes so the builder can add, remove and reorder slides.
One pair of arrows outside the slides; indicators hidden but kept, because the builder needs them.
Remix icons. Desktop/tablet: 615px text column + photo, 900px high. Mobile: stacked.
homepage.xml rewritten (the old file had two #wrap and placeholder copy).
Test tests/test_homepage.py.
Fix after browser check: Odoo's old carousel CSS made the arrows absolute and hid them on mobile; overridden. Above 1440px the hero text lines up with the header. The header is fixed and see-through (80% white + blur), so content shows through it when scrolling, as designed.
Menu loading fix: parse_menus.py no longer writes is_mega_menu / parent_id on the root menu. Writing them re-ran Odoo 19's _validate_parent_menu on the root and failed with "Menus with child menus cannot be added as a submenu".
Offices list (Website → Site → Content → Offices) now includes the head office (company contact), in bold (19.0.1.12.1).
Designer questions collected in design/kdvn_website/designer-questions.md.
2026-10-18 (head office = company address)
Decision (Thanh): the company address is the head office; other offices are company contacts marked "Website Office". Version 19.0.1.12.0.
res.company._kdvn_website_offices() always returns the company's own contact first; it counts as a main office with no flag. Other offices follow in "Office Order".
Company form → Website Profile → "Head office" group: website name, fax, latitude/longitude, map link. These are related fields stored on the company's contact, so changing the company address updates the website.
Test test_company_address_change_updates_head_office. To do: remove the duplicate "Hanoi Head Office Branch" contact, or untick its "Website Office".
2026-10-18 (three frames per page)
Designer makes 3 frames per page: desktop 1440, tablet 1280 (same layout as desktop so far), mobile 390. Procedure, spec template and project instructions updated; files frames/<page>-desktop|tablet|mobile.png.
Full-size frames for Group Companies and Office Location applied (version 19.0.1.11.0):
All pages, mobile: page title 48/52, breadcrumb 16px (desktop stays 64px / 14px).
Group Companies: lead 28/44 (mobile 24/36); section titles 48px Oswald; creed JP 32px (mobile 28), EN 16px; body text 16px with 32px lines on desktop; photo strip tiles 320×200 (mobile 192×120), 16px gap, bleeding to the right screen edge; profile = grid 575 : 664 with 121px gap, table 50/50 with top line, 24px row padding, 14px desktop / 16px mobile.
Office Location mobile: search → scrolling card list (max 728px) → map 310×400 below.
Confirmed from the mobile frame: founded July 29th, 1997; employees 442 (as of June 2026).
Designer inconsistency to raise: mobile side margin is 24px on Group Companies but 40px on Office Location and the homepage (built with 24px everywhere).
Menus: noupdate="0" during development (module update resets menus to menus.csv); one-time manual delete of "KDVN Menu Root" (Website → Configuration → Menus, developer mode). Switch back to noupdate="1" before go-live.
2026-10-18 (Office Location & Map + map positioning)
Offices entered as contacts by Thanh. Embedded map (no API key) uses Geo Latitude / Longitude (standard contact fields) for an exact pin, else the address; "Map Link" optional. Office Location page from the desktop frame: search + scrolling cards + map; Odoo 19 Interaction static/src/js/office_locator.js.
2026-10-18 (company data)
Decision: marketing text = builder-editable page text; images = Site Media; company facts + offices = Odoo records shown through code-owned blocks.
Offices = company contacts marked "Website Office" (no new model). Company "Website Profile" tab (founding date, capital, employees + as-of). Blocks in views/components/company_info.xml used by the footer, Group Companies profile and Office Location page. Tests tests/test_company_info.py.
2026-10-18 (Group Companies)
Built first from low-res screenshots; 8 Site Media placeholder photos; reusable creed / split / gallery / map / profile classes.
2026-10-16
Browser check OK after fixes; footer built; tests pass; website.menu.overview_url; Site Media; Company History; menu per phase plan; General Director Message; EN / JA / VI.
2026-10-15
DEVELOPMENT.md, project instructions, module review; design sources + procedure in design/kdvn_website/; header + mega menu; shared page header/footer nav with breadcrumb + JSON-LD (also on job pages).
Open
Translations: add JA + VI to the website on beta; reviewers return the Company History sheet; then .po files + Translate mode; then the other pages.
Projects page: browser check with real projects and screenshots; designer questions (mobile category tiles, view buttons on mobile, card click / detail page, tablet card widths).
Designer: which Figma frames are final, and whether the prototype is up to date (section 0 of the questions file); 8b–8e; search results page design; Chinese languages.
Missing frames: tablet and mobile frames for the navigation/header, General Director Message and Company History.
Data to enter: coordinates for each office (head office in the company form); employees as-of date June 2026; company data on beta.
Real photos (Site Media): Group Companies, Business Information, footer building (the original file), Shinsha-san's quote, designer check of the BOD photo; hero full-size photos (5 slides); original certificate scans + renewed HCMC ISO 45001.
Ask designer: mobile side margin 24px or 40px?
Design details: header fill opacity; mobile open-menu design.
Before go-live: menus noupdate="1"; a deployment section in DEVELOPMENT.md (not written yet); certificate for the real domain.
Other review findings: Remix picker JS; the manifest still lists the removed web_editor.assets_media_dialog bundle.
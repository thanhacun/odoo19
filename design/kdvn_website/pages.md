# kdvn_website — build tracker

Source of the site structure: Kinden_Website_Phase_Plan.pdf (slide 1). Languages: **EN / JA / VI from day one**; overview pages launch in Phase 1.
Frame widths: desktop 1440, tablet 1280 (same layout as desktop), mobile 390.
Status: `todo` → `design` (frames + spec ready) → `build` → `review` → `done`.

## Shared parts
| Part | Status | Notes |
|---|---|---|
| Header bar | review | Matches navbar frames; waiting on fill opacity |
| Mega menu | review | Click to open; built from prototype screenshot |
| Mobile menu (open state) | todo | Not designed yet |
| Footer | review | Built from Company History frame; Site Media keys `logo_white` (made from the logo) and `footer_background` (dark placeholder, building photo to upload) |
| Page header (breadcrumb + title + divider) | review | `kdvn_website.page_header`; breadcrumb from the menu + schema.org data; also on /jobs pages |
| Page footer nav (divider + breadcrumb) | review | `kdvn_website.page_footer_nav` |
| Content blocks: intro, year card, section title, stats, timeline, green button | review | From Company History; classes in `theme.scss` (CONTENT BLOCKS) |
| Company data blocks (footer offices, profile table, office map) | review | `views/components/company_info.xml`; data in Settings > Companies > Website Profile + Website > Site > Content > Offices |
| Site Media (replaceable images) | review | `kdvn.website.media` + `/kdvn/media/<key>`; keys: general_director_photo, company_history_intro, logo_white, footer_background, group_companies_hero, management_creed, kinden_vietnam_site, kinden_vietnam_building, kinden_vietnam_gallery_1..4 |

## Pages
| Section | Page | Phase | URL | Status | Notes |
|---|---|---|---|---|---|
| — | Home | 1 | `/` | build | Hero slider + Business Information done; next: Past Prominent Projects (project model). Spec: specs/home.md |
| Company profile | Overview | 1 | `/company-profile` | todo | "View details" target |
| Company profile | General Director Message | 1 | `/company-profile/general-director-message` | review | Quote from Shinsha-san pending; BOD photo in |
| Company profile | Licenses & Certifications | 1 | | todo | |
| Company profile | Company History | 1 | `/company-profile/company-history` | review | Built; content questions answered |
| Company profile | Kinden Business Areas | 3 | | todo | |
| Company profile | Group Companies | 3 | `/company-profile/group-companies` | review | Aligned to full-size desktop/tablet/mobile PNG frames; photos = placeholders |
| Company profile | HR Development | 4 | | todo | |
| Business Information | Overview | 1 | `/business-information` | todo | |
| Business Information | Electrical Systems | 1 | `/business/electrical-system` | review | Built from frames (desktop/tablet/mobile); shared `kdvn-bizpage-*` layout, images in Site Media `electrical_*` |
| Business Information | Air Conditioning & Sanitary Systems | 1 | `/business/air-conditioning-sanitary-system` | review | Same layout as Electrical; images in Site Media `ac_sanitary_*` |
| Business Information | Instrumentation Systems | 2 | | todo | Probably same layout as Electrical |
| Business Information | Information & Communication Systems | 2 | | todo | |
| Business Information | Interior Systems | 2 | | todo | |
| Business Information | Energy Saving & Renewal | 2 | | todo | |
| Business Information | Maintenance Services | 2 | | todo | |
| Past Prominent Projects | Projects Overview | 1 | `/prominent-projects` | build | Module kdvn_website_project; spec specs/prominent-projects.md |
| Past Prominent Projects | Factories / Data Center / Buildings / Logistics / Educational / Hotels | 3 | `/prominent-projects?category=…` | build | Same page filtered by category |
| Recruitment | Why Join Kinden Vietnam | 4 | | todo | |
| Recruitment | Open Positions | 4 | `/jobs` | build | KDVN page header on list, detail, apply |
| Recruitment | LinkedIn Homepage | 4 | external | todo | Need URL |
| Contact Us | Overview | 1 | `/contact-us` | todo | |
| Contact Us | Office Locations & Map | 1 | `/contact-us/office-locations` | review | Desktop/tablet/mobile frames applied (mobile: search, scrolling list, map below) |
| Contact Us | Inquiry Form | 1 | `/contactus` | review | Custom form → `kdvn.website.inquiry` (Website > Inquiries), email to Settings > Website > Inquiry Form; "Got it!" popup on `?sent=1` |

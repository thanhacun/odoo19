# Questions for the designer — kdvn_website

Updated 2026-10-18. Tick each item when answered and copy the answer into the matching spec in `specs/`.
For every page, please send 3 frames: **desktop 1440, tablet 1280, mobile 390** (PNG, 2x).

## 0. Which design is final? (most important)
- [ ] The prototype link and the design frames differ slightly. Which frames are final? Please mark them in Figma (e.g. a section "Final / Ready for development" or a status per frame).
- [ ] Is the prototype kept up to date? If not, should we take only the interactions from it (clicks, hover, page links, animations), or nothing?
- [ ] Where prototype and design differ, which differences are intentional?
(Until answered: we build from the exported design frames.)

## 1. Missing frames
- [ ] **Header / navigation**: tablet (1280) and mobile (390) frames.
- [ ] **Mobile menu, open state**: what it looks like when the hamburger is tapped (layout, background, how sub-menus open, where the action buttons go).
- [ ] **General Director Message**: tablet and mobile frames. The page was "President Message" in Figma; please rename it and put it under Company profile.
- [ ] **Company History**: tablet and full-size mobile frames (we only have a small screenshot of the mobile version).
- [ ] **Phase 1 pages not designed yet** (or not found in Figma):
  - Overview pages: Company profile, Business Information, Contact Us.
  - Licenses & Certifications.
  - Electrical Systems; Air Conditioning & Sanitary Systems.
  - Projects Overview (Past Prominent Projects).
  - Inquiry Form (contact form).

## 2. Header
- [ ] **Fill opacity** of the glass header. Background blur is 80; we built a white fill at 80% opacity. Is that right?
- [ ] **Desktop padding**: 40px on the left and 20px on the right. Is the difference intended?
- [ ] **Menu hover**: there are two variants in Figma, bold black with no underline, or with a thin green underline. Which one does the header use? (We built: hover = thin green underline, click = open dropdown.)
- [ ] Any **animation** for opening the dropdown or mega menu (fade, slide, duration)? None found in the prototype.

## 3. Layout consistency
- [ ] **Mobile side margin**: 24px on Group Companies but 40px on Office Location & Map. Which is correct for all pages? (Built with 24px everywhere.)
- [ ] **Tablet 1280**: confirm it always uses the desktop layout, only narrower.

## 4. Footer and naming
- [ ] Footer link **"Office Network"** and menu item **"Office Locations & Map"**: are they the same page? If yes, which name should both use?
- [ ] **Footer background**: which building photo should we use? Please send it full size.

## 5. Photos and images
- [ ] **General Director Message**: is the BOD group photo OK in this layout (crop, position)?
- [ ] **Group Companies**: real photos for the hero, the Management Creed, the Kinden Vietnam site and building, and the 4-photo gallery.
- [ ] **Company History** intro photo is a placeholder. Send the final image, or confirm the current one.
- [ ] **White logo** for the dark footer: we made one from the colour logo. Is there an official white version?

## 6. Languages (EN / JA / VI from day one)
- [ ] **Fonts for Japanese and Vietnamese**: Oswald (headings and figures) has no Japanese glyphs. Which font should Japanese text use?
- [ ] Japanese and Vietnamese titles are often longer or shorter than English. Any rules for long titles, e.g. in the menu, mega menu and page titles?
- [ ] **Language switcher**: where does it go in the header, and what does it look like (desktop and mobile)?

## 7. Homepage
- [ ] Hero slider: how many slides, auto-play (and speed), and where does "View detail" go on each slide?
- [ ] Hero title wording: "Heart to be the connected in the future" (check with management).
- [ ] Business Information list: does the photo change on hover or on click? (Mobile frame: accordion, photo under the active item.)
- [ ] "Business Information" title: mixed case on desktop, uppercase on tablet and mobile. Which one? (Built uppercase, like the inner pages.)
- [ ] Project cards: hover effect? The projects tagline repeats the Business Information one: final text?
- [ ] Mobile hero side margin: 40px left / 24px right in the frame (built with 24px, see section 3).

## 8. Past Prominent Projects
- [ ] Mobile list frame shows category photo tiles (Buildings, Factories, Educational, Logistics, Hotels, Data Center) that the desktop frames don't have. Where do they belong (overview page only? all screen sizes?) and which photos?
- [ ] Mobile frames have no grid/list buttons: hide them on mobile? (Built: shown.)
- [ ] What happens when a card is clicked? No project detail page is designed.
- [ ] Tablet frame: card widths differ from card to card: intended?

## 8b. Business area pages (Electrical, AC & Sanitary)
- [ ] Page title: mobile frame shows "Electrical system" (mixed case), desktop "ELECTRICAL SYSTEM". Built uppercase on all sizes like the other inner pages. Title text comes from the menu ("Electrical Systems", "Air Conditioning & Sanitary Systems"): rename the menu items if the singular is wanted.
- [ ] No breadcrumb at the bottom of these frames (other inner pages have it). Built with it, for consistency.
- [ ] AC & Sanitary desktop frame: "Business items" title at x=80 and right column ending at 1360 (Electrical: 40 / 1400). Built the same as Electrical.
- [ ] Section titles "Feature" / "Business items" are mixed case, other pages use uppercase (MANAGEMENT CREED). Built as in the frames (mixed case).
- [ ] Other business areas (Instrumentation, ICT, Interior, Energy saving, Maintenance): same layout? Text and photos needed.

## 8c. Inquiry form
- [ ] The form has no message field. Built with a required "Message" box under "Inquiry type": OK?
- [ ] "Inquiry type" options? Started with: Request for quotation, Project consultation, Maintenance and services, Partnership and suppliers, Other (editable in Website > Configuration > Inquiry Types).
- [ ] Popup text "respond within [X] business days": built with **2** business days. Correct number?
- [ ] Placeholder of Inquiry type in the frame is "Ex: Capital Crest Vietnam" (copied from Company name). Built "Select an inquiry type".

## 8d. Licenses & Certifications
- [ ] Clicking a certificate opens it full size (popup frame). The popup frame has no close button: built with a small X (plus click outside / Escape). OK?
- [ ] Mobile: all certificates the same size (240 x 340), as in the frame; no "large current one" on mobile. OK?
- [ ] Text above the slider (intro, list of licenses)? The frames have none; an editable area is there if needed.

## 8e. Search and Language panels
- [ ] Language list has 5 languages (Tiếng Việt, 日本語, English, 繁體, 简体). Plan so far: EN / JA / VI. Are Traditional and Simplified Chinese wanted? (The list shows whatever languages are installed on the website.)
- [ ] Search: is there a design for the results page? Built with Odoo's search results page (pages, projects, jobs) in our layout.
- [ ] Search box sits higher than the Language box in the frames (top 320 vs centred). Built both centred.

## 9. Small corrections already made (for the designer's information)
- Company History: Vina-Kinden joint venture year is **1997** (Figma says 1944); locations = **7**.
- Company History timeline: spacing between events made even (16px); the gaps in Figma were uneven.

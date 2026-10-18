# kdvn_website — design sources

Design inputs and one-off generator scripts for `addons/kdvn_website`.
Nothing here is loaded by Odoo.

| Folder | Contents |
|---|---|
| `tokens/` | `tokens.json` (Figma variables export) and `compile_tokens.py` |
| `menus/` | `menus.csv`, `unlink_menus.csv` and `parse_menus.py` |
| `specs/` | Component specs (`sample.md` is the template, one file per component) |
| `frames/` | PNG exports of Figma frames, e.g. `header-desktop.png`, `header-mobile.png` |

## Tokens (one-off)

Only rerun if the designer changes the Figma variables:

```bash
python3 design/kdvn_website/tokens/compile_tokens.py
```

It completely rewrites `addons/kdvn_website/static/src/scss/primary_variables.scss`
and `theme_utilities.scss`. Move any hand-written CSS out of `theme_utilities.scss`
into `theme.scss` first.

## Menus

```bash
python3 design/kdvn_website/menus/parse_menus.py
```

Regenerates `addons/kdvn_website/data/menus.xml`. During development the records
are `noupdate="0"`: each module update resets the menus to the CSV. Switch to
`noupdate="1"` in `parse_menus.py` before go-live.

## Working procedure (one page or component per round)

Tracker: `pages.md`. Spec template: `specs/_page_template.md`.

> **Sharing frames:** save the 2x PNG exports straight into `frames/` in this
> folder (e.g. `frames/group-companies-desktop.png`) and tell Claude the file
> names. Images pasted into the chat get shrunk, so small text and photos
> become unreadable; files in the folder are read at full size.

1. **Pick** the next item in `pages.md`. Build shared parts first, and build one page per layout before its look-alikes.
2. **Thanh — export**: every page has three frames in Figma (desktop, tablet,
   mobile). Select each frame, Export → PNG 2x, save as
   `frames/<page>-desktop.png`, `frames/<page>-tablet.png` and
   `frames/<page>-mobile.png`. For anything
   interactive, open Present (▶), put it in each state and screenshot it
   (`frames/<page>-<state>.png`).
3. **Thanh — spec**: copy `specs/_page_template.md` to `specs/<page>.md`; fill in
   sections, content status, links, behaviour. Rough notes are fine.
4. **Claude — plan**: reads frames + spec, measures sizes from the PNGs, lists
   what reuses existing parts vs. what is new, asks only the open questions.
   Thanh confirms.
5. **Claude — build**: template in `views/pages/`, shared pieces as reusable
   QWeb blocks, styles in `scss` using tokens only, `is_published`, menu URL in
   `menus/menus.csv`.
6. **Thanh — check**: `-u kdvn_website`, open with `?debug=assets`, screenshot
   desktop and mobile (and states) and send them.
7. **Claude — compare & fix**: lists differences against the frames, fixes;
   max two rounds, then remaining items go to the spec as follow-ups.
8. **Close**: `pages.md` status → done, decisions written into the spec, commit
   on the feature branch (Claude asks first).

Images: every page image is a **Site Media** record (Website → Site → Content →
Site Media) with a fixed key, added in `data/website_media.xml` and used in
templates as `<img src="/kdvn/media/<key>"/>` (optional `?width=800`). To change
an image, upload a new one on that record; no page edit needed. Captions are
page text (translatable), never baked into the image.

Rules: one change at a time · Figma frames are the source, the prototype (▶)
shows interactions · tokens instead of literal values · menus don't change on
module upgrade only while `noupdate="0"` (development).

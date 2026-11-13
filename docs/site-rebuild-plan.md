# Plan: replace the Squarespace site at nptedebate.com with a custom static site

Status: plan only, nothing built. Written 2026-11-13 from a full crawl of
https://www.nptedebate.com/ and a read of this repo. This document is the
brief for the agent that does the build. Read `CLAUDE.md` first; its rules
(never `Read` the whole rankings file, never force-push, alias conventions)
all still apply.

## 1. Goal

Serve `www.nptedebate.com` from this repo via GitHub Pages, with every page
the Squarespace site has today plus the rankings and Head-to-Head pages as
native pages of the same site, then cancel the Squarespace site plan.

Done means:

- Every current URL (`/`, `/about`, `/rankings`, `/tournament-invite`,
  `/npte2026info`, `/home`) resolves on the new site with equivalent or
  better content.
- Rankings and Head-to-Head are first-class pages under the shared site
  header, not an iframe.
- The data-ingest workflow in `CLAUDE.md` still works, with paths updated.
- The owner has a short DNS cutover runbook (section 8) and has not had to
  touch anything else.

## 2. What exists today

### 2.1 Squarespace site (5 pages, no backend features in use)

Squarespace 7.1. No blog, events, store, forms, newsletter, member area,
search, analytics, custom code, or hosted file downloads. Footer is empty.
Nothing functional is lost by going static.

Nav (logo left, links right, hamburger on mobile): Rankings, Tournament
Invite, NPTE 2026 Tournament Info, About. Home is reached via the logo.

| URL | Content |
|---|---|
| `/` (also `/home`) | Hero photo with H1 "National Parliamentary Tournament of Excellence" and button "See Rankings" → `/rankings`. Second section: photo, heading "Our Purpose", the mission paragraph, button "See Invite" → `/tournament-invite`. |
| `/rankings` | Heading "NPTE Rankings", a hand-edited line "Tournaments Recorded: GGO, Rice, Steve Hunt, Crossman" (stale), and an iframe of `https://paulicydebate.github.io/NPTE-Rankings/` at 900px height. |
| `/tournament-invite` | Photo `mercer.jpg`, "March 6 - 8, 2026", "Mercer University / Macon, Georgia", and an embedded Google Doc (id `1BXAt_BWWTTayRaiHudQw3j-dktZhuCBp5c5bbotiF8s`) wrapped in Embedly. The invite text lives only in that doc. The event is already past. |
| `/npte2026info` | Four sections: "Groups" (a screenshot of a table), "Debate Patterns" (a screenshot of a table), "Topics" (5 resolutions as a numbered list) with a link "Audit Spreadsheet", and a link "NPTE Points Table". Data transcribed in section 2.3. |
| `/about` | "Our Mission" (the mission paragraph) and "Our History": 21 subsections, 1999–2000 through 2020, about 4,000 words. Nothing after 2020. |

Mission paragraph (used on Home and About): "The purpose of the National
Parliamentary Tournament of Excellence is to provide an opportunity for the
finest parliamentary debate teams from a variety of schools to participate
in an annual championship parliamentary debate tournament."

Off-site resources the pages link to or embed, which must keep working:

- Invite Google Doc: `https://docs.google.com/document/d/1BXAt_BWWTTayRaiHudQw3j-dktZhuCBp5c5bbotiF8s/preview?embedded=true` (direct embed URL, no Embedly)
- Audit Spreadsheet: `https://docs.google.com/spreadsheets/d/16IbEIQ7sTme2MYM_T6-TaXisebRUR1_45mby_nMSdaY/edit?usp=sharing`
- NPTE Points Table: `https://docs.google.com/spreadsheets/d/1btjWB9cbKmBsWQcBTOtHd7-SUofU5Pp8A8DmcpFaLOI/edit?usp=sharing`

Images, all under
`https://images.squarespace-cdn.com/content/v1/679d2435c0cadc24e9bccc0c/`
(omit the query string for the original):

1. `685650ec-4dd2-4467-9231-a5cf06451f2e/Untitled+design+%285%29.png` — logo, 500x500 transparent PNG, black circular badge
2. `47bf76dd-1924-41b5-a74a-a62facb09271/unsplash-image-YRMWVcdyhmI.jpg` — home hero (Unsplash stock, lecture hall)
3. `1738650416793-WU3D7F599RH3G4XPXDQ0/unsplash-image-ID1yWa1Wpx0.jpg` — home "Our Purpose" (Unsplash stock, auditorium)
4. `460a5a8b-91dc-4ea6-b09b-2273aa107c8b/mercer.jpg` — 800x533
5. `9ccea685-8d57-4134-99ff-bb960a9b68d7/npte+groups+2026.png` — do not reuse, rebuild as a table
6. `aa7ee677-7dca-4c51-afb9-41eac04f087f/correct+npte+matrix.png` — do not reuse, rebuild as a table

Design tokens:

- Colors: text `#36302A`, off-white `#F6F3EC`, page background `#ECE4DA`,
  accent `#B9A590`, dark accent `#574C3F`.
- Fonts: headings Libre Baskerville 400 (tight tracking, about 66px H1 on
  desktop); body, nav and buttons Almarai 400 at 16px/1.5.
- Buttons: solid `#36302A`, text `#F6F3EC`, radius 15px.
- Layout: max width 1400px, 4vw side padding, transparent header over the
  home hero, header not sticky.
- No favicon is set. No meta descriptions. Alt text is missing on all
  content images. Heading levels are wrong on every page (two H1s on Home,
  none elsewhere).
- Title pattern: `<Page> — National Parliamentary Tournament of Excellence`.
- `nptedebate.com` 301s to `www.nptedebate.com`.

### 2.2 This repo (already live on GitHub Pages)

- `index.html` — the rankings app, about 695 KB, one file, Tailwind CDN,
  vanilla JS, data in `tournamentLogs`. Served today at
  `https://paulicydebate.github.io/NPTE-Rankings/`.
- `h2h.html` + `assets/h2h.{js,css}` + `data/h2h.json` — Head-to-Head.
- Both share a dark-mode preference in `localStorage['npte-theme']`.
- `tools/h2h/common.py`, `tools/h2h/site_extract.js` (takes the path as an
  argument) and `tools/site_data_fixes_2026_11.py` read `index.html` by
  path. `CLAUDE.md`, `tools/h2h/README.md` and `tools/h2h/readme.py`
  document that path.
- The owner sometimes uploads the rankings file through GitHub's web UI.

### 2.3 Content transcribed from the two screenshot images

Group stage, 2026 (seed in parentheses):

| Group A | Group B | Group C | Group D |
|---|---|---|---|
| DVC LP (4) | Rice SS (2) | PDAB BC (1) | PDAB PZ (3) |
| Pacific CP (7) | PDAB CG (6) | UTT HS (5) | Pacific AB (8) |
| Rice DW (11) | William Jewell DT (12) | Rice JT (10) | Rice GJ (9) |
| PDAB LS (13) | Mercer KO (15) | Whitman HK (14) | Mercer BM (16) |
| UTT CS (17) | Pacific GG (19) | Mercer DN (20) | McKendree BC (18) |

Debate patterns:

| | Round 1 | Round 2 | Round 3 | Round 4 | Round 5 |
|---|---|---|---|---|---|
| Team 1 | debates 5 | debates 4 | debates 3 | debates 2 | bye |
| Team 2 | debates 4 | bye | debates 5 | debates 1 | debates 3 |
| Team 3 | bye | debates 5 | debates 1 | debates 4 | debates 2 |
| Team 4 | debates 2 | debates 1 | bye | debates 3 | debates 5 |
| Team 5 | debates 1 | debates 3 | debates 2 | bye | debates 4 |

These were transcribed by a model from screenshots. Check both tables
against the original images before publishing.

2026 topics:

1. The United States federal government should significantly increase its democracy assistance to non-state actors in Iran.
2. The United States federal government should substantially increase its military assistance to the Republic of Kazakhstan, the Kyrgyz Republic, or the Republic of Tajikistan.
3. The United States federal government should significantly increase its economic support for the Republic of Yemen.
4. The United States federal government should adopt a policy to significantly increase supply chain transparency for both cocoa imports and cacao imports into the United States.
5. The United States federal government should substantially increase its domestic environmental conservation efforts in the Arctic.

## 3. Decisions already made (do not reopen without the owner)

1. **Hosting: GitHub Pages from this repo's `main`, custom domain
   `www.nptedebate.com`.** It already hosts the rankings, costs nothing,
   and keeps the owner's "upload a file in the GitHub web UI" habit working.
2. **No build step.** Hand-written HTML pages, one shared stylesheet, one
   small shared script. Seven pages do not justify a generator, and a build
   step would break the web-UI upload habit. The header and footer markup
   is duplicated per page; a check script (phase 5) keeps the copies
   identical.
3. **Flat files, relative links only.** GitHub Pages serves `about.html` at
   `/about`, so the current slugs are preserved with no redirects. Every
   `href`/`src` must be relative (`about`, `assets/site.css`), never
   root-absolute (`/about`), so the site works both at
   `paulicydebate.github.io/NPTE-Rankings/` before cutover and at the
   domain root after.
4. **The rankings app moves from `index.html` to `rankings.html`.** The
   domain root has to be the home page. The app itself is not rewritten.
5. **Visual direction: keep the current identity** (palette, two fonts,
   logo) for the content pages, and bring the site header onto the rankings
   pages. Do not restyle the rankings tables.
6. **Self-host the fonts** as woff2 in `assets/fonts/`. Get them from the
   npm packages `@fontsource/libre-baskerville` and `@fontsource/almarai`
   (the package registry is reachable; Google's font hosts are not).
7. **No analytics, no forms, no CMS** unless the owner asks. None exist
   today.

## 4. Target site

| File | URL | Notes |
|---|---|---|
| `index.html` | `/` | New home page |
| `rankings.html` | `/rankings` | The existing app, renamed, with the site header added |
| `h2h.html` | `/h2h` | Existing, with the site header replacing its two-button nav |
| `tournament-invite.html` | `/tournament-invite` | Current season's invite |
| `npte2026info.html` | `/npte2026info` | 2026 info, kept at its URL as an archive page |
| `about.html` | `/about` | Mission and history |
| `home.html` | `/home` | Stub: canonical + meta refresh to `./` |
| `404.html` | — | Site-styled, links to Home and Rankings |
| `assets/site.css`, `assets/site.js` | — | Shared tokens, header, footer, theme toggle |
| `assets/img/`, `assets/fonts/` | — | Migrated images, favicon set, fonts |
| `CNAME`, `sitemap.xml`, `robots.txt`, `.nojekyll` | — | `CNAME` is added only at cutover (phase 6) |

Nav: Rankings, Head-to-Head, Tournament Invite, Tournament Info, About.
"Tournament Info" points at the newest `npteYYYYinfo` page.

Improvements over the Squarespace site, in scope:

- Rankings and Head-to-Head render natively at full page height, with real
  URLs and working mobile layout, instead of a fixed 900px iframe.
- The stale hand-typed "Tournaments Recorded" line is dropped; the rankings
  app already lists tournaments from the data.
- Home shows the current season's top 5 teams, computed in the browser from
  the same data the rankings page uses. See phase 3 for how to do this
  without loading the 695 KB file on the home page.
- Groups and Debate Patterns become real HTML tables (readable on phones
  and by screen readers).
- About gets a year index (jump links) and a champions table built from the
  history text; each year becomes an `id`-anchored section.
- One H1 per page, correct heading order, alt text on every image, a meta
  description and Open Graph tags per page, a favicon generated from the
  logo, `sitemap.xml`.
- Dark mode on every page, using the existing `npte-theme` key so the
  choice carries between content pages and rankings.
- A footer with the mission line and links to the Points Table and Audit
  Spreadsheet.
- Images resized and compressed; the hero served at sensible widths with
  `srcset`. No third-party scripts on content pages.

Out of scope unless the owner asks: rewriting the rankings app, replacing
Tailwind CDN, splitting `tournamentLogs` into its own file beyond what
phase 3 needs, a blog or news feed, a contact form.

## 5. Constraints and traps

- **Merging to `main` changes what the live Squarespace page shows.** The
  Squarespace `/rankings` page iframes the GitHub Pages root. The moment a
  new `index.html` lands on `main`, that iframe shows the new home page.
  So the merge to `main` is part of cutover, not a preview step. Preview
  locally instead.
- **Data ingests keep landing in `index.html` on `main` while this is
  built.** Do the rename (`git mv index.html rankings.html`) and the header
  insertion as the last commits before merge, as small scripted edits, so
  a rebase onto fresh `main` is trivial. Never hand-merge the data line.
- **The rankings file is too large to read.** Insert the header with
  `grep -n` and targeted edits near the top of `<body>`; check the result
  in a browser.
- **Old links.** Once the custom domain is set, GitHub redirects
  `paulicydebate.github.io/NPTE-Rankings/...` to the domain. The old root
  link lands on Home, which has a prominent Rankings button; `h2h.html`
  links keep working because the file name is unchanged.
- **Capture content before anything is cancelled.** The About text and the
  images exist only on Squarespace. Phase 1 copies them into the repo.
- **Network.** The cloud environment `npte-rankings` allows
  `www.nptedebate.com`, `nptedebate.com`, `images.squarespace-cdn.com` and
  `static1.squarespace.com`. Run the build session in that environment.
  `docs.google.com` is not allowed there, so the invite doc cannot be read
  from the sandbox.
- Tailwind's CDN is blocked in the sandbox; ignore that one console error
  when testing the rankings page, as `CLAUDE.md` says.

## 6. Build phases

Work on a feature branch. Commit per phase. Do not open a pull request or
push to `main` unless the owner says so.

### Phase 1 — Capture

- Fetch the five pages' HTML and save the About history verbatim (decode
  entities such as `&amp;`), preserving every heading and paragraph.
- Download images 1–4 into `assets/img/` with clean names (`logo.png`,
  `hero.jpg`, `purpose.jpg`, `mercer.jpg`). Download 5 and 6 to a scratch
  directory only, to verify the tables in section 2.3.
- Produce the favicon set (`favicon.ico`, 32px and 180px PNG, an SVG if the
  logo traces cleanly) and a 1200x630 Open Graph image from the logo on the
  page background color.
- Install the two font packages in a scratch directory and copy only the
  latin woff2 files needed (Libre Baskerville 400 and 400 italic, Almarai
  400 and 700).

### Phase 2 — Shared shell

- `assets/site.css`: the tokens from section 2.1 as custom properties, a
  dark palette under `html.dark` (match how the rankings app toggles its
  theme; check with `grep -n "npte-theme" index.html`), type scale,
  buttons, tables, header, footer, skip link, focus styles.
- `assets/site.js`: mobile menu toggle, theme toggle reading and writing
  `npte-theme`, marking the current nav link. Set the theme class from an
  inline snippet in `<head>` to avoid a flash.
- The header and footer markup, written once and pasted identically into
  every page between `<!-- site-header -->` / `<!-- /site-header -->` and
  `<!-- site-footer -->` / `<!-- /site-footer -->` markers.

### Phase 3 — Content pages

- `index.html` (home): hero, purpose section, a "current standings" top-5
  block, and a next-tournament strip driven by a small object at the top of
  the page that the owner can edit (name, dates, host, city). If no next
  tournament is set, the strip hides.
  - For the top 5: add a script to `tools/` that reads the rankings file
    with the existing `tools/h2h/site_extract.js` approach and writes
    `data/home.json` (season label, top 5 teams with points and record,
    tournament count, last tournament name). Home fetches that file. Add
    "regenerate `data/home.json`" to the ingest steps in `CLAUDE.md`. Reuse
    the app's own season-ranking logic by evaluating it in Node or by
    driving the page with Playwright; do not reimplement the ranking rules
    by hand, and assert the result equals what the rankings page displays.
- `about.html`: mission, year index, history sections, champions table
  (year, host, champion, runner-up, decision) extracted from the history
  text. Where a year's text does not state a field, leave the cell empty.
  Do not invent 2021–2026 entries; add a visible "2021 onward: to be added"
  note only if the owner approves that wording, otherwise end at 2020 as
  the current page does.
- `tournament-invite.html`: heading, dates, host, photo, the Google Doc
  embedded directly (URL in section 2.1) in a responsive frame with a
  visible "Open the invite in Google Docs" link below it. Label it as the
  2026 invite until the owner supplies 2027 details.
- `npte2026info.html`: the two tables, the topics, the two spreadsheet
  links, under an H1 "NPTE 2026 Tournament Info".
- `home.html` stub and `404.html`.

### Phase 4 — Rankings integration (last before merge)

- Rebase onto the latest `origin/main`.
- `git mv index.html rankings.html`; place the new home page at
  `index.html`.
- Insert the site header into `rankings.html` and `h2h.html`, load
  `assets/site.css` scoped so it does not restyle the app (prefix header
  and footer rules with a `.site-` class; do not put element selectors in
  the part the rankings page loads). Remove the app's now-duplicate
  Head-to-Head button and theme button only if the shared header covers
  them; keep one working theme toggle.
- Update the path in `tools/h2h/common.py` and
  `tools/site_data_fixes_2026_11.py`, the docs in `tools/h2h/README.md` and
  `tools/h2h/readme.py`, and rewrite the affected parts of `CLAUDE.md`
  (file layout, the md5 divergence check, the ingest steps, the note that
  the owner now uploads `rankings.html`).
- Run `python3 tools/h2h/build.py` far enough to confirm it still finds the
  data (see its README for inputs), without committing regenerated output
  unless it differs for a real reason.

### Phase 5 — Checks

Add `tools/check_site.py` (stdlib only) and run it:

- The header and footer blocks are byte-identical across all pages.
- No `href` or `src` starts with `/`; every relative link resolves to a
  file in the repo; external links are listed for manual review.
- Each page has exactly one `<h1>`, a `<title>`, a meta description, a
  canonical pointing at `https://www.nptedebate.com/<slug>`, and every
  `<img>` has `alt`.
- `sitemap.xml` lists exactly the public pages.

Then with `python3 -m http.server` and Playwright
(`/opt/pw-browsers/chromium`):

- Serve the repo twice: at the server root, and from a parent directory so
  it sits under `/NPTE-Rankings/`. All pages and assets load in both.
- Screenshot every page at 390px and 1440px wide, light and dark. Look at
  them. Compare Home, About and the info page against the live Squarespace
  pages for missing content.
- Rankings: the table renders, a view-mode switch works, a team modal
  opens, the Tournaments view shows the same champion for the latest
  tournament as before the change, the points calculator opens.
- Head-to-Head: a search returns matchups; a `?`-parameter link still
  works.
- The theme choice made on Home is still set on Rankings and Head-to-Head.
- Keyboard: skip link, menu toggle and nav are reachable and visibly
  focused.

Report results honestly, including anything that could not be checked in
the sandbox (the Google Doc embed, Tailwind styling).

### Phase 6 — Cutover (only when the owner says go)

1. Rebase on `main` once more, re-run phase 5, merge to `main` using the
   worktree procedure in `CLAUDE.md`.
2. Confirm `https://paulicydebate.github.io/NPTE-Rankings/` shows the new
   home page and `/rankings` shows the app. From this moment the
   Squarespace `/rankings` iframe shows the new home page, so move straight
   to step 3; if DNS has to wait, ask the owner to change the iframe `src`
   on Squarespace to `.../NPTE-Rankings/rankings.html`.
3. Add `CNAME` containing `www.nptedebate.com` and hand the owner the
   runbook in section 8.
4. After DNS resolves and HTTPS is issued, check every URL in section 2.1
   on the real domain, plus `http://`, the bare domain, `/home`, and an old
   `paulicydebate.github.io/NPTE-Rankings/h2h.html` link.

## 7. Questions for the owner

None of these block phases 1–5; the defaults are what the build uses if
there is no answer.

| Question | Default |
|---|---|
| Are there unlinked pages in Squarespace (Pages panel, "Not Linked")? The crawl only saw the sitemap and nav. | Assume none. |
| Does anyone receive email at an `@nptedebate.com` address? If so the MX records must be kept at cutover. | Keep every existing non-web DNS record untouched. |
| Where is the domain registered and where is its DNS managed? | Assume Squarespace Domains for both. It is not in the connected Cloudflare account. |
| 2027 tournament: dates, host, invite doc? | Show the 2026 invite, labelled as 2026. |
| History for 2021–2026: will you supply text? | Leave the history ending at 2020. |
| Do you want visitor stats? | None. Cloudflare Web Analytics is the suggested option if wanted. |
| Are the two stock photos fine to keep, or do you have real NPTE photos? | Keep the stock photos. |

## 8. Owner runbook for cutover

Only the owner can do these; they need the domain and GitHub logins.

1. GitHub → account Settings → Pages → add and verify the domain
   `nptedebate.com` (a TXT record; this stops anyone else claiming it).
2. Repo Settings → Pages → Custom domain: `www.nptedebate.com`.
3. In the domain's DNS settings, replace the Squarespace web records, and
   only those:
   - `www` CNAME → `paulicydebate.github.io`
   - apex `A` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
     `185.199.111.153`
   - Confirm these values against GitHub's "Managing a custom domain for
     your GitHub Pages site" page before entering them.
   - Leave MX, TXT and any other records alone.
4. Wait for the Pages settings screen to show the DNS check passing, then
   tick "Enforce HTTPS". Certificate issuance can take up to a day.
5. Check the site on a phone and a laptop.
6. Only then cancel the Squarespace **website** subscription. The domain
   registration is billed separately; keep it (or transfer it to another
   registrar first). Confirm in Squarespace billing that cancelling the
   site does not cancel the domain. Squarespace's built-in traffic stats
   stop at this point.

Rollback before step 6: restore the previous DNS records and the
Squarespace site is live again.

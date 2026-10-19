# NPTE Rankings — Project Notes

A single-file static site (`index.html`) tracking NPDA/NPTE parliamentary
debate results, hosted via GitHub Pages from `main`. Tailwind CDN, vanilla
JS, no build step. All data lives in one JS array (`tournamentLogs`) inside
`index.html`; everything else (leaderboards, modals, trophies, the points
calculator) is computed from it client-side.

## Git workflow — read this before pushing anything

- Develop on `claude/data-merge-error-analysis-5n44pp`. Push to `main`
  only when the user explicitly says so ("push", "push to main").
- `main` periodically diverges because the user sometimes uploads
  `index.html` directly via GitHub's web UI. **Never force-push.** Before
  pushing to `main`, always check for divergence first:
  ```
  git fetch origin main
  git show origin/main:index.html | md5sum
  git show origin/<feature-branch>~N:index.html | md5sum   # last common ancestor
  ```
  If they match, it's safe. To push: `git worktree add <tmp> origin/main`,
  copy the updated files in from the feature branch
  (`git show origin/<branch>:<file> > <tmp>/<file>`), commit, `git push
  origin HEAD:main` from the worktree, then `git worktree remove --force
  <tmp>`. This updates `main` without rewriting history.
- `index.html` is huge (the `tournamentLogs` line alone is 400K+ tokens).
  Never `Read` the whole file — use `grep -n`/`sed -n` for structure, and
  Python regex (`re.search(r'const tournamentLogs = (\[.*?\]);\s*\n\s*let
  summaryData'...)`) to load/write just the data array.

## Data ingest workflow

The user maintains a master Google Sheets ingest workbook (~85+ tabs, one
per tournament, "Data Entry Template" layout: header row 4, data from row
5). Each new tournament's results go through this pipeline:

1. **Scrape or receive data** for a new tournament (PDF/JSON scrapers in
   `scrapers/`, or the user hand-fills an ingest tab themselves).
2. **Hand the user an ingest-tab `.xlsx`** (copy `Data Entry Template`'s
   structure: row 2 col F = `(Tournament Name)` placeholder, row 3 cols
   K–Q = weights `[1.0,1.2,1.4,1.6,1.8,2.0,2.2]`, row 4 = headers, data
   from row 5, include the `Points Earned` MROUND formula in col R) so
   they can review/correct it before anything touches the live site.
3. **When they send back the updated full workbook**, diff its tab list
   against what's already live (`tournamentLogs`' distinct `Tournament`
   values) to confirm it only adds what was asked — do **not** blindly
   run a full-workbook sync; it can pull in other unreviewed tournaments
   (this happened once). Also check for a pasted-but-unrenamed tab
   (`Copy of Data Entry Template`) if the expected tab name is missing.
4. **Check every school/debater name in the new tab against the current
   season's and the prior season's existing data** (fuzzy match via
   `difflib`, resolving through `SCHOOL_ALIASES`/`NAME_ALIASES` first) for
   spelling splits before merging — this has repeatedly caught real
   duplicate-name issues (e.g. "Elisandra Moulitsas" vs "...-Batista",
   "Nico" vs "Nicolas Brenneman-Ochoa"). Add any new aliases to
   `SCHOOL_ALIASES`/`NAME_ALIASES` in `index.html`.
5. **Merge into `tournamentLogs`**: compute `Points Earned` with the same
   formula `scrapers/sync_ingest.py` uses (`compute_points`/`mround`,
   Decimal-based `ROUND_HALF_UP`), dedup by `(Year, Tournament, Team)`.
6. **Compute `Elim Wins`/`Elim Losses`** — not produced by any ingest
   column directly, has to be derived:
   - Non-advancing team: `0-0`.
   - **A win or bye in a tournament's partial/under-strength first elim
     round counts as a real elim win** (not just partial point credit) —
     this was missed early on and had to be bulk-corrected across the
     whole dataset once discovered. `Elim Wins = (1 if Partial Elim > 0
     else 0) + count(True in the 1st–7th Full Win columns)`.
   - `Elim Losses = 0` for whoever has the tournament's **max** `Elim
     Wins` (the champion, or tied co-champions in a festival/bronze-gold
     format), `1` for every other team that broke to elims.
7. **Verify before pushing**: spin up `python3 -m http.server`, drive it
   with Playwright (`/opt/pw-browsers/chromium`, tailwind CDN is blocked
   in-sandbox so ignore that one console error), check the Tournaments
   view shows the right champion, spot-check a modal.
8. Push to the feature branch, then `main` once asked.

## Scrapers (`scrapers/`)

Offline tools, not part of the deployed site. Each outputs the same
ingest-template row shape. Install deps fresh each session (`pip3
install pdfplumber pandas openpyxl cffi`, `apt-get install tesseract-ocr`
— container doesn't persist them). Run Python interpreters with `-I` on
anything from an untrusted download.

- **`tabroom_scraper.py`** — Tabroom JSON. Falls back to the tournament's
  posted "Ballots" text when ballot-level winloss scores are missing —
  decided **per-debate**, not once for the whole event (an export can
  have prelims fully scored but elims not yet judged).
- **`FTN_Scraper.py`** — FTN PDF tab reports, real embedded text (no
  OCR). `_strip_parens()` handles name annotations: removes well-formed
  `(...)` pairs first (so a mid-name nickname like `"William (Liam)
  Ward"` doesn't eat the real last name after it), then falls back to
  stripping an unclosed `(` to end of string (a tournament's own
  data-entry error, e.g. `"Valerie Mulure (pronounced moo-loo-ray"`).
- **`speechwire_scraper.py`** — two input formats:
  - Older/combined: one PDF with a standings table (OCR'd via Tesseract,
    SpeechWire obfuscates its font) plus a bracket-tree page.
    `_is_standings_header()` OCRs the header and requires it read
    "Competitor" before trusting a 6+-column table (guards against
    mis-picking an "Individual Speakers" table).
  - Newer: a "tab grouping" prelim sheet + separate "awards assembly
    script" PDF (real text, no OCR). `parse_speechwire_tab_grouping_
    tournament()`. Round names in the script must match SpeechWire's
    exact spelling in `TAB_GROUPING_ROUND_PRIORITY`/`_FULL_SIZE`
    ("Octafinalists", not "Octofinalists" — a mismatch silently
    misorders rounds instead of raising).

## Site conventions

- `SCHOOL_ALIASES`/`NAME_ALIASES` (top of the main `<script>` block)
  canonicalize raw spelling variants at render time — never edit raw
  `tournamentLogs` rows to "fix" a name, always add/extend an alias.
- View modes (`currentViewMode`): `teams`, `partnerships`, `debaters`,
  `schoolsAllTime`, `schoolsBySeason`, `tournaments`. Each has its own
  `build*Data()` aggregation and mode-aware `renderTableHeader()`/
  `renderTable()`.
- Debater names in leaderboard rows link to the **team/partnership**
  view, not directly to the individual debater — this was tried and
  explicitly reverted; the dedicated "Individual Debater Leaderboard"
  view mode is the intended way to reach a person's career stats.
- `NATIONAL_TITLES` — manually curated list of championship pairs,
  independent of `tournamentLogs`; update by hand when a new champion is
  crowned at nationals (not inferable from regular-season data).
- Points Calculator modal (`computeCalcPoints`/`mround05` in the main
  script) is a JS port of `sync_ingest.py`'s formula — keep both in sync
  if the scoring formula ever changes.

## Recap posts

When asked to "write the update post" after an ingest, the established
format (no emojis): a one-line note on which tournament the update
covers, new #1 (or confirm it held), current season top 5 with
points/record, the biggest riser (compare season rankings with vs.
without the new tournament, by rank delta), and the final-round result.
Compute the "before" snapshot by re-running season rankings excluding
just the new tournament's rows from `tournamentLogs`.

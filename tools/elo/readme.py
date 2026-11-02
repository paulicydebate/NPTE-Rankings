"""Writes README.md from the build outputs (called at the end of build.py)."""
import csv, collections, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(HERE, f)


def main(cfg):
    rows = list(csv.DictReader(open(P('matchups.csv'))))
    cov = list(csv.DictReader(open(P('coverage.csv'))))
    val = list(csv.DictReader(open(P('validation.csv'))))
    deb = [r for r in rows if r['status'] != 'BYE']
    st = collections.Counter(r['status'] for r in rows)
    bys = collections.Counter(r['season'] for r in deb)
    cnt = collections.Counter(r['season'] for r in deb if r['status'] in ('CONFIRMED', 'INFERRED'))
    L = []
    w = L.append
    w('# NPTE-Rankings: round-by-round matchups, ELO, and head-to-head\n')
    w('Everything here is rebuilt from the source files by `python3 build.py` (about a minute; OCR text is cached in `cache/`).')
    w('Open `h2h.html` by double-clicking it. The data is embedded, so it works offline.\n')
    w('## Files\n')
    w('| file | what |\n|---|---|')
    for f, d in [('matchups.csv', 'one row per debate/meeting (byes included as status BYE): season, tournament, tourn_order, round, round_order, round_type, aff_team, aff_debaters, neg_team, neg_debaters, sides_known, winner, ballots, judges, status, note, source'),
                 ('elo_partnerships.csv / elo_debaters.csv', 'per season (scope=season) and all-time (scope=all-time): rank, rating, season_start, peak, games, W, L'),
                 ('elo_history.csv', 'rating before/after every counted debate, for every partnership and debater, both scopes'),
                 ('h2h.html', 'head-to-head search (debater or partnership, optional opponent, season filter) + ELO leaderboard tab'),
                 ('debater_ids.csv', 'every debater id (canonical site spelling after NAME_ALIASES), whether on the site, source spellings seen, possible duplicates (never merged)'),
                 ('uncertain_matches.csv', 'source teams matched to a site team with a fuzzy name match'),
                 ('teams_not_on_site.csv', 'teams in the sources that have no row on the site for that tournament'),
                 ('validation.csv', 'per site team: site prelim/elim W-L vs parsed W-L'),
                 ('coverage.csv', 'per tournament: source, parsed debates vs the site, status counts, mismatches'),
                 ('build_notes.txt', 'inferred/generated rounds, same-school prelims, parse issues per tournament'),
                 ('build.py, p_tabroom.py, p_ftn.py, p_speechwire.py, common.py, site_extract.js, h2h_template.html, readme.py', 'the code')]:
        w(f'| `{f}` | {d} |')
    w('\n## Totals\n')
    w(f'{len(deb)} debates/meetings (byes excluded); {sum(cnt.values())} count for ELO. Status counts over all rows: ' +
      ', '.join(f'{k} {v}' for k, v in st.most_common()) + '.\n')
    w('| season | debates | counted for ELO |\n|---|---|---|')
    for s in sorted(bys):
        w(f'| {s} | {bys[s]} | {cnt[s]} |')
    w('\n## Rules applied\n')
    w('- **Status**: CONFIRMED = result read from the source. INFERRED = winner (or a whole missing round) derived: from the team that shows up in the next elim round, from the site\'s per-team prelim/elim record when that forces the answer, or from the accepted Mound High pt 1 2024 CSV. '
      'WALKOVER = a same-school elim meeting (the team advances but it is not a debate). BYE = bye (not a debate). FORFEIT = Tabroom forfeit flag. UNKNOWN = pairing known but result unknown or the two result sheets conflict and the site record cannot settle it. '
      '**Only CONFIRMED and INFERRED count for ELO**. Walkovers, byes, forfeits and unknowns are shown in the H2H page but marked "not a debate".')
    w('- Multi-judge panels: `ballots` holds the count (e.g. 2-1) and `winner` the decision. ELO uses the decision. Set `BALLOT_WEIGHT = True` at the top of build.py to score a 2-1 as 0.667/0.333 instead.')
    w('- Same-person merges: 12 groups confirmed by Paul are merged to one id (most common or site spelling), listed in `debater_aliases.csv` (`PERSON_MERGE` in build.py). Juliette and Julissa Celis are **not** merged because they are partners on the same team, so they are two people.')
    w('- DOUBLE_WIN = FTN "W&W" (both teams credited a win): not a decided debate, so it does not count for ELO.')
    w('- Identity: source names go through the site\'s NAME_ALIASES, then each source team is matched to a site row for the same tournament on debater names (exact > same last name + first initial > close spelling), with school as a tie-breaker. A matched team takes the site\'s spelling. '
      'Partnerships are unordered pairs. Fuzzy matches are listed in `uncertain_matches.csv`. Near-identical debater ids are flagged in `debater_ids.csv` and **not merged**.')
    w('- Tournaments run in `calendar/tournament_calendar.csv` order, with rounds in order within each one.')
    w('- Mile High pt 1 2023: skipped (Paul: no matchups). Mound High pt 1 2024: the accepted `mound-high-pt1-2024/matchups.csv` is used as is (its R1-R3/R5 pairings do not exist; two quarterfinals with an "X or Y" opponent are UNKNOWN).')
    w('\n## ELO settings\n')
    w(f'- Start {cfg["start"]}, K = {cfg["k"]} (elims K = {cfg["kelim"]}), standard logistic expectation (400 scale). Constants are at the top of build.py.')
    w(f'- **Season scope: no hard reset.** At each new season every debater regresses to the mean: start = {cfg["start"]} + R x (previous season end - {cfg["start"]}), with R = `SEASON_CARRY_R` = {cfg["carry"]}. '
      f'Brand-new debaters start at {cfg["start"]}. A partnership starts each season at the average of its two debaters\' carried-over ratings, so a new pairing of experienced debaters does not start at {cfg["start"]}. A partnership first formed mid-season also starts at its debaters\' season-start average. R = 0 would give a hard reset.')
    w(f'- All-time scope: one continuous run with no regression. A partnership\'s first debate starts at the average of its debaters\' current ratings.')
    w('- Debaters: each debater updates from the team result against the opposing team\'s average debater rating (pre-debate ratings).')
    w('- Mavericks (one-person teams) are treated as a one-debater partnership.')
    w('\n## Coverage per tournament\n')
    w('`prelim` = parsed prelim debates / upper bound from the site (sum of site prelim W+L / 2, which counts byes and includes rounds the site has). `elim` = parsed elim debates (byes excluded) / site elim losses. `W-L ok` = site teams whose parsed record matches the site.\n')
    w('| season | tournament | platform | prelim | elim | inferred | unknown | walkover | W-L ok / site teams | notes |\n|---|---|---|---|---|---|---|---|---|---|')
    for c in cov:
        if c['status'] != 'parsed':
            w(f'| {c["season"]} | {c["tournament"]} | {c["platform"]} | - | - | - | - | - | - | {c["status"]} |')
            continue
        w(f'| {c["season"]} | {c["tournament"]} | {c["platform"]} | {c["parsed_prelim_debates"]}/{c["site_prelim_upper_bound"]} | {c["parsed_elim_debates"]}/{c["site_elim_losses"]} | '
          f'{c["inferred"]} | {c["unknown"]} | {c["walkover"]} | {c["wl_match"]}/{c["site_teams"]} | {"OCR" if "OCR" in c["source"] else ""} |')
    w('\n## Mismatches against the site (validation.csv)\n')
    vc = collections.Counter(v['match'] for v in val)
    w(f'{vc["Y"]} of {len(val)} site team-records match the parsed W-L exactly (byes counted the way the site counts them), {vc["N"]} differ, {vc.get("NOT FOUND IN SOURCE", 0)} site teams are not found in the source.\n')
    w(EXTRA)
    w(VERIFY)
    w('\n## Parsing caveats\n')
    w(CAVEATS)
    open(P('README.md'), 'w').write('\n'.join(L) + '\n')


VERIFY = """
## Official-source verification (Nov 2, 2026)

- **FTN, all 51 tournaments**: the official result sheets (`https://forensicstournament.net/<slug>/<yy>/results/et/<id>`, Open NPDA/Parli division) were fetched through fetch-cached (`ftn_live.py` -> `cache/ftn_live.json`) and compared team by team and round by round with the PDF parse (`ftn_compare.py` -> `cache/ftn_compare.csv`). Every prelim pairing and decision matches, except for these fixes:
  - 4 "W&W" **double wins**, where both teams were credited a win: NCFA Spring 2022 R5 Berck/Karnavat vs Sandhiparthi/Smithson, PSCFA Fall 2023 R4 Durepo/Halbert vs Bartl/Simon, The Bernacchi 2024 R1 Deivaprakash/Goodman vs Schroers/Wilson, and PSCFA Spring 2025 R3 Hepburn/Carvajal vs Osorio/Syring. They were INFERRED before and are now status DOUBLE_WIN, not counted for ELO, and counted as a win for both teams in validation. (NCFA Spring 2022 had no sheet at the time, so the build still shows 3 DOUBLE_WIN rows and this one stays INFERRED; see the README section.)
  - Crossman 2021: Mae Riley's partner is **Jose Chavez** (the PDF and the site say "N/A").
  - "N/A" is no longer a debater id. A team with an "N/A" partner is a one-person team.
  - The remaining compare lines are label-only: FTN calls its elim rounds Bronze and Gold. Talk Hawk 2026 "Aly" on the site is "Aly Greaver" on the sheet.
- **The 4-vs-5 prelim issue is a site data error.** In Crossman 2022, Crossman 2023, Jannese Davidson 2023, Talk Hawk 2023, Talk Hawk 2024, NCFA Spring 2022, NCFA Spring 2023, Gorlock Gala 2023 and Great Salt Lake 2024, the official sheets show 5 real prelims for every team. The only byes are a few "ZZ" bye wins. No round belongs to another event. For every team in those tournaments the site stores prelim losses as max(0, 4 - wins), while wins are right. Example: Crossman 2022 Maszk/Shurance went 4-1 officially and shows 4-0 on the site. These rows are tagged `SITE ERROR` in the validation.csv `explanation` column.
- **Rice 2024** (Tabroom API re-pulled, tourn_id 32594, identical to the repo JSON): Holden Carrillo & Michael Lan won octos (3-0 over Stansbery/Carroll) and quarters (2-1 over Dixon/Terry), then lost semis to Surya/Sanderfer, so 2-1. Anthony Carrillo & Alexia Gallon lost octos to Surya/Sanderfer, so 0-1. The site has 1-1 and 2-1, which looks swapped. **Site error.**
- **Tabroom re-pulls** (API for Big Red 2025/2026, Big Tent 2022/2023, GGI 2025/2026, Mile High pt1 2022, Mile High pt2 2023, Mound pt2 2024, Mound pt1 2026, Rice 2023/2024, Mercer Macke 2023, William Jewell pt2 2024): all identical to the repo JSONs. The API has no Big Red 2026 octos, no Mile High pt2 2023 octo results, nothing past quarters for GGI 2025, and no varsity NPDA elims for Big Tent 2023. The Tabroom HTML results and bracket pages need a logged-in browser, so these are **still missing**. They need a browser pass of `tabroom.com/index/tourn/results/index.mhtml?tourn_id=37636 / 25894 / 34235 / 27495`.
- **Mound High pt 1 2024** (11 UNKNOWN rows): the Tabroom JSON has pairings but no ballots, so these are still missing. The accepted CSV is used as is.
- **SpeechWire** (Steve Hunt 2021/2023/2025, Paul Winters 2023): `c-results.php` and `c-postings-pub.php` return 404, and `c-postings-results.php?tournid=11597` returns an empty shell. These are **still missing**, so the OCR parse stands.
"""

EXTRA = """The main patterns (details per team in validation.csv):
- **Site error, prelim losses stored as 4 - wins** in 9 FTN tournaments. This is confirmed against the official sheets (see above).
- **Missing elim rounds in the source**: Big Red 2026 (Tabroom JSON has no octafinal round), Mile High pt 2 2023 (only octos, no winners), GGI 2025 (only quarters), Big Tent 2023, Steve Hunt 2021/2025 (OCR could not read every elim line). Those teams' elim records are short.
- **Rice 2024**: site error (swapped elim records), confirmed from the Tabroom API.
- **Elim byes / walkovers**: where an elim bye or a same-school walkover exists, the site counts it as an elim win. Validation accepts that. A few residual elim mismatches are on teams with a closeout.
- **Mound High pt 1 2024**: R1-R3/R5 are unknown by design (accepted CSV), so the 10 teams' prelim records cannot match."""

CAVEATS = """- **OCR**: Steve Hunt 2021, 2023, 2025 and Paul Winters 2023 are image/garbled PDFs. They were OCR'd with tesseract (300 dpi). Each prelim debate is read from both teams' grid cells and merged, a missing or conflicting result is filled from the site record when forced, otherwise left UNKNOWN. Judges are missing for many OCR prelims. Some OCR names are misspelled on the site too (e.g. "Anvla Hall", "Skv-Rose Jaamann" in Steve Hunt 2025). Those come through with the site spelling and are listed in uncertain_matches.csv.
- **Steve Hunt 2026**: prelims from the tab-grouping sheet (`Steve Hunt Prelims.pdf`), elims OCR'd from `new-sources/Steve Hunt - 2026 elim results.pdf`. One team block (Parliamentary SY) is split across a page break. It was matched to Daniel Siu & Jonathan Daoyan Yu by school + code initials (flagged).
- **Paul Winters 2024**: grid + elim-results PDFs from `new-sources/Paul Winters - 2024 PDFs/`.
- **Rice 2022**: `new-sources/Rice University Classic - 2022.json` (raw Tabroom).
- **FTN**: opponents without their own result sheet (Jannese Davidson 2022Jan PDB Krishnan/Rashid, Gorlock 2023 Simpson, NPDA Fall 2025 WJC Lepage/Massey, Robert Barbera 2025 Kim/Gurrola, GGO 2024, Great Salt Lake 2024) are taken from the opponent cell. Same-school finals with "?" decisions (Missouri Mule 2021, Sunset Cliffs 2021, Great Salt Lake 2025 semis, GGO 2021) are WALKOVERs. Where both sheets show the same decision (NCFA Spring 2022 R5, PSCFA Fall 2023 R4, PSCFA Spring 2025 R3, Bernacchi 2024 R1), the winner comes from the site record if forced, otherwise UNKNOWN.
- **Same-school prelims** do appear in a few small FTN tournaments (Norene Hockett 2021, Jannese Davidson 2023, Great Salt Lake 2024, Crossman 2025Jan, Sunset Cliffs 2025). They are kept as debates and listed in build_notes.txt.
- **Bracket inference**: a seed-based bracket rebuild was tested on complete Tabroom brackets. It did not reproduce the real pairings (tournaments re-pair or re-seed), so it is **not used**. Missing rounds are generated only when they are forced (two teams left = final, or SpeechWire's bracket-ordered list). Generated rounds are INFERRED or WALKOVER, with no sides or judges.
- Sides: `sides_known = N` when the source does not give sides (byes, generated rounds, some OCR/SpeechWire finals). Those rows list the first team under aff_* for layout only.
- Gaske Memorial 2022.pdf and the duplicate Crossman 2021 / Jannese Davidson 2024 exports are not used (no calendar entry / duplicates)."""

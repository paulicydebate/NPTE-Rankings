# NPTE-Rankings: round-by-round matchups, ELO, and head-to-head

Everything here is rebuilt from the source files by `python3 build.py` (about a minute; OCR text is cached in `cache/`).
Open `h2h.html` by double-clicking it. The data is embedded, so it works offline.

## Files

| file | what |
|---|---|
| `matchups.csv` | one row per debate/meeting (byes included as status BYE): season, tournament, tourn_order, round, round_order, round_type, aff_team, aff_debaters, neg_team, neg_debaters, sides_known, winner, ballots, judges, status, note, source |
| `elo_partnerships.csv / elo_debaters.csv` | per season (scope=season) and all-time (scope=all-time): rank, rating, season_start, peak, games, W, L |
| `elo_history.csv` | rating before/after every counted debate, for every partnership and debater, both scopes |
| `h2h.html` | head-to-head search (debater or partnership, optional opponent, season filter) + ELO leaderboard tab |
| `debater_ids.csv` | every debater id (canonical site spelling after NAME_ALIASES), whether on the site, source spellings seen, possible duplicates (never merged) |
| `uncertain_matches.csv` | source teams matched to a site team with a fuzzy name match |
| `teams_not_on_site.csv` | teams in the sources that have no row on the site for that tournament |
| `validation.csv` | per site team: site prelim/elim W-L vs parsed W-L |
| `coverage.csv` | per tournament: source, parsed debates vs the site, status counts, mismatches |
| `build_notes.txt` | inferred/generated rounds, same-school prelims, parse issues per tournament |
| `build.py, p_tabroom.py, p_ftn.py, p_speechwire.py, common.py, site_extract.js, h2h_template.html, readme.py` | the code |

## Totals

4362 debates/meetings (byes excluded); 4301 count for ELO. Status counts over all rows: CONFIRMED 4263, BYE 418, WALKOVER 40, INFERRED 38, UNKNOWN 13, DOUBLE_WIN 4, FORFEIT 4.

| season | debates | counted for ELO |
|---|---|---|
| 2021-2022 | 663 | 657 |
| 2022-2023 | 551 | 544 |
| 2023-2024 | 745 | 724 |
| 2024-2025 | 1062 | 1049 |
| 2025-2026 | 1080 | 1067 |
| 2026-2027 | 261 | 260 |

## Rules applied

- **Status**: CONFIRMED = result read from the source. INFERRED = winner (or a whole missing round) derived: from the team that shows up in the next elim round, from the site's per-team prelim/elim record when that forces the answer, or from the accepted Mound High pt 1 2024 CSV. WALKOVER = a same-school elim meeting (the team advances but it is not a debate). BYE = bye (not a debate). FORFEIT = Tabroom forfeit flag. UNKNOWN = pairing known but result unknown or the two result sheets conflict and the site record cannot settle it. **Only CONFIRMED and INFERRED count for ELO**. Walkovers, byes, forfeits and unknowns are shown in the H2H page but marked "not a debate".
- Multi-judge panels: `ballots` holds the count (e.g. 2-1) and `winner` the decision. ELO uses the decision. Set `BALLOT_WEIGHT = True` at the top of build.py to score a 2-1 as 0.667/0.333 instead.
- Same-person merges: 12 groups confirmed by Paul are merged to one id (most common or site spelling), listed in `debater_aliases.csv` (`PERSON_MERGE` in build.py). Juliette and Julissa Celis are **not** merged because they are partners on the same team, so they are two people.
- DOUBLE_WIN = FTN "W&W" (both teams credited a win): not a decided debate, so it does not count for ELO.
- Identity: source names go through the site's NAME_ALIASES, then each source team is matched to a site row for the same tournament on debater names (exact > same last name + first initial > close spelling), with school as a tie-breaker. A matched team takes the site's spelling. Partnerships are unordered pairs. Fuzzy matches are listed in `uncertain_matches.csv`. Near-identical debater ids are flagged in `debater_ids.csv` and **not merged**.
- Tournaments run in `calendar/tournament_calendar.csv` order, with rounds in order within each one.
- Mile High pt 1 2023: skipped (Paul: no matchups). Mound High pt 1 2024: the accepted `mound-high-pt1-2024/matchups.csv` is used as is (its R1-R3/R5 pairings do not exist; two quarterfinals with an "X or Y" opponent are UNKNOWN).

## ELO settings

- Start 1500, K = 32 (elims K = 32), standard logistic expectation (400 scale). Constants are at the top of build.py.
- **Season scope: no hard reset.** At each new season every debater regresses to the mean: start = 1500 + R x (previous season end - 1500), with R = `SEASON_CARRY_R` = 0.75. Brand-new debaters start at 1500. A partnership starts each season at the average of its two debaters' carried-over ratings, so a new pairing of experienced debaters does not start at 1500. A partnership first formed mid-season also starts at its debaters' season-start average. R = 0 would give a hard reset.
- All-time scope: one continuous run with no regression. A partnership's first debate starts at the average of its debaters' current ratings.
- Debaters: each debater updates from the team result against the opposing team's average debater rating (pre-debate ratings).
- Mavericks (one-person teams) are treated as a one-debater partnership.

## Coverage per tournament

`prelim` = parsed prelim debates / upper bound from the site (sum of site prelim W+L / 2, which counts byes and includes rounds the site has). `elim` = parsed elim debates (byes excluded) / site elim losses. `W-L ok` = site teams whose parsed record matches the site.

| season | tournament | platform | prelim | elim | inferred | unknown | walkover | W-L ok / site teams | notes |
|---|---|---|---|---|---|---|---|---|---|
| 2021-2022 | GGO - 2021 | FTN | 16/14 | 3/3 | 0 | 0 | 1 | 7/7 |  |
| 2021-2022 | Rice University Classic - 2021 | Tabroom | 60/60 | 12/12 | 0 | 0 | 0 | 24/24 |  |
| 2021-2022 | Norene Hockett - 2021 | FTN | 15/16 | 1/1 | 0 | 0 | 0 | 8/8 |  |
| 2021-2022 | Steve Hunt - 2021 | SpeechWire | 40/42 | 6/8 | 6 | 0 | 1 | 11/17 | OCR |
| 2021-2022 | Crossman - 2021 | FTN | 54/54 | 8/10 | 0 | 0 | 0 | 16/18 |  |
| 2021-2022 | Missouri Mule - 2021 | FTN | 45/45 | 7/9 | 0 | 0 | 1 | 16/18 |  |
| 2021-2022 | Sunset Cliffs - 2021 | FTN | 32/32 | 7/7 | 0 | 0 | 1 | 16/16 |  |
| 2021-2022 | Grossmont Griffin - 2021 | FTN | 28/30 | 3/3 | 0 | 0 | 0 | 15/15 |  |
| 2021-2022 | DVC Thing - 2021 | FTN | 24/26 | 5/5 | 0 | 0 | 1 | 11/13 |  |
| 2021-2022 | PSCFA Fall Champs - 2021 | FTN | 16/16 | 3/3 | 0 | 0 | 0 | 8/8 |  |
| 2021-2022 | Mile High pt 1 - 2022 | Tabroom | 30/32 | 5/5 | 0 | 0 | 0 | 10/13 |  |
| 2021-2022 | Mile High pt 2 - 2022 | Tabroom | 45/45 | 9/9 | 0 | 0 | 0 | 18/18 |  |
| 2021-2022 | Gorlock Gala - 2022 | FTN | 35/35 | 8/8 | 0 | 0 | 0 | 14/14 |  |
| 2021-2022 | Jannese Davidson - 2022Jan | FTN | 35/35 | 9/9 | 0 | 0 | 0 | 14/14 |  |
| 2021-2022 | NCFA Spring Champs - 2022 | FTN | 25/25 | 5/5 | 0 | 0 | 0 | 8/10 |  |
| 2021-2022 | Tabor Venitsky - 2022 | FTN | 28/28 | 5/5 | 0 | 0 | 0 | 14/14 |  |
| 2021-2022 | PSCFA Spring Champs - 2022 | FTN | 32/34 | 7/7 | 0 | 0 | 0 | 17/17 |  |
| 2022-2023 | Rice University Classic - 2022 | Tabroom | 35/37 | 7/7 | 0 | 0 | 2 | 15/15 |  |
| 2022-2023 | GGO - 2022 | FTN | 16/18 | 3/3 | 0 | 0 | 1 | 9/9 |  |
| 2022-2023 | Steve Hunt - 2022 | SpeechWire | 30/32 | 5/5 | 0 | 0 | 1 | 13/13 |  |
| 2022-2023 | Sunset Cliffs - 2022 | FTN | 24/26 | 5/5 | 0 | 0 | 0 | 13/13 |  |
| 2022-2023 | Paul Winters - 2022 | SpeechWire | 25/27 | 5/5 | 0 | 0 | 1 | 11/11 |  |
| 2022-2023 | Crossman - 2022 | FTN | 35/35 | 7/7 | 0 | 0 | 1 | 14/14 |  |
| 2022-2023 | DVC Thing - 2022 | FTN | 28/28 | 4/4 | 0 | 0 | 0 | 14/14 |  |
| 2022-2023 | Big Tent - 2022 | Tabroom | 35/35 | 6/5 | 0 | 0 | 0 | 12/14 |  |
| 2022-2023 | Mile High pt 1 - 2023 | Tabroom | - | - | - | - | - | - | SKIPPED: Paul: ignore (no matchups available) |
| 2022-2023 | Mile High pt 2 - 2023 | Tabroom | 45/45 | 10/9 | 10 | 0 | 0 | 18/19 |  |
| 2022-2023 | Gorlock Gala - 2023 | FTN | 22/22 | 4/4 | 0 | 0 | 0 | 9/9 |  |
| 2022-2023 | Jannese Davidson - 2023 | FTN | 70/72 | 14/14 | 0 | 0 | 0 | 29/29 |  |
| 2022-2023 | Talk Hawk - 2023 | FTN | 25/27 | 5/5 | 0 | 0 | 1 | 11/11 |  |
| 2022-2023 | Gaske - 2023 | FTN | 44/44 | 7/7 | 0 | 0 | 0 | 22/22 |  |
| 2022-2023 | NCFA Spring Champs - 2023 | FTN | 30/30 | 5/5 | 0 | 0 | 0 | 12/12 |  |
| 2023-2024 | GGO - 2023 | FTN | 16/16 | 3/3 | 0 | 0 | 0 | 8/8 |  |
| 2023-2024 | Rice University Classic - 2023 | Tabroom | 60/60 | 10/11 | 0 | 0 | 2 | 22/24 |  |
| 2023-2024 | Steve Hunt - 2023 | SpeechWire | 40/45 | 10/10 | 1 | 0 | 1 | 14/18 | OCR |
| 2023-2024 | BLCC - 2023 | FTN | 20/22 | 3/3 | 0 | 0 | 2 | 11/11 |  |
| 2023-2024 | Mercer Macke - 2023 | Tabroom | 40/40 | 7/8 | 0 | 0 | 0 | 15/17 |  |
| 2023-2024 | Paul Winters - 2023 | SpeechWire | 50/40 | 7/7 | 8 | 0 | 0 | 6/16 | OCR |
| 2023-2024 | Crossman - 2023 | FTN | 40/40 | 7/7 | 0 | 0 | 2 | 16/16 |  |
| 2023-2024 | The Bernacchi - 2023 | FTN | 20/20 | 2/2 | 0 | 0 | 0 | 10/10 |  |
| 2023-2024 | Big Tent - 2023 | Tabroom | 25/25 | 2/4 | 0 | 0 | 1 | 5/10 |  |
| 2023-2024 | PSCFA Fall Champs - 2023 | FTN | 60/60 | 10/10 | 0 | 0 | 0 | 30/30 |  |
| 2023-2024 | Mound High pt 1 - 2024 | Tabroom | 10/25 | 9/9 | 5 | 11 | 0 | 0/10 |  |
| 2023-2024 | Mound High pt 2 - 2024 | Tabroom | 45/45 | 8/9 | 8 | 0 | 0 | 17/19 |  |
| 2023-2024 | Great Salt Lake - 2024 | FTN | 35/35 | 3/6 | 0 | 0 | 0 | 11/14 |  |
| 2023-2024 | Jannese Davidson - 2024Jan | FTN | 85/85 | 15/17 | 0 | 0 | 1 | 32/34 |  |
| 2023-2024 | Talk Hawk - 2024 | FTN | 35/35 | 5/5 | 0 | 0 | 0 | 14/14 |  |
| 2023-2024 | Gaske - 2024 | FTN | 32/34 | 7/7 | 0 | 0 | 0 | 17/17 |  |
| 2023-2024 | NCFA Spring Champs - 2024 | FTN | 20/20 | 4/4 | 0 | 0 | 0 | 10/10 |  |
| 2024-2025 | GGO - 2024 | FTN | 24/24 | 5/5 | 0 | 0 | 0 | 12/12 |  |
| 2024-2025 | Rice University Classic - 2024 | Tabroom | 70/70 | 14/14 | 0 | 0 | 0 | 29/29 |  |
| 2024-2025 | Jannese Davidson - 2024oct | FTN | 50/52 | 11/11 | 0 | 0 | 0 | 21/21 |  |
| 2024-2025 | Steve Hunt - 2024 | SpeechWire | 50/50 | 11/11 | 0 | 0 | 0 | 20/20 |  |
| 2024-2025 | Paul Winters - 2024 | SpeechWire | 70/72 | 13/13 | 0 | 0 | 1 | 26/29 |  |
| 2024-2025 | William Jewell pt 1 - 2024 | Tabroom | 50/50 | 10/10 | 0 | 0 | 0 | 20/20 |  |
| 2024-2025 | The Bernacchi - 2024 | FTN | 24/24 | 2/2 | 0 | 0 | 1 | 12/12 |  |
| 2024-2025 | William Jewell pt 2 - 2024 | Tabroom | 50/50 | 10/9 | 0 | 0 | 3 | 19/20 |  |
| 2024-2025 | PSCFA Fall Champs - 2024 | FTN | 48/50 | 7/7 | 0 | 0 | 0 | 25/25 |  |
| 2024-2025 | Mound High pt 1 - 2025 | Tabroom | 72/72 | 17/17 | 0 | 0 | 0 | 36/36 |  |
| 2024-2025 | Mound High pt 2 - 2025 | Tabroom | 85/85 | 18/18 | 0 | 0 | 0 | 35/35 |  |
| 2024-2025 | Crossman - 2025Jan | FTN | 45/47 | 8/8 | 0 | 0 | 0 | 19/19 |  |
| 2024-2025 | Great Salt Lake - 2025 | FTN | 25/25 | 3/4 | 0 | 0 | 2 | 9/10 |  |
| 2024-2025 | Big Red - 2025 | Tabroom | 57/56 | 12/11 | 0 | 0 | 0 | 21/23 |  |
| 2024-2025 | Talk Hawk - 2025 | FTN | 30/30 | 6/6 | 0 | 0 | 0 | 12/12 |  |
| 2024-2025 | GGI - 2025 | Tabroom | 32/30 | 6/5 | 0 | 2 | 2 | 10/13 |  |
| 2024-2025 | NCFA Spring Champs - 2025 | FTN | 36/36 | 7/7 | 0 | 0 | 0 | 18/18 |  |
| 2024-2025 | PSCFA Spring Champs - 2025 | FTN | 72/74 | 12/12 | 0 | 0 | 0 | 37/37 |  |
| 2025-2026 | GGO - 2025 | FTN | 24/24 | 5/5 | 0 | 0 | 1 | 12/12 |  |
| 2025-2026 | Rice University Classic - 2025 | Tabroom | 45/45 | 7/7 | 0 | 0 | 0 | 18/18 |  |
| 2025-2026 | Steve Hunt - 2025 | SpeechWire | 63/64 | 8/12 | 0 | 0 | 0 | 18/26 | OCR |
| 2025-2026 | Crossman - 2025 | FTN | 60/62 | 12/12 | 0 | 0 | 0 | 25/25 |  |
| 2025-2026 | Gina Lane pt 1 - 2025 | Tabroom | 49/47 | 7/7 | 0 | 0 | 0 | 19/19 |  |
| 2025-2026 | Sunset Cliffs - 2025 | FTN | 32/32 | 7/7 | 0 | 0 | 0 | 16/16 |  |
| 2025-2026 | Gina Lane pt 2 - 2025 | Tabroom | 60/60 | 10/10 | 0 | 0 | 0 | 24/24 |  |
| 2025-2026 | Paul Winters - 2025 | SpeechWire | 60/60 | 11/11 | 0 | 0 | 1 | 24/24 |  |
| 2025-2026 | Robert Barbera - 2025 | FTN | 33/34 | 3/3 | 0 | 0 | 0 | 17/17 |  |
| 2025-2026 | The Bernacchi - 2025 | FTN | 36/38 | 5/5 | 0 | 0 | 1 | 19/19 |  |
| 2025-2026 | NPDA Fall Champs - 2025 | FTN | 52/52 | 10/10 | 0 | 0 | 0 | 21/21 |  |
| 2025-2026 | Mound High pt 1 - 2026 | Tabroom | 75/77 | 15/16 | 0 | 0 | 0 | 29/31 |  |
| 2025-2026 | Mound High pt 2 - 2026 | Tabroom | 75/77 | 15/15 | 0 | 0 | 0 | 31/31 |  |
| 2025-2026 | Great Salt Lake - 2026 | Tabroom | 35/37 | 7/7 | 0 | 0 | 1 | 15/15 |  |
| 2025-2026 | GGI - 2026 | Tabroom | 90/92 | 17/17 | 0 | 0 | 1 | 34/37 |  |
| 2025-2026 | Talk Hawk - 2026 | FTN | 40/40 | 7/7 | 0 | 0 | 3 | 14/16 |  |
| 2025-2026 | Big Red - 2026 | Tabroom | 79/77 | 7/15 | 0 | 0 | 0 | 15/31 |  |
| 2025-2026 | NCFA Spring Champs - 2026 | FTN | 16/18 | 3/3 | 0 | 0 | 1 | 8/9 |  |
| 2026-2027 | GGO - 2026 | FTN | 27/27 | 7/7 | 0 | 0 | 0 | 18/18 |  |
| 2026-2027 | Rice University Classic - 2026 | Tabroom | 55/57 | 12/12 | 0 | 0 | 0 | 23/23 |  |
| 2026-2027 | Steve Hunt - 2026 | SpeechWire | 65/65 | 11/11 | 0 | 0 | 0 | 26/26 | OCR |
| 2026-2027 | Crossman - 2026 | FTN | 70/70 | 14/14 | 0 | 0 | 1 | 28/28 |  |

## Mismatches against the site (validation.csv)

1502 of 1604 site team-records match the parsed W-L exactly (byes counted the way the site counts them), 102 differ, 0 site teams are not found in the source.

The main patterns (details per team in validation.csv):
- **Site error, prelim losses stored as 4 - wins** in 9 FTN tournaments. This is confirmed against the official sheets (see above).
- **Missing elim rounds in the source**: Big Red 2026 (Tabroom JSON has no octafinal round), Mile High pt 2 2023 (only octos, no winners), GGI 2025 (only quarters), Big Tent 2023, Steve Hunt 2021/2025 (OCR could not read every elim line). Those teams' elim records are short.
- **Rice 2024**: site error (swapped elim records), confirmed from the Tabroom API.
- **Elim byes / walkovers**: where an elim bye or a same-school walkover exists, the site counts it as an elim win. Validation accepts that. A few residual elim mismatches are on teams with a closeout.
- **Mound High pt 1 2024**: R1-R3/R5 are unknown by design (accepted CSV), so the 10 teams' prelim records cannot match.

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


## Parsing caveats

- **OCR**: Steve Hunt 2021, 2023, 2025 and Paul Winters 2023 are image/garbled PDFs. They were OCR'd with tesseract (300 dpi). Each prelim debate is read from both teams' grid cells and merged, a missing or conflicting result is filled from the site record when forced, otherwise left UNKNOWN. Judges are missing for many OCR prelims. Some OCR names are misspelled on the site too (e.g. "Anvla Hall", "Skv-Rose Jaamann" in Steve Hunt 2025). Those come through with the site spelling and are listed in uncertain_matches.csv.
- **Steve Hunt 2026**: prelims from the tab-grouping sheet (`Steve Hunt Prelims.pdf`), elims OCR'd from `new-sources/Steve Hunt - 2026 elim results.pdf`. One team block (Parliamentary SY) is split across a page break. It was matched to Daniel Siu & Jonathan Daoyan Yu by school + code initials (flagged).
- **Paul Winters 2024**: grid + elim-results PDFs from `new-sources/Paul Winters - 2024 PDFs/`.
- **Rice 2022**: `new-sources/Rice University Classic - 2022.json` (raw Tabroom).
- **FTN**: opponents without their own result sheet (Jannese Davidson 2022Jan PDB Krishnan/Rashid, Gorlock 2023 Simpson, NPDA Fall 2025 WJC Lepage/Massey, Robert Barbera 2025 Kim/Gurrola, GGO 2024, Great Salt Lake 2024) are taken from the opponent cell. Same-school finals with "?" decisions (Missouri Mule 2021, Sunset Cliffs 2021, Great Salt Lake 2025 semis, GGO 2021) are WALKOVERs. Where both sheets show the same decision (NCFA Spring 2022 R5, PSCFA Fall 2023 R4, PSCFA Spring 2025 R3, Bernacchi 2024 R1), the winner comes from the site record if forced, otherwise UNKNOWN.
- **Same-school prelims** do appear in a few small FTN tournaments (Norene Hockett 2021, Jannese Davidson 2023, Great Salt Lake 2024, Crossman 2025Jan, Sunset Cliffs 2025). They are kept as debates and listed in build_notes.txt.
- **Bracket inference**: a seed-based bracket rebuild was tested on complete Tabroom brackets. It did not reproduce the real pairings (tournaments re-pair or re-seed), so it is **not used**. Missing rounds are generated only when they are forced (two teams left = final, or SpeechWire's bracket-ordered list). Generated rounds are INFERRED or WALKOVER, with no sides or judges.
- Sides: `sides_known = N` when the source does not give sides (byes, generated rounds, some OCR/SpeechWire finals). Those rows list the first team under aff_* for layout only.
- Gaske Memorial 2022.pdf and the duplicate Crossman 2021 / Jannese Davidson 2024 exports are not used (no calendar entry / duplicates).

## Running it from this repo (tools/elo)

```
cd tools/elo
NPTE_NEW_SOURCES=/path/to/new-sources python3 build.py   # ~70 s
```

- Reads `index.html` (via `site_extract.js`, needs `node`), `source_pdfs/`, the
  inputs in `inputs/` (tournament calendar, Tabroom bracket overrides for
  Mile High pt 2 2023 and GGI 2025, Mound High pt 1 2024 posted pairings) and
  the caches in `cache/` (`ftn_live.json` official FTN results, SpeechWire OCR
  output so Tesseract is not needed).
- `NPTE_NEW_SOURCES` is only needed until the Rice 2022/2026, Paul Winters 2024
  and Steve Hunt 2026 sources land in `source_pdfs/` (PR #3).
- Writes `data/elo.json` (read by `h2h.html` and `elo.html`) plus the CSVs here.
  `elo_history.csv` (~6.6 MB, per-debate rating log) is generated but git-ignored.
- `../site_data_fixes_2026_11.py` holds the Nov 2026 corrections to
  `tournamentLogs` that this build's `validation.csv` found.

import pandas as pd
import pdfplumber
import subprocess
import tempfile
import os
import csv
import re
import glob
import shutil
import sys
import difflib
from collections import defaultdict

# ============================================================================
# WHY THIS SCRAPER LOOKS DIFFERENT FROM FTN_Scraper.py
#
# SpeechWire PDFs deliberately obfuscate their text: every "character" is
# drawn using a custom Type 3 font where each glyph is a hand-drawn shape
# with an arbitrary internal name (not a real letter). There is no character
# mapping to recover - copy/pasting text out of these PDFs gives garbage on
# purpose. So instead of reading the embedded text (like FTN_Scraper.py
# does), this scraper renders each page to an image and reads it with OCR
# (tesseract), using the PDF's own table borders and bracket connector
# lines - which ARE real vector graphics, not text - to know exactly where
# to crop for clean, reliable OCR reads.
#
# The final output (a DataFrame with the same columns FTN_Scraper.py
# produces: Year, School, Debater names, Prelim Wins/Losses, Advanced,
# Partial Elim, 1st-7th Full Win) is identical, so it drops into the same
# ingest-template / sync_ingest.py pipeline without any changes downstream.
#
# REQUIRES: Tesseract OCR installed separately (it's a program, not a
# Python package). On Windows, get it from:
#   https://github.com/UB-Mannheim/tesseract/wiki
# The default install location is found automatically below. If you
# installed it somewhere else, set TESSERACT_CMD to that exact .exe path.
# ============================================================================

TESSERACT_CMD = "tesseract"  # only edit this if auto-detection below fails

_CANDIDATE_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]


def _resolve_tesseract():
    if shutil.which(TESSERACT_CMD):
        return TESSERACT_CMD
    for path in _CANDIDATE_PATHS:
        if os.path.isfile(path):
            return path
    sys.exit(
        "\nERROR: Could not find Tesseract OCR on this computer.\n"
        "This script needs it installed separately (it's not a Python package).\n\n"
        "On Windows:\n"
        "  1. Go to https://github.com/UB-Mannheim/tesseract/wiki\n"
        "  2. Download and run the 64-bit installer (keep the default install location)\n"
        "  3. Run this script again\n\n"
        "If you installed it somewhere other than the default location, open this\n"
        "script and set TESSERACT_CMD near the top to the full path of tesseract.exe.\n"
    )


TESSERACT_PATH = _resolve_tesseract()

ROUND_NAMES_FROM_FINAL = ["FINALS", "SEMIS", "QUARTERS", "OCTOS", "DOUBLE OCTOS"]
ROUND_PRIORITY = {
    "DOUBLE OCTOS": 1, "OCTOS": 2, "QUARTERS": 3, "SEMIS": 4,
    "BRONZE": 5, "GOLD": 6, "FINALS": 7,
}
FULL_BRACKET_SIZE = {
    "DOUBLE OCTOS": 32, "OCTOS": 16, "QUARTERS": 8, "SEMIS": 4, "BRONZE": 4,
}


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _ocr_text(png_path, psm=6, whitelist=None):
    cmd = [TESSERACT_PATH, png_path, 'stdout', '--psm', str(psm)]
    if whitelist:
        cmd += ['-c', f'tessedit_char_whitelist={whitelist}']
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout.strip()


def _ocr_lines(png_path, psm=6):
    """Runs OCR and groups words back into visual lines using tesseract's
    own line detection (block/par/line numbers), returning (top, text)
    pairs sorted top-to-bottom."""
    out = subprocess.run([TESSERACT_PATH, png_path, 'stdout', '--psm', str(psm), 'tsv'],
                          capture_output=True, text=True)
    reader = csv.DictReader(out.stdout.splitlines(), delimiter='\t')
    rows = [r for r in reader if r['text'].strip()]
    groups = defaultdict(list)

    for r in rows:
        groups[(r['block_num'], r['par_num'], r['line_num'])].append(r)
    lines = []
    for words in groups.values():
        words.sort(key=lambda w: int(w['left']))
        text = ' '.join(w['text'] for w in words)
        top = min(int(w['top']) for w in words)
        lines.append((top, text))
    lines.sort()
    return lines


def _crop_and_ocr_cell(page, bbox, psm=6, pad=2, margin=20, whitelist=None):
    """Crops a table cell, pulling in from its border lines (which otherwise
    confuse OCR) and adding a white margin, then OCRs it as one blob.
    Binarizes first - SpeechWire's zebra-striped gray rows are just light
    enough to confuse tesseract's own thresholding otherwise."""
    x0, top, x1, bottom = bbox
    cropped = page.crop((x0 + pad, top + pad, x1 - pad, bottom - pad))
    im = cropped.to_image(resolution=400)
    from PIL import ImageOps
    gray = im.original.convert('L')
    bw = gray.point(lambda p: 0 if p < 180 else 255, mode='1').convert('L')
    bordered = ImageOps.expand(bw, border=margin, fill='white')
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        path = f.name
    bordered.save(path)
    try:
        return _ocr_text(path, psm=psm, whitelist=whitelist)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Page 1 (or however many pages): the standings table
# ---------------------------------------------------------------------------

def _split_debater_line(names_line):
    """'Brenna Seiersen and Tristan Keene' -> two (first, last) pairs."""
    parts = re.split(r'\s+and\s+', names_line, flags=re.IGNORECASE)
    result = []
    for p in parts[:2]:
        tokens = p.strip().split()
        if not tokens:
            result.append(("", ""))
        elif len(tokens) == 1:
            result.append((tokens[0], ""))
        else:
            result.append((tokens[0], " ".join(tokens[1:])))
    while len(result) < 2:
        result.append(("", ""))
    return result


# A trailing division word SpeechWire sometimes bakes into the school
# parenthetical, e.g. "Competitor (Rice University Senior)" - not part of
# the school's actual name.
_DIVISION_SUFFIX_RE = re.compile(
    r'\s+(Senior|Junior|Novice|Open|Varsity|JV)$', re.IGNORECASE)


def _is_standings_header(page, header_row):
    """Confirms a candidate 6+ column table is the real standings table (its
    first column header OCRs to 'Competitor') and not a same-shaped table
    SpeechWire also renders with 6+ columns, like 'Individual Speakers in
    order' (header 'Speaker'), which lists people but not team records."""
    if not header_row.cells or header_row.cells[0] is None:
        return False
    text = _crop_and_ocr_cell(page, header_row.cells[0], psm=6).strip().lower()
    return text.startswith('competitor')


def _parse_standings_tables(pdf):
    """Finds every genuine standings table across all pages (a big field
    may spill onto a second page) and returns a list of team dicts in
    finish order (which IS the seed order SpeechWire prints them in)."""
    teams = []
    for page in pdf.pages:
        for table in page.find_tables():
            rows = table.rows
            # Only Competitor (col 0) and Record (col 1) are ever read below, so
            # any extra tiebreaker columns SpeechWire adds (e.g. "J Var", a
            # second "Drop H/L") don't matter - just require the table look
            # like a standings table at all, not an exact column count.
            if not rows or len(rows[0].cells) < 6:
                continue
            if not _is_standings_header(page, rows[0]):
                continue
            for row in rows[1:]:  # skip header row
                competitor_bbox = row.cells[0]
                record_bbox = row.cells[1]
                comp_text = _crop_and_ocr_cell(page, competitor_bbox, psm=6)
                rec_text = _crop_and_ocr_cell(page, record_bbox, psm=7,
                                               whitelist='0123456789-')
                if not comp_text.strip():
                    continue
                lines = [l for l in comp_text.splitlines() if l.strip()]
                if len(lines) < 2:
                    continue
                header_line, names_line = lines[0], lines[1]

                m = re.match(r'^(.*?)\s*\((.*?)\)\.?\s*$', header_line.strip())
                if m:
                    code, school = m.group(1).strip(), m.group(2).strip().rstrip('.')
                    school = _DIVISION_SUFFIX_RE.sub('', school).strip()
                else:
                    code, school = header_line.strip(), ""

                (d1_first, d1_last), (d2_first, d2_last) = _split_debater_line(names_line)

                rec_m = re.search(r'(\d+)\s*-\s*(\d+)', rec_text)
                wins, losses = (int(rec_m.group(1)), int(rec_m.group(2))) if rec_m else (0, 0)

                teams.append({
                    "seed": len(teams) + 1,
                    "code": code,
                    "school": school,
                    "d1_first": d1_first, "d1_last": d1_last,
                    "d2_first": d2_first, "d2_last": d2_last,
                    "wins": wins, "losses": losses,
                })
    return teams


# ---------------------------------------------------------------------------
# Bracket page: reconstruct who-beat-whom from the tree diagram
# ---------------------------------------------------------------------------

def _detect_column_bands(page):
    """Bracket connector lines are real vector rects (unlike the text), so
    their x0 positions mark exact column boundaries regardless of bracket
    size. Falls back to None if no bracket is found on this page."""
    xs = sorted(set(round(r['x0']) for r in page.rects))
    # keep only values that are clearly column starts (drop stray outliers
    # within 3pt of another - line segments cluster tightly per column)
    bands = []
    for x in xs:
        if not bands or x - bands[-1] > 20:
            bands.append(x)
    if len(bands) < 2:
        return None
    bands.append(page.width)
    return bands  # e.g. [34, 178, 263, 345, 427, width]


def _ocr_column(page, x0, x1):
    crop = page.crop((max(x0, 0), 0, min(x1, page.width), page.height))
    im = crop.to_image(resolution=300)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        path = f.name
    im.original.save(path)
    try:
        return _ocr_lines(path, psm=6)
    finally:
        os.unlink(path)


def _norm_code(s):
    return re.sub(r'[^A-Z0-9]', '', s.upper())


def _parse_bracket(pdf, teams_by_seed):
    """Returns {seed: [(round_name, won_bool, has_bye_bool), ...]} for every
    seed that appears in the bracket."""
    elim_rounds = defaultdict(list)
    for page in pdf.pages:
        bands = _detect_column_bands(page)
        if not bands:
            continue

        columns = []
        for i in range(len(bands) - 1):
            lines = _ocr_column(page, bands[i], bands[i + 1])
            # keep only lines that look like a bracket entry: start with a
            # seed number, or are "BYE", or match a known team code
            keep = []
            for top, text in lines:
                t = text.strip()
                if re.match(r'^\d+\s', t) or t.upper().startswith('BYE'):
                    keep.append(t)
                elif any(_norm_code(t).startswith(_norm_code(c))
                         for c in [tm['code'] for tm in teams_by_seed.values()]):
                    keep.append(t)
            columns.append(keep)

        if len(columns) < 2 or not columns[0]:
            continue  # not actually a bracket page

        # column 0: alternating real-seed / bye slots -> resolve to seed numbers
        slot_seed = []   # None for BYE
        for entry in columns[0]:
            if entry.upper().startswith('BYE'):
                slot_seed.append(None)
            else:
                m = re.match(r'^(\d+)', entry)
                slot_seed.append(int(m.group(1)) if m else None)

        # slot -> normalized code, used to match against later columns
        slot_code = [
            _norm_code(teams_by_seed[s]['code']) if s is not None else None
            for s in slot_seed
        ]

        prev_labels = slot_code            # codes reaching the START of round 1
        prev_seed_for_slot = slot_seed      # which seed each label belongs to
        n_rounds = len(columns) - 1

        for r in range(n_rounds):
            round_name = ROUND_NAMES_FROM_FINAL[n_rounds - 1 - r] if n_rounds - 1 - r < len(ROUND_NAMES_FROM_FINAL) else f"ROUND {r+1}"
            next_col = [_norm_code(t) for t in columns[r + 1]]
            new_prev_labels = []
            new_prev_seed = []
            for i in range(0, len(prev_labels) - 1, 2):
                a_code, b_code = prev_labels[i], prev_labels[i + 1]
                a_seed, b_seed = prev_seed_for_slot[i], prev_seed_for_slot[i + 1]
                winner_idx = len(new_prev_labels)
                winner_code = next_col[winner_idx] if winner_idx < len(next_col) else None

                for code, seed, opp_seed in [(a_code, a_seed, b_seed), (b_code, b_seed, a_seed)]:
                    if seed is None:
                        continue
                    has_bye = opp_seed is None
                    if code is None:
                        continue
                    won = (winner_code is not None and winner_code.startswith(code)) or has_bye
                    elim_rounds[seed].append((round_name, bool(won), has_bye))

                # whichever of the pair matches the next column's label advances
                if a_code and winner_code and winner_code.startswith(a_code):
                    new_prev_labels.append(a_code); new_prev_seed.append(a_seed)
                elif b_code and winner_code and winner_code.startswith(b_code):
                    new_prev_labels.append(b_code); new_prev_seed.append(b_seed)
                elif a_seed is not None and b_seed is None:
                    new_prev_labels.append(a_code); new_prev_seed.append(a_seed)
                elif b_seed is not None and a_seed is None:
                    new_prev_labels.append(b_code); new_prev_seed.append(b_seed)
                else:
                    new_prev_labels.append(winner_code); new_prev_seed.append(None)

            prev_labels, prev_seed_for_slot = new_prev_labels, new_prev_seed

        # only keep a team's LAST recorded round result as a loss; once a
        # team loses, they shouldn't show up "winning" a later phantom round
        for seed, rounds in elim_rounds.items():
            cleaned, eliminated = [], False
            for name, won, bye in rounds:
                if eliminated:
                    break
                cleaned.append((name, won, bye))
                if not won:
                    eliminated = True
            elim_rounds[seed] = cleaned

    return elim_rounds


# ---------------------------------------------------------------------------
# Main entry points (mirrors FTN_Scraper.py)
# ---------------------------------------------------------------------------

def parse_speechwire_pdf(pdf_path, season_year="2025-2026"):
    with pdfplumber.open(pdf_path) as pdf:
        teams = _parse_standings_tables(pdf)
        if not teams:
            raise ValueError(
                "No team standings table found in this PDF (only a "
                "results/standings page with a 'Competitor' + 'Record' "
                "table is supported - an 'Individual Speakers' or other "
                "export won't have team win-loss records to scrape)."
            )
        teams_by_seed = {t['seed']: t for t in teams}
        elim_rounds_by_seed = _parse_bracket(pdf, teams_by_seed)

    advanced_seeds = set(elim_rounds_by_seed.keys())

    # Same "how big was the first real elim round" logic as FTN_Scraper.py
    tournament_first_round, min_priority = None, 99
    for rounds in elim_rounds_by_seed.values():
        for r_name, _, _ in rounds:
            p = ROUND_PRIORITY.get(r_name, 99)
            if p < min_priority:
                min_priority, tournament_first_round = p, r_name

    first_round_total = first_round_byes = 0
    if tournament_first_round:
        for rounds in elim_rounds_by_seed.values():
            matches = [r for r in rounds if r[0] == tournament_first_round]
            if matches:
                first_round_total += 1
                if matches[0][2]:
                    first_round_byes += 1

    partial_val = 0
    if first_round_byes > 0 and tournament_first_round:
        full_team_count = FULL_BRACKET_SIZE.get(tournament_first_round, 8)
        partial_val = round((first_round_total - first_round_byes) / full_team_count, 4)

    col_names = ["1st Full Win", "2nd Full Win", "3rd Full Win", "4th Full Win",
                 "5th Full win", "6th Full win", "7th Full win"]

    records = []
    for t in teams:
        rounds = elim_rounds_by_seed.get(t['seed'], [])
        full_wins = []
        source_rounds = rounds[1:] if partial_val > 0 else rounds
        for _, won, _ in source_rounds:
            if won:
                full_wins.append(True)

        # Partial Elim is credit for winning the tournament's under-strength
        # first round - it belongs only to the team(s) who actually won that
        # specific round (whether by a real win or a bye), not to everyone
        # who merely played in it or advanced further afterward.
        won_first_round = bool(rounds) and rounds[0][0] == tournament_first_round and rounds[0][1]
        team_partial_elim = partial_val if won_first_round else 0

        record = {
            "Year": season_year,
            "School": t['school'],
            "Debater 1 First Name": t['d1_first'],
            "Debater 1 Last Name": t['d1_last'],
            "Debater 2 First Name": t['d2_first'],
            "Debater 2 Last Name": t['d2_last'],
            "Prelim Wins": t['wins'],
            "Prelim Losses": t['losses'],
            "Advanced": t['seed'] in advanced_seeds,
            "Partial Elim": team_partial_elim,
        }
        for i, col in enumerate(col_names):
            record[col] = i < len(full_wins) and full_wins[i]
        records.append(record)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Alternate SpeechWire export: a "tab grouping" prelim sheet (URL path
# .../tab-grouping-print.php) plus a separate "awards assembly script" PDF
# for elim results, instead of one combined standings+bracket PDF. Unlike
# the format above, this one's embedded text is real (not an obfuscated
# Type 3 font), so neither file needs OCR at all.
# ---------------------------------------------------------------------------

# Teams named under a round heading in the awards script are the ones
# ELIMINATED there (never advanced further) - not the ones who reached it.
# Spelling matches SpeechWire's own script text exactly ("Octafinalists",
# not "Octofinalists") - a mismatch here silently sorts that round last
# instead of first, corrupting every round's win count.
TAB_GROUPING_ROUND_PRIORITY = {
    "Octafinalists": 0, "Quarterfinalists": 1, "Semifinalists": 2, "Finalists": 3,
}
TAB_GROUPING_FULL_SIZE = {
    "Octafinalists": 16, "Quarterfinalists": 8, "Semifinalists": 4, "Finalists": 2,
}


def _recover_split_tab_grouping_row(page_end, bottom_y, page_start, top_y):
    """Recovers a team's header row when it fell into the gap between the
    end of one page's detected table and the start of the next page's -
    seen when an unusually long school name (e.g. "Parliamentary Debate at
    Berkeley") wraps to enough lines that pdfplumber's table detection
    can't reconstruct one coherent row spanning the page break. Crops the
    leftover text above/below the two pages' detected table boundaries and
    parses the team code and win-loss record directly from it (reliable);
    the school name is a best-effort guess from the same text, since it's
    flattened together with neighboring cells' wrapped continuations."""
    crop_end = page_end.crop((0, bottom_y, page_end.width, page_end.height))
    crop_start = page_start.crop((0, 0, page_start.width, top_y))
    lines_end = (crop_end.extract_text() or '').splitlines()
    lines_start = [l for l in (crop_start.extract_text() or '').splitlines()
                   if 'SpeechWire Tournament Services' not in l]

    line1 = lines_end[0] if lines_end else ''
    line2 = lines_end[1] if len(lines_end) > 1 else ''
    line3 = lines_start[0] if lines_start else ''

    m = re.match(r'^(.*?)\s+(?:[LW]\s*-).*?(\d+)-(\d+)\s+(\d+\w\w)\s*$', line1)
    if not m:
        return None
    code = m.group(1).strip()
    wins, losses = int(m.group(2)), int(m.group(3))
    school_guess = re.sub(r'\s+', ' ', (line2 + ' ' + line3).strip())
    return {'code': code, 'school_guess': school_guess, 'wins': wins, 'losses': losses}


def _parse_tab_grouping_round_cell(cell_text):
    """A prelim round cell looks like "L - Rice\\nUniversit GW -\\nAFF\\nWC1
    Alexa\\nGrechishkin" once pdfplumber wraps the opponent's name across
    lines - collapsing newlines to spaces gives "L - Rice Universit GW -
    AFF WC1 Alexa Grechishkin", where the side is reliably the token right
    after the LAST " - " before the judge info starts. Team codes never
    contain a hyphen themselves, so this never ambiguously matches the
    wrong "-". Returns (result, side) as ('W'|'L'|None, 'Aff'|'Neg'|None);
    either can be None for a cell this doesn't recognize (e.g. a bye)."""
    normalized = ' '.join((cell_text or '').split())
    m = re.match(r'^([WL])\s*-\s*.*?-\s*(AFF|Neg|GOV|OPP)\b', normalized, re.IGNORECASE)
    if not m:
        return None, None
    result = m.group(1).upper()
    side_word = m.group(2).upper()
    side = 'Aff' if side_word in ('AFF', 'GOV') else 'Neg'
    return result, side


def parse_tab_grouping_pdf(pdf_path):
    """Parses a SpeechWire 'tab grouping' print sheet into one record per
    team, in the sheet's own finish/seed order: {code, school, d1, d2,
    wins, losses, aff_wins, aff_losses, neg_wins, neg_losses}. Each team
    occupies 3 table rows (a header row giving code/school/record plus one
    round-result cell per prelim round, then one row per debater's
    individual speaker scores) - real embedded text, no OCR needed.

    The Aff/Neg tally only covers these PRELIM rounds - the separate
    awards-script PDF (elim rounds) names only who was eliminated where,
    never which side they were on, so elim rounds can't contribute to the
    split with this source."""
    all_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages
        page_tables = [p.find_tables() for p in pages]
        for i, page in enumerate(pages):
            if not page_tables[i]:
                continue
            page_rows = page_tables[i][0].extract()
            if page_rows and page_rows[0] and (page_rows[0][0] or '').strip() == 'Competitor':
                page_rows = page_rows[1:]
            # If this page doesn't open on a header row (code\nschool) and
            # the previous page had a table, a row likely fell into the
            # page-break gap - try to recover it before continuing.
            if (page_rows and page_rows[0][0] and '\n' not in page_rows[0][0]
                    and i > 0 and page_tables[i - 1]):
                prev_table = page_tables[i - 1][0]
                recovered = _recover_split_tab_grouping_row(
                    pages[i - 1], prev_table.rows[-1].bbox[3], page, page_tables[i][0].rows[0].bbox[1]
                )
                if recovered:
                    all_rows.append(('__RECOVERED__', recovered))
            all_rows.extend(page_rows)

    teams = []
    i = 0
    while i < len(all_rows):
        row = all_rows[i]
        if isinstance(row, tuple) and row[0] == '__RECOVERED__':
            rec = row[1]
            school = rec['school_guess']
            if school.lower().startswith('parliamentary debate'):
                school = 'Parliamentary Debate at Berkeley'
            else:
                print(f"  [WARNING] Recovered a team header split across a page break "
                      f"(code '{rec['code']}') - school name is a best-effort guess "
                      f"('{school}') and should be double-checked.")
            d1 = (all_rows[i + 1][0] or '').strip()
            d2 = (all_rows[i + 2][0] or '').strip()
            # The page-break recovery path only reconstructs the code/
            # school/record from cropped leftover text, not the individual
            # round cells - Aff/Neg can't be determined for this team.
            teams.append({'code': rec['code'], 'school': school,
                          'd1': d1, 'd2': d2, 'wins': rec['wins'], 'losses': rec['losses'],
                          'aff_wins': None, 'aff_losses': None, 'neg_wins': None, 'neg_losses': None})
            i += 3
            continue

        c0 = row[0] or ''
        if '\n' not in c0:
            raise ValueError(
                f"Expected a team header row (Code\\nSchool) at position {i}, got: {c0!r}. "
                "This PDF's layout may not match what this parser expects - check manually."
            )
        code, school = c0.split('\n', 1)
        code, school = code.strip(), re.sub(r'\s+', ' ', school).strip().rstrip('.')
        if school.lower().startswith('parliamentary debate'):
            school = 'Parliamentary Debate at Berkeley'

        record_cell = row[6] or ''
        m = re.match(r'(\d+)-(\d+)', record_cell.strip())
        if not m:
            raise ValueError(f"Could not find a W-L record in row {i}'s record cell: {record_cell!r}")
        wins, losses = int(m.group(1)), int(m.group(2))

        aff_wins = aff_losses = neg_wins = neg_losses = 0
        for round_cell in row[1:6]:
            result, side = _parse_tab_grouping_round_cell(round_cell)
            if result is None or side is None:
                continue
            if side == 'Aff':
                aff_wins += result == 'W'
                aff_losses += result == 'L'
            else:
                neg_wins += result == 'W'
                neg_losses += result == 'L'

        d1 = (all_rows[i + 1][0] or '').strip()
        d2 = (all_rows[i + 2][0] or '').strip()
        if '\n' in d1 or '\n' in d2:
            raise ValueError(f"Expected plain debater-name rows after row {i}, got {d1!r} / {d2!r}")

        teams.append({'code': code, 'school': school, 'd1': d1, 'd2': d2, 'wins': wins, 'losses': losses,
                      'aff_wins': aff_wins, 'aff_losses': aff_losses, 'neg_wins': neg_wins, 'neg_losses': neg_losses})
        i += 3

    return teams


def parse_awards_script(pdf_path):
    """Parses a SpeechWire 'awards assembly script' PDF into
    {frozenset({d1, d2}): {'school': ..., 'eliminated_in': round_name,
    'place': 1 | 2 | None}}. Teams named under a round heading are the ones
    ELIMINATED in that round; the Final section instead gives an explicit
    1st/2nd place for the two finalists (place=1 means they won it all)."""
    with pdfplumber.open(pdf_path) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)

    results = {}
    current_round = None
    for line in (l.strip() for l in text.splitlines() if l.strip()):
        m_round = re.match(r'The (\w+) in .+ were\.\.\.', line)
        if m_round:
            current_round = m_round.group(1)
            continue
        if line.startswith('In the Final round'):
            current_round = 'Finalists'
            continue
        m_place = re.match(r'In (1st|2nd) place, from (.+?), (.+?) and (.+?)\.$', line)
        if m_place:
            place = 1 if m_place.group(1) == '1st' else 2
            school, d1, d2 = (g.strip() for g in m_place.groups()[1:])
            results[frozenset([d1, d2])] = {'school': school, 'eliminated_in': current_round, 'place': place}
            continue
        m_from = re.match(r'From (.+?), (.+?) and (.+?)\.$', line)
        if m_from and current_round:
            school, d1, d2 = (g.strip() for g in m_from.groups())
            results[frozenset([d1, d2])] = {'school': school, 'eliminated_in': current_round, 'place': None}
            continue
    return results


def _find_prelim_header_line(lines):
    """Index of the "Competitor Round 1 ... Totals Results" column-header
    line, or None. Looked up by content, not position, since how many lines
    precede it (tournament name only, or a timestamp + tournament name)
    varies by export."""
    for i, line in enumerate(lines):
        if line.startswith('Competitor') and 'Results' in line:
            return i
    return None


def _page_section(page):
    """Classifies one page of a "complete" multi-event SpeechWire tournament
    report (every event in the tournament printed to one PDF, real text, no
    OCR needed) by its own title lines: (division_name, section_type), where
    section_type is one of 'prelim_table', 'individual_speakers',
    'elim_results', 'elim_bracket', or None if the page doesn't look like a
    per-division report page at all (e.g. the school-codes cover page).

    The division name always sits on the line right before whichever marker
    identifies the page - but how many lines come before THAT (just the
    tournament name, or a timestamp line plus the tournament name) differs
    between exports, so this searches by content instead of assuming a
    fixed line index."""
    text = page.extract_text() or ''
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for marker, kind in (
        ('Individual speakers in order', 'individual_speakers'),
        ('Competitors in order', 'individual_speakers'),
        ('Elimination round results', 'elim_results'),
        ('Elimination round bracket', 'elim_bracket'),
    ):
        if marker in lines:
            i = lines.index(marker)
            return (lines[i - 1] if i > 0 else None), kind
    i = _find_prelim_header_line(lines)
    if i is not None:
        return (lines[i - 1] if i > 0 else None), 'prelim_table'
    return None, None


def _parse_complete_doc_prelim_pages(pages):
    """Parses the "Competitor | Round 1...N | Totals | Results" team table
    from a list of already-selected pdfplumber Page objects (all belonging
    to one division) into per-team Aff/Neg tallies.

    pdfplumber's table-geometry detection (find_tables) doesn't work on this
    layout - it collapses the whole page into one or two giant cells, since
    this report style apparently doesn't draw the same column-separator
    lines the "tab grouping" single-division PDFs do. Reading the page as
    plain text instead, each team is a fixed shape regardless of its exact
    line count (which varies: a long opponent name can wrap the header onto
    an extra line): one or more "header" lines giving [W/L] per round
    (opponent text interleaved - ignored, not needed) followed by one or
    more "side" lines giving [Aff/Neg/BYE] per round (also carrying the
    placement ordinal), then exactly two "score" lines (one per debater -
    the only lines matching a bare decimal score, e.g. "29.00 (2.00)",
    which no header/side/judge line ever contains), unambiguously marking
    where one team's data ends and the next begins.

    Round order is recovered by reading the [W/L] tokens and the
    [Aff/Neg/BYE] tokens as two separate ordered streams and zipping them -
    a BYE consumes a position in the side stream but has no corresponding
    [W/L] token at all (no opponent to report), so it's paired with None
    instead of advancing the win/loss stream. Validated against this
    format's own already-known correct records (e.g. a team showing "4-1"
    whose recovered round-by-round sequence sums to 4 wins/byes and 1 loss)
    before being trusted for every historical tournament this is used on.

    pdfplumber's reading order can scramble into individual interleaved
    letters (e.g. "L - R R ic S e - U N n e iv g ersit BYE") for a team
    whose SCHOOL name wraps across its own header line - seen only for
    schools with long names ("University of Texas - Tyler", "University of
    the Pacific"), not a general problem with this parser. Rather than risk
    silently extracting wrong win/loss or side data from garbled text, each
    team's token counts are checked against the page's own declared round
    count (from the "Round 1 Round 2 ... Round N" column header) and
    against each other (every non-BYE side token must pair with a real W/L
    token); a mismatch means this team's data is unusable here and its
    tally comes back as None rather than a partial or wrong one."""
    teams = []
    expected_rounds = None
    for page in pages:
        text = page.extract_text() or ''
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        header_idx = _find_prelim_header_line(lines)
        if header_idx is not None:
            expected_rounds = len(re.findall(r'\bRound\s+\d+\b', lines[header_idx]))
            body = lines[header_idx + 1:]
        else:
            # A page-break continuation: the table carries on with no
            # repeated title or column header, so the whole page is body -
            # expected_rounds comes from whichever earlier page in this same
            # call last had a real header.
            body = lines
        body = [l for l in body if not l.startswith('This tournament')
                and not l.startswith('©') and not l.startswith('https://')]

        # A debater's own score line - detected by shape (2+ decimal scores,
        # ends in a placement ordinal) rather than requiring the "(rank)"
        # parenthetical some exports omit per-score. Excludes AFF/Neg/BYE
        # so it never matches the side line, which also ends in an ordinal.
        def _is_score_line(l):
            if re.search(r'\bAFF\b|\bNeg\b|\bBYE\b', l):
                return False
            if not re.search(r'\d+(st|nd|rd|th)$', l):
                return False
            return len(re.findall(r'\d+\.\d{2}', l)) >= 2
        score_idxs = [i for i, l in enumerate(body) if _is_score_line(l)]
        start = 0
        for k in range(0, len(score_idxs) - 1, 2):
            si1, si2 = score_idxs[k], score_idxs[k + 1]
            header_text = ' '.join(body[start:si1])
            wl_tokens = re.findall(r'\b([WL])(?=\s*-)', header_text)
            side_tokens = re.findall(r'\b(AFF|Neg|BYE)\b', header_text)

            m1 = re.match(r'^(.+?)\s+\d', body[si1])
            m2 = re.match(r'^(.+?)\s+\d', body[si2])
            start = si2 + 1
            if not m1 or not m2:
                continue
            d1, d2 = m1.group(1).strip(), m2.group(1).strip()

            non_bye = sum(1 for t in side_tokens if t != 'BYE')
            corrupted = (len(side_tokens) != expected_rounds) or (non_bye != len(wl_tokens))

            aff_wins = aff_losses = neg_wins = neg_losses = None
            if not corrupted:
                aff_wins = aff_losses = neg_wins = neg_losses = 0
                wl_iter = iter(wl_tokens)
                for side_tok in side_tokens:
                    if side_tok == 'BYE':
                        continue
                    result = next(wl_iter)
                    side = 'Aff' if side_tok == 'AFF' else 'Neg'
                    if side == 'Aff':
                        aff_wins += result == 'W'
                        aff_losses += result == 'L'
                    else:
                        neg_wins += result == 'W'
                        neg_losses += result == 'L'

            teams.append({'school': '', 'd1': d1, 'd2': d2,
                          'aff_wins': aff_wins, 'aff_losses': aff_losses,
                          'neg_wins': neg_wins, 'neg_losses': neg_losses})

    return teams


def _parse_complete_doc_elim_sides(text, teams):
    """Tallies elim-round Aff/Neg from a "complete doc"'s "Elimination round
    results" page text, e.g. "5 San Joaquin De HT Ashan Herath and Joshua
    Turnbull (Neg) def. 4 Diablo Valley BF Tawny Fischer and Teo Buegeleisen
    (AFF) 3-0" - unlike the "awards assembly script" format, this one DOES
    carry side for elim rounds. Rather than fully parsing the line's school/
    seed structure (ambiguous, since both share the literal word "and"),
    this looks up each known team by searching for both debaters' names
    together and reading the side out of the parenthetical right after -
    far more robust against the format's own ambiguity. A BYE line is
    skipped (not a contested round on either side, same reasoning as
    elsewhere). teams: list of (d1, d2) tuples from the prelim parse.
    Returns {(d1, d2): [aff_w, aff_l, neg_w, neg_l]}."""
    tally = {t: [0, 0, 0, 0] for t in teams}
    for line in text.splitlines():
        line = line.strip()
        if not line or 'BYE' in line or ' def.' not in line:
            continue
        def_idx = line.find(' def.')
        for (d1, d2) in teams:
            if d1 not in line or d2 not in line:
                continue
            d1_pos, d2_pos = line.find(d1), line.find(d2)
            name_end = max(d1_pos + len(d1), d2_pos + len(d2))
            m = re.search(r'\((Neg|AFF)\)', line[name_end:name_end + 15])
            if not m:
                continue
            side = 'Aff' if m.group(1) == 'AFF' else 'Neg'
            won = min(d1_pos, d2_pos) < def_idx
            if side == 'Aff':
                tally[(d1, d2)][0 if won else 1] += 1
            else:
                tally[(d1, d2)][2 if won else 3] += 1
    return tally


def _ocr_page_text(page, resolution=300):
    """Whole-page OCR, used only for the "complete doc" format's obfuscated-
    font exports - real text extraction returns (cid:N) garbage on these,
    so section titles and elim-results prose need OCR same as the table
    cells do."""
    im = page.to_image(resolution=resolution)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        path = f.name
    im.save(path)
    try:
        return _ocr_text(path, psm=6)
    finally:
        os.unlink(path)


def _page_section_ocr(page):
    """Same idea as _page_section, but for a page whose embedded text is
    obfuscated (OCR needed) rather than real."""
    text = _ocr_page_text(page)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for marker, kind in (
        ('Individual speakers in order', 'individual_speakers'),
        ('Competitors in order', 'individual_speakers'),
        ('Elimination round results', 'elim_results'),
        ('Elimination round bracket', 'elim_bracket'),
    ):
        for i, line in enumerate(lines):
            if marker.lower() in line.lower():
                return (lines[i - 1] if i > 0 else None), kind
    # A prelim table page has no such marker - any page with a real table
    # on it (OCR title lines aside) counts as one. A genuine title line
    # never contains a digit and is reasonably short; a page-break
    # continuation has no title at all, so its first OCR'd lines are just
    # more table content (round data, scores) - checked for here so a
    # continuation page comes back (None, None) and gets its division
    # filled in from the preceding page instead of a garbled fake one.
    if page.find_tables():
        candidate = lines[1] if len(lines) > 1 else (lines[0] if lines else None)
        if candidate and len(candidate) < 60 and not re.search(r'\d', candidate):
            return candidate, 'prelim_table'
        return None, None
    return None, None


def _real_table_columns(row):
    """(name_idx, [round_idxs], totals_idx, result_idx) from a table row's
    real (non-None-bbox) cells - some exports pad the table with a blank
    border cell on each side, some don't, so column count/position isn't
    fixed; what's constant is the shape (one wide name column, several
    equal-ish-width round columns, then Totals and Result). Returns None
    if the row doesn't have enough real cells to make sense of."""
    real = [i for i, c in enumerate(row.cells) if c is not None]
    if len(real) < 4:
        return None
    return real[0], real[1:-2], real[-2], real[-1]


def _name_similarity(a, b):
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _best_team_match(d1_ocr, d2_ocr, candidates):
    """Identifies a team by fuzzy-matching its two OCR'd debater names
    against a small list of candidate (school, d1, d2) tuples already
    known for this tournament from the live dataset - a per-name pairwise
    comparison (checking both possible pairings, since OCR'd row order
    doesn't necessarily match the dataset's Debater 1/2 order), which is
    far more discriminating than matching a combined text blob: two
    different teams from the same school share most of a blob match's
    content (the school name) but share almost none of a per-name match.
    Returns (candidate, score) for the best match, or (None, 0) if
    d1_ocr/d2_ocr are missing."""
    if not candidates or not d1_ocr or not d2_ocr:
        return None, 0
    best, best_score = None, 0
    for cand in candidates:
        _, d1, d2 = cand
        score = max(
            (_name_similarity(d1_ocr, d1) + _name_similarity(d2_ocr, d2)) / 2,
            (_name_similarity(d1_ocr, d2) + _name_similarity(d2_ocr, d1)) / 2,
        )
        if score > best_score:
            best, best_score = cand, score
    return best, best_score


def _parse_complete_doc_prelim_pages_ocr(pages, known_teams):
    """OCR equivalent of _parse_complete_doc_prelim_pages, for the
    obfuscated-font "complete doc" exports. These DO draw real table/cell
    borders (unlike the readable-text exports, where pdfplumber's table
    detection collapses the page into one blob), so each round is read as
    its own cell with _crop_and_ocr_cell + the same
    _parse_tab_grouping_round_cell regex already validated on real text.

    Row grouping is noisy - some exports insert near-zero-height spacer
    rows between a team's real rows, which OCR to garbage - so rows are
    classified by content instead of position: a row whose round cells
    contain W/L-dash-side or "BYE" patterns starts a new team (its own
    code+school text is read too, but only as a sanity check - OCR on a
    short, cramped header cell is the least reliable text on the page);
    a row that isn't a header is read as a debater name instead (reliably
    OCR'd, one clean name per cell) and attached to whichever team is
    currently open, up to two per team. Team identity comes from fuzzy-
    matching those two debater names against the known roster for this
    tournament (known_teams) - far more discriminating than matching the
    header's code+school text alone, since two different teams from the
    same school share almost nothing in a per-name comparison.

    known_teams: list of (school, d1, d2) from the tournament's existing
    tournamentLogs rows."""
    teams = []
    for page in pages:
        tables = page.find_tables()
        if not tables:
            continue
        rows = tables[0].rows
        if len(rows) < 2:
            continue

        current = None
        for row in rows[1:]:
            cols = _real_table_columns(row)
            if cols is None:
                continue
            name_idx, round_idxs, totals_idx, result_idx = cols
            name_bbox = row.cells[name_idx]
            height = name_bbox[3] - name_bbox[1]
            if height > 100:
                continue  # a giant border-column artifact, not a real row

            round_texts = [
                _crop_and_ocr_cell(page, row.cells[i], psm=6) if row.cells[i] else ''
                for i in round_idxs
            ]
            pairs = []  # (result, side) per round, or ('BYE'|'FORFEIT', None)
            for t in round_texts:
                result, side = _parse_tab_grouping_round_cell(t)
                if result is not None and side is not None:
                    pairs.append((result, side))
                elif 'bye' in t.lower():
                    pairs.append(('BYE', None))
                elif 'forfeit' in t.lower():
                    # No side to report for a forfeited round (no debate
                    # happened), but it's not missing/corrupted data either -
                    # same treatment as a bye: skipped in the Aff/Neg tally,
                    # doesn't block the team's other rounds from counting.
                    pairs.append(('FORFEIT', None))
                else:
                    pairs.append((None, None))

            is_header = any(r in ('BYE', 'FORFEIT') or (r is not None and s is not None) for r, s in pairs)
            if is_header:
                if current:
                    teams.append(current)
                current = {'debaters': [], 'pairs': pairs, 'expected_rounds': len(round_idxs)}
                continue

            if current is None or len(current['debaters']) >= 2:
                continue  # noise row before any header, or a 3rd+ stray row
            name_text = _crop_and_ocr_cell(page, name_bbox, psm=6)
            name_text = re.sub(r'\s+', ' ', name_text).strip()
            # A real debater name OCRs as 2+ capitalized words - excludes a
            # spacer/divider row's OCR garbage (fragments like "r ol" or
            # "An An" from a thin gray gridline), which this format can
            # insert between a team's real rows at an arbitrarily small
            # height, so height alone can't be used to skip those rows.
            if re.match(r"^[A-Z][a-zA-Z'.\-]*(\s+[A-Z][a-zA-Z'.\-]*)+$", name_text):
                current['debaters'].append(name_text)
        if current:
            teams.append(current)

    MATCH_THRESHOLD = 0.6
    results = []
    used_candidates = set()
    for t in teams:
        d1_ocr, d2_ocr = (t['debaters'] + ['', ''])[:2]
        matched, score = _best_team_match(d1_ocr, d2_ocr, known_teams)
        # A candidate already claimed by an earlier, better-scoring team in
        # this same document can't be this team too - two different OCR'd
        # blocks matching the same known team means at least one is wrong,
        # so neither is trusted.
        ambiguous = matched is not None and matched in used_candidates
        corrupted = (
            len(t['debaters']) != 2
            or any(r is None for r, s in t['pairs'])
            or matched is None
            or score < MATCH_THRESHOLD
            or ambiguous
        )
        if matched is not None and not ambiguous:
            used_candidates.add(matched)

        aff_wins = aff_losses = neg_wins = neg_losses = None
        if not corrupted:
            aff_wins = aff_losses = neg_wins = neg_losses = 0
            for result, side in t['pairs']:
                if result in ('BYE', 'FORFEIT'):
                    continue
                if side == 'Aff':
                    aff_wins += result == 'W'
                    aff_losses += result == 'L'
                else:
                    neg_wins += result == 'W'
                    neg_losses += result == 'L'
        school, d1, d2 = matched if matched else ('', '', '')
        results.append({'school': school, 'd1': d1, 'd2': d2,
                        'ocr_debaters': t['debaters'], 'match_score': score,
                        'aff_wins': aff_wins, 'aff_losses': aff_losses,
                        'neg_wins': neg_wins, 'neg_losses': neg_losses})
    return results


def parse_complete_speechwire_doc_ocr(pdf_path, known_teams,
                                       division_names=('Parli Novice Division', 'Parli Open Division')):
    """OCR counterpart to parse_complete_speechwire_doc, for a "complete
    doc" export using SpeechWire's obfuscated Type 3 font (real text
    extraction returns (cid:N) garbage). Same output shape and same
    side-data-only scope (doesn't recompute Prelim Wins/Losses, Advanced,
    etc. - those are already correct from this tournament's original
    ingest). known_teams: list of (school, d1, d2) tuples from the
    tournament's existing tournamentLogs rows, used to identify each OCR'd
    team by fuzzy name match rather than trusting OCR'd names outright."""
    with pdfplumber.open(pdf_path) as pdf:
        sections = [_page_section_ocr(p) for p in pdf.pages]
        for i in range(1, len(sections)):
            if sections[i] == (None, None):
                sections[i] = sections[i - 1]

        records = []
        for division in division_names:
            prelim_pages = [pdf.pages[i] for i, (d, k) in enumerate(sections)
                             if d == division and k == 'prelim_table']
            elim_pages = [pdf.pages[i] for i, (d, k) in enumerate(sections)
                          if d == division and k == 'elim_results']
            if not prelim_pages:
                continue

            teams = _parse_complete_doc_prelim_pages_ocr(prelim_pages, known_teams)
            elim_text = '\n'.join(_ocr_page_text(p) for p in elim_pages)
            elim_sides = _parse_complete_doc_elim_sides(elim_text, [(t['d1'], t['d2']) for t in teams if t['d1']])

            for t in teams:
                if t['aff_wins'] is None:
                    records.append({'division': division, 'school': t['school'], 'd1': t['d1'], 'd2': t['d2'],
                                    'ocr_debaters': t['ocr_debaters'], 'match_score': t['match_score'],
                                    'aff_wins': None, 'aff_losses': None, 'neg_wins': None, 'neg_losses': None})
                    continue
                ew, el, nw, nl = elim_sides.get((t['d1'], t['d2']), [0, 0, 0, 0])
                records.append({
                    'division': division, 'school': t['school'], 'd1': t['d1'], 'd2': t['d2'],
                    'ocr_debaters': t['ocr_debaters'], 'match_score': t['match_score'],
                    'aff_wins': t['aff_wins'] + ew, 'aff_losses': t['aff_losses'] + el,
                    'neg_wins': t['neg_wins'] + nw, 'neg_losses': t['neg_losses'] + nl,
                })
    return records


def parse_complete_speechwire_doc(pdf_path, division_names=('Parli Novice Division', 'Parli Open Division')):
    """Parses a "complete" multi-event SpeechWire tournament report (every
    event printed into one PDF - IPDA, LD, individual speech events, AND
    Parli - with real embedded text, no OCR needed) for just the named Parli
    division(s)' Aff/Neg data, prelim and elim combined. Unlike the other
    SpeechWire formats, this one's elim results DO carry side, so nothing is
    left out.

    This is a side-data-only parse: it does NOT recompute Prelim Wins/
    Losses, Advanced, Partial Elim, or Elim Wins/Losses - those come from
    this tournament's original ingest (built from a different, standings-
    only export) and are already correct, so this only returns
    {school, d1, d2, aff_wins, aff_losses, neg_wins, neg_losses} per team,
    meant to be matched against the existing dataset by name rather than
    merged as new rows."""
    with pdfplumber.open(pdf_path) as pdf:
        sections = [_page_section(p) for p in pdf.pages]
        # A page whose table/section continues from the previous page (no
        # repeated title after a page break) classifies as (None, None) -
        # attribute it to whatever section immediately precedes it, since a
        # genuinely new section is never missing its own title.
        for i in range(1, len(sections)):
            if sections[i] == (None, None):
                sections[i] = sections[i - 1]
        records = []
        for division in division_names:
            prelim_pages = [pdf.pages[i] for i, (d, t) in enumerate(sections)
                             if d == division and t == 'prelim_table']
            elim_pages = [pdf.pages[i] for i, (d, t) in enumerate(sections)
                          if d == division and t == 'elim_results']
            if not prelim_pages:
                continue

            teams = _parse_complete_doc_prelim_pages(prelim_pages)
            elim_text = '\n'.join(p.extract_text() or '' for p in elim_pages)
            elim_sides = _parse_complete_doc_elim_sides(elim_text, [(t['d1'], t['d2']) for t in teams])

            for t in teams:
                if t['aff_wins'] is None:
                    # Prelim side data was unrecoverable (garbled text) for
                    # this team - don't layer elim data on top of an already
                    # unusable prelim tally.
                    records.append({
                        'division': division, 'school': t['school'], 'd1': t['d1'], 'd2': t['d2'],
                        'aff_wins': None, 'aff_losses': None, 'neg_wins': None, 'neg_losses': None,
                    })
                    continue
                ew, el, nw, nl = elim_sides.get((t['d1'], t['d2']), [0, 0, 0, 0])
                records.append({
                    'division': division, 'school': t['school'], 'd1': t['d1'], 'd2': t['d2'],
                    'aff_wins': t['aff_wins'] + ew, 'aff_losses': t['aff_losses'] + el,
                    'neg_wins': t['neg_wins'] + nw, 'neg_losses': t['neg_losses'] + nl,
                })
    return records


def parse_speechwire_tab_grouping_tournament(prelims_path, outs_path, season_year="2025-2026"):
    """Combines a 'tab grouping' prelims sheet and its matching 'awards
    assembly script' into the same row shape the other scrapers produce.
    The earliest round named in the awards script is treated as a partial
    first round (same meaning as elsewhere: an under-strength bracket round,
    credited via Partial Elim rather than a numbered Full Win) whenever
    fewer teams entered it than a full bracket at that size would hold;
    its strength is derived from how many teams were eliminated in it
    (each elimination there implies one real debate, i.e. two entrants),
    matching how FTN_Scraper.py sizes a partial round."""
    teams = parse_tab_grouping_pdf(prelims_path)
    elim = parse_awards_script(outs_path)

    rounds_present = sorted({v['eliminated_in'] for v in elim.values()} | {'Finalists'},
                             key=lambda r: TAB_GROUPING_ROUND_PRIORITY.get(r, 99))
    first_round = rounds_present[0] if rounds_present else None
    full_size = TAB_GROUPING_FULL_SIZE.get(first_round, 0)
    entrants_total = len(elim)
    first_round_eliminated = sum(1 for v in elim.values() if v['eliminated_in'] == first_round)
    is_partial = bool(full_size) and entrants_total < full_size
    partial_fraction = round(2 * first_round_eliminated / full_size, 4) if is_partial else 0

    col_names = ["1st Full Win", "2nd Full Win", "3rd Full Win", "4th Full Win",
                 "5th Full win", "6th Full win", "7th Full win"]
    records = []
    for t in teams:
        info = elim.get(frozenset([t['d1'], t['d2']]))
        advanced = info is not None
        partial_elim = 0
        full_wins = [False] * 7

        if advanced:
            elim_idx = len(rounds_present) if info['place'] == 1 else rounds_present.index(info['eliminated_in'])
            if is_partial:
                partial_elim = partial_fraction if elim_idx > 0 else 0
                full_rounds_won = max(0, elim_idx - 1)
            else:
                full_rounds_won = elim_idx
            for fi in range(min(full_rounds_won, 7)):
                full_wins[fi] = True

        d1_parts, d2_parts = t['d1'].split(), t['d2'].split()
        records.append({
            "Year": season_year, "School": t['school'],
            "Debater 1 First Name": d1_parts[0] if d1_parts else '',
            "Debater 1 Last Name": ' '.join(d1_parts[1:]) if len(d1_parts) > 1 else '',
            "Debater 2 First Name": d2_parts[0] if d2_parts else '',
            "Debater 2 Last Name": ' '.join(d2_parts[1:]) if len(d2_parts) > 1 else '',
            "Prelim Wins": t['wins'], "Prelim Losses": t['losses'],
            "Advanced": advanced, "Partial Elim": partial_elim,
            **{col_names[fi]: full_wins[fi] for fi in range(7)},
            "Aff Wins": t['aff_wins'], "Aff Losses": t['aff_losses'],
            "Neg Wins": t['neg_wins'], "Neg Losses": t['neg_losses'],
        })

    column_order = ["Year", "School", "Debater 1 First Name", "Debater 1 Last Name",
                     "Debater 2 First Name", "Debater 2 Last Name", "Prelim Wins", "Prelim Losses",
                     "Advanced", "Partial Elim"] + col_names + [
                     "Aff Wins", "Aff Losses", "Neg Wins", "Neg Losses"]
    return pd.DataFrame(records)[column_order]


def process_all_pdfs_to_multitab_excel(season_year="2025-2026"):
    pdf_files = glob.glob("*.pdf")
    if not pdf_files:
        print("Error: No PDF files found in this folder!")
        return

    output_excel = "SpeechWire_Tournament_Tabs.xlsx"
    results = {}
    failed = []
    for pdf_path in pdf_files:
        sheet_name = os.path.splitext(os.path.basename(pdf_path))[0][:31]
        print(f"Scraping '{pdf_path}' -> writing to Excel sheet tab '{sheet_name}'...")
        try:
            results[sheet_name] = parse_speechwire_pdf(pdf_path, season_year)
        except Exception as e:
            print(f"  FAILED on '{pdf_path}': {e}")
            failed.append(pdf_path)

    if not results:
        print("\nNothing scraped successfully - no Excel file was written.")
        return

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        for sheet_name, df in results.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"\nSuccess! Multi-tab workbook saved to: {os.path.abspath(output_excel)}")
    if failed:
        print(f"({len(failed)} file(s) failed and were skipped: {', '.join(failed)})")


if __name__ == "__main__":
    process_all_pdfs_to_multitab_excel("2025-2026")
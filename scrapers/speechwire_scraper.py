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


def _parse_standings_tables(pdf):
    """Finds every 6-column standings table across all pages (a big field
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
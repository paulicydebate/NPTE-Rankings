"""One-off corrections to tournamentLogs in index.html (Nov 2026), verified
against official FTN sheets / the Tabroom API by tools/elo (validation.csv).
Idempotent: re-running makes no further changes.
  python3 tools/site_data_fixes_2026_11.py [validation.csv]
"""
import csv, json, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / 'index.html'
VAL = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'tools/elo/validation.csv'
PAT = re.compile(r'(const tournamentLogs = )(\[.*?\])(;\s*\n\s*let summaryData)', re.S)
FOUR_MINUS_W = {'Crossman - 2022', 'Crossman - 2023', 'Jannese Davidson - 2023', 'Talk Hawk - 2023', 'Talk Hawk - 2024',
                'NCFA Spring Champs - 2022', 'NCFA Spring Champs - 2023', 'Gorlock Gala - 2023', 'Great Salt Lake - 2024'}


def mround05(x):
    return float((Decimal(str(x)) / Decimal('0.05')).quantize(Decimal('1'), ROUND_HALF_UP) * Decimal('0.05'))


def inner(w, l):
    t = w + l
    return mround05((w / t) * 2 + w * 0.25 - l * 0.25) if t else 0.0


def last(n):
    return n.strip().split()[-1].lower() if n.strip() else ''


def parse_total(s):  # "3-2" or "0-4 +1 bye"
    m = re.match(r'(\d+)-(\d+)(?: \+(\d+) bye)?', s)
    return int(m[1]) + int(m[2]) + int(m[3] or 0)


def main():
    src = HTML.read_text()
    m = PAT.search(src)
    logs = json.loads(m.group(2))
    log = []
    by_t = {}
    for r in logs:
        by_t.setdefault(r['Tournament'], []).append(r)

    # 1. prelim losses stored as 4 - wins at 9 FTN tournaments
    for v in csv.DictReader(open(VAL)):
        if v['tournament'] not in FOUR_MINUS_W or not v['explanation'].startswith('SITE ERROR: official FTN sheet has 5 prelims'):
            continue
        names = {last(n) for n in v['team'].split(' & ')}
        cand = [r for r in by_t.get(v['tournament'], []) if {last(r['Debater 1']), last(r['Debater 2'])} == names]
        if len(cand) != 1:
            log.append(f"!! no unique row for {v['tournament']} / {v['team']} ({len(cand)})")
            continue
        r = cand[0]
        w, l_old = r['Prelim Wins'], r['Prelim Losses']
        l_new = float(parse_total(v['parsed_prelim']) - w)
        if l_new == l_old:
            continue
        p_old = r['Points Earned'] or 0
        p_new = p_old
        if p_old:  # advanced: only the prelim component of the formula moves
            p_new = mround05(p_old - inner(w, l_old) + inner(w, l_new))
        r['Prelim Losses'], r['Points Earned'] = l_new, p_new
        log.append(f"{v['tournament']}: {v['team']} prelims {w:g}-{l_old:g} -> {w:g}-{l_new:g}, points {p_old} -> {p_new}")

    # 2. Rice 2024: Carrillo elim records swapped (Tabroom API: Holden Carrillo/Lan 2-1, Anthony Carrillo/Gallon 0-1)
    rice = {r['Debater 2']: r for r in by_t['Rice University Classic - 2024'] if 'Carrillo' in r['Debater 1']}
    g, ln = rice['Alexia Gallon'], rice['Michael Lan']
    if (g['Elim Wins'], ln['Elim Wins']) == (2, 1):
        g['Points Earned'], ln['Points Earned'] = ln['Points Earned'], g['Points Earned']
        g['Elim Wins'], g['Elim Losses'] = 0, 1
        ln['Elim Wins'], ln['Elim Losses'] = 2, 1
        log.append(f"Rice 2024: Gallon elims 2-1 -> 0-1 (pts {ln['Points Earned']} -> {g['Points Earned']}); Lan 1-1 -> 2-1 (pts {g['Points Earned']} -> {ln['Points Earned']})")

    # 3. Crossman 2021: 'N/A' partner of Mae Riley is Jose Chavez (official FTN sheet).
    #    Row-level fix: an alias for 'N/A' would rename every maverick placeholder.
    for r in by_t['Crossman - 2021']:
        if r['Debater 1'] == 'Mae Riley' and r['Debater 2'] == 'N/A':
            r['Debater 2'] = 'Jose Chavez'
            log.append('Crossman 2021: Mae Riley & N/A -> Mae Riley & Jose Chavez')

    out = json.dumps(logs)
    src = src[:m.start(2)] + out + src[m.end(2):]

    # 4. Talk Hawk 2026 'Aly they/them' -> Aly Greaver, via NAME_ALIASES (site convention)
    if "'aly they/them'" not in src:
        src = src.replace("        const NAME_ALIASES = {\n", "        const NAME_ALIASES = {\n            'aly they/them': 'Aly Greaver',\n", 1)
        log.append("NAME_ALIASES: 'aly they/them' -> 'Aly Greaver' (Talk Hawk 2026)")
    HTML.write_text(src)
    print('\n'.join(log) or 'nothing to change')


if __name__ == '__main__':
    main()

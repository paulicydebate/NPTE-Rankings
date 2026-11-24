"""SpeechWire prelim grids -> per-debater speaker points.

Reuses the word-coordinate grid reader in tools/h2h/p_speechwire.py (unchanged) but keeps what that reader
discards: the two score lines under each team (one per debater, one score per round, then the printed total)."""
import os, re, sys
import pdfplumber

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'h2h'))
from common import clean_name
import p_speechwire as p_sw

NUM = re.compile(r'^\d{1,3}\.\d{1,2}$')
JCODE = re.compile(r'^[A-Z]{1,4}\d{1,3}\s+')


def _block(lines, cols):
    """Same contract as p_speechwire.make_block plus 'scores': [(name, {round: pts}, printed_total)]."""
    b = _orig_make_block(lines, cols)
    scores = []
    for l in lines:
        if not any(w.get('__score') for w in l):
            continue
        real = [w for w in l if not w.get('__score')]
        name = clean_name(' '.join(w['text'] for w in real if w['x1'] < cols[0] + 5))
        per, tail = {}, []
        for w in real:
            t = w['text'].replace(',', '.')
            if not NUM.match(t):
                continue
            if w['x0'] >= cols[-1] - 6:
                tail.append(float(t))
                continue
            for k in range(len(cols) - 1):
                if cols[k] <= w['x0'] < cols[k + 1]:
                    per[k + 1] = float(t)
        scores.append((name, per, tail[0] if tail else None))
    b['scores'] = scores
    return b


_orig_make_block = p_sw.make_block


def grid_divisions(path, ocr=False, cache=None):
    if cache:                       # keep OCR output out of tools/h2h/cache (that folder is committed)
        os.makedirs(cache, exist_ok=True)
        p_sw.CACHE = cache
    pages = p_sw.page_words(path, ocr)
    p_sw.make_block = _block
    try:
        return p_sw.parse_grid(pages)
    finally:
        p_sw.make_block = _orig_make_block


def table_blocks(path):
    """'Tab grouping' sheet (Steve Hunt 2026): real table cells, team row then one row per debater."""
    rows = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            for t in p.find_tables():
                rows.extend(t.extract())
    blocks, orphans, i = [], [], 0
    while i < len(rows):
        r = rows[i]
        c0 = r[0] or ''
        if c0.strip() == 'Competitor' or '\n' not in c0:
            if c0.strip() and c0.strip() != 'Competitor' and len(r) > 6 and any(NUM.match((r[c] or '').strip()) for c in range(1, 6)):
                orphans.append(_score_row(r))     # debater line whose team line fell on the previous page
            i += 1
            continue
        code_line, school = c0.split('\n', 1)
        scores = []
        for k in (1, 2):
            if i + k < len(rows) and rows[i + k][0] and '\n' not in rows[i + k][0]:
                scores.append(_score_row(rows[i + k]))
        blocks.append({'comp': code_line.strip() + ' ' + ' '.join(school.split()), 'names': [s[0] for s in scores],
                       'rounds': {k: ' '.join((r[k] or '').split()) for k in range(1, 6)}, 'scores': scores})
        i += 1 + len(scores)
    if orphans:
        blocks.append({'comp': None, 'names': [o[0] for o in orphans], 'rounds': {}, 'scores': orphans, 'orphan': True})
    return blocks


def _score_row(sr):
    per = {}
    for c in range(1, 6):
        t = (sr[c] or '').strip()
        if NUM.match(t):
            per[c] = float(t)
    tot = next((float(x) for x in ((sr[6] or '').split() if len(sr) > 6 else []) if NUM.match(x)), None)
    return (clean_name(sr[0]), per, tot)


def pick_division(divs, site_last):
    def score(blocks):
        return sum(1 for b in blocks for n in b['names'] if n and n.lower().split()[-1] in site_last)
    cand = {d: b for d, b in divs.items() if d and re.search(r'parli|senior|open', d, re.I) and not re.search(r'ipda|novice', d, re.I)} or divs
    return max(cand, key=lambda d: (score(cand[d]), len(cand[d])))


def records(blocks):
    """-> (records, issues). One record per team per round with both debaters' points."""
    orphan = [b for b in blocks if b.get('orphan')]
    blocks = [b for b in blocks if not b.get('orphan')]
    teams = p_sw.build_prelims(blocks)
    out, issues = [], []
    for t, b in zip(teams, blocks):
        if len(b['scores']) != 2:
            issues.append(f'{t["code"]}: {len(b["scores"])} score lines')
        for name, per, tot in b['scores']:
            if tot is not None and abs(sum(per.values()) - tot) > 0.011:
                issues.append(f'{t["code"]} {name}: round points sum {sum(per.values()):.2f} != printed total {tot}')
        for rn, txt in sorted(t['rounds'].items()):
            txt = txt.strip()
            pts = {name: per[rn] for name, per, _ in b['scores'] if rn in per}
            lost_wl = False
            if not txt and not pts:
                continue
            if re.match(r'^BYE\b', txt) and not re.search(r'[WL]\s*-', txt):
                continue                      # bye: the sheet prints an average, not a judge's score
            m = p_sw.ROUND_RE.match(txt) or p_sw.ROUND_RE.match(p_sw.despace(txt))
            if not m and txt.startswith('-'):   # the W/L letter fell outside the column: result comes from the opponent's cell
                m = p_sw.ROUND_RE.match('W ' + txt)
                lost_wl = True
            if not m:
                if pts:
                    issues.append(f'{t["code"]} R{rn}: points but unparsed cell "{txt[:50]}"')
                continue
            res, ref, side, rest = m.groups()
            rest = re.sub(r'\s*\d{3}(?:\.\d+)?\s*$', '', rest.strip())
            judge = clean_name(JCODE.sub('', rest))
            out.append({'round': f'R{rn}', 'rtype': 'prelim', 'team': {'school': t['school_text'], 'names': t['names'], 'code': t['code']},
                        'side': 'Aff' if side.lower() in ('aff', 'gov') else 'Neg', 'win': None if lost_wl else res == 'W', 'judge': judge,
                        'pts': pts, 'opp': ' '.join(ref.split())})
    # a team whose own line was lost at a page break: its side, result and judge are the mirror of what its opponents' cells say
    flat = lambda c: re.sub(r'[^a-z]', '', c.lower())
    known = {flat(t['code']) for t in teams}
    unres = sorted({r['opp'] for r in out if flat(r['opp']) not in known})
    if orphan and len(unres) == 1 and len(orphan[0]['scores']) == 2:
        ob, ref = orphan[0], unres[0]
        for name, per, tot in ob['scores']:
            if tot is not None and abs(sum(per.values()) - tot) > 0.011:
                issues.append(f'{ref} {name}: round points sum {sum(per.values()):.2f} != printed total {tot}')
        for r in [x for x in out if x['opp'] == ref]:
            rn = int(r['round'][1:])
            out.append({'round': r['round'], 'rtype': 'prelim', 'team': {'school': ref, 'names': ob['names'], 'code': ref},
                        'side': 'Neg' if r['side'] == 'Aff' else 'Aff', 'win': None if r['win'] is None else not r['win'], 'judge': r['judge'],
                        'pts': {name: per[rn] for name, per, _ in ob['scores'] if rn in per}, 'opp': r['team']['code']})
        issues.append(f'{ref}: team line lost at a page break; rounds rebuilt from the opponents\' cells ({", ".join(ob["names"])})')
    elif orphan:
        issues.append(f'unmatched opponent references {unres} / {len(orphan)} debater lines without a team line')
    # fill a missing result from the other team in the same room (same round + judge, opposite side)
    for r in out:
        if r['win'] is None:
            o = [x for x in out if x is not r and x['round'] == r['round'] and x['judge'] == r['judge'] and x['side'] != r['side'] and x['win'] is not None]
            if len(o) == 1:
                r['win'] = not o[0]['win']
            else:
                issues.append(f'{r["team"]["code"]} {r["round"]}: win/loss letter missing and not recoverable')
    return out, issues

"""FTN result-sheet PDF -> debates (pdfplumber tables, like scrapers/FTN_Scraper.py)."""
import re, logging
import pdfplumber
from common import clean_name, key, norm_elim_label

logging.getLogger('pdfminer').setLevel(logging.ERROR)


def _n(c):
    if c is None:
        return ''
    t = re.sub(r'(?<!\s)-\s+(?=[a-z])', '-', str(c))
    return re.sub(r'\s+', ' ', t).strip()


def _split_team(cell):
    m = re.match(r'^(.+?)\s+-\s+(.+?)\s*&\s*(.+)$', cell)
    if not m:
        m = re.match(r'^(.+?)\s*-\s*(.+?)\s*&\s*(.+)$', cell)
    if not m:
        return None
    return m.group(1).strip(), [clean_name(m.group(2)), clean_name(m.group(3))]


def _full(cell):
    return re.sub(r'[^a-z]', '', key(cell.replace('&', ' ')))


def parse(path):
    teams = {}   # fullkey -> team
    rows = []    # (teamkey, round_label, side, opp_cell, judge_cell, decision)
    cur = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or not row[0]:
                        continue
                    c0 = _n(row[0])
                    joined = ' '.join(_n(c) for c in row if c)
                    if ' & ' in c0 and ' - ' in c0 and joined.count('Total Points') == 1 and 'Win' in joined:
                        st = _split_team(c0)
                        if not st:
                            continue
                        k = _full(c0)
                        if k not in teams:
                            mw = re.search(r'(\d+)\s*Wins?', joined)
                            teams[k] = {'school': st[0], 'names': st[1], 'code': c0, 'fk': k,
                                        'header_wins': int(mw.group(1)) if mw else None}
                        cur = k
                        continue
                    if len(row) < 5 or not row[1]:
                        continue
                    side = _n(row[1]).lower()
                    if side not in ('aff', 'neg', 'gov', 'opp') or cur is None:
                        continue
                    rows.append((cur, c0, 'Aff' if side in ('aff', 'gov') else 'Neg', _n(row[2]), _n(row[3]), _n(row[4])))
    # resolve opponents
    allk = list(teams)

    def resolve(opp):
        o = _full(opp)
        if not o:
            return None
        exact = [k for k in allk if k == o]
        if exact:
            return exact
        return [k for k in allk if k.startswith(o)] or [k for k in allk if o.startswith(k)]

    # round order
    def rkey(lbl):
        m = re.match(r'Rd\s*(\d+)', lbl, re.I)
        if m:
            return (0, int(m.group(1)))
        order = {'Triple Octos': 0, 'Double Octos': 1, 'Octos': 2, 'Quarters': 3, 'Semis': 4, 'Bronze': 5, 'Final': 6}
        return (1, order.get(norm_elim_label(lbl), 9))
    labels = sorted({r[1] for r in rows}, key=rkey)
    order = {l: i + 1 for i, l in enumerate(labels)}
    seen = {}
    by_round = {}
    for r in rows:
        by_round.setdefault((r[0], r[1]), []).append(r)
    debates = []
    issues = []
    used = set()
    for r in rows:
        tk, lbl, side, opp, judge, dec = r
        if (tk, lbl) in used:
            continue
        is_prelim = lbl.lower().startswith('rd')
        label = ('R' + re.search(r'(\d+)', lbl).group(1)) if is_prelim else norm_elim_label(lbl)
        dl = dec.upper()
        won = dl.startswith('W')
        letters = re.findall(r'[WL]', re.sub(r'^[WL]', '', dl.strip()))
        judges = [clean_name(j.split(' - ')[0]) for j in judge.split(';') if j.strip()]
        rec = {'round': label, 'round_order': order[lbl], 'round_type': 'prelim' if is_prelim else 'elim',
               'judges': [j for j in judges if j and 'zz' not in j.lower()], 'note': '', 'status': 'CONFIRMED'}
        if opp.strip().upper() == 'ZZ' or 'bye' in opp.lower():
            used.add((tk, lbl))
            rec.update(a=teams[tk], b=None, side_a=None, winner='a', ballots='', status='BYE')
            debates.append(rec)
            continue
        cands = resolve(opp) or []
        # prefer candidate whose own row in this round points back at tk with the opposite side
        def back(c):
            for rr in by_round.get((c, lbl), []):
                if tk in (resolve(rr[3]) or []):
                    return True
            return False
        good = [c for c in cands if c != tk and back(c)] or [c for c in cands if c != tk]
        if len(good) != 1:
            issues.append(f'{lbl}: {teams[tk]["code"]} vs "{opp}" -> {len(good)} candidates')
            if not good:
                st = _split_team(opp)
                bt = ({'school': st[0], 'names': st[1], 'code': opp, 'fk': _full(opp), 'no_header': True} if st else
                      {'school': '', 'names': [], 'code': opp, 'unresolved': True})
                wl0 = letters.count('W'), letters.count('L')
                rec.update(a=teams[tk], b=bt, side_a=side, winner=('a' if won else 'b') if dl[:1] in ('W', 'L') else None,
                           ballots=f'{max(wl0)}-{min(wl0)}' if sum(wl0) else '1-0', status='CONFIRMED',
                           note='opponent has no result sheet in the PDF; team taken from the opponent cell')
                used.add((tk, lbl)); debates.append(rec)
                continue
        ok = good[0]
        used.add((tk, lbl)); used.add((ok, lbl))
        wl = letters.count('W'), letters.count('L')
        if sum(wl) == 0:
            ball = '1-0'
        else:
            ball = f'{max(wl)}-{min(wl)}'
        # cross-check other side's decision
        other = by_round.get((ok, lbl), [])
        if other:
            od = other[0][5].upper()
            if od[:1] == dl[:1]:
                issues.append(f'{lbl}: both {teams[tk]["code"]} and {teams[ok]["code"]} show {dl[:1]}')
                rec['conflict'] = True
        rec.update(a=teams[tk], b=teams[ok], side_a=side, winner='a' if won else 'b', ballots=ball)
        if not dl[:1] in 'WL' or not dl or rec.get('conflict'):
            rec['winner'] = None
            rec['note'] = 'both result sheets show the same decision' if rec.get('conflict') else 'decision not shown (' + dec + ')'
        debates.append(rec)
    return debates, {'teams': teams, 'issues': issues}

"""FTN result-sheet PDF -> per-debater speaker-point rows.

Each team block is: header ("School - A & B ... N Wins - T Total Points"), a column row
("Rd | Side | Opponent | Judge | Decision | <debater 1> | <debater 2>") and one row per round whose
last two cells are that debater's points ("28.5", or "rank- pts" like "1- 28.5")."""
import re, logging
import pdfplumber

logging.getLogger('pdfminer').setLevel(logging.ERROR)
PTS = re.compile(r'^(?:(\d)\s*-\s*)?(\d{1,2}(?:\.\d+)?)$')


def _n(c):
    if c is None:
        return ''
    t = re.sub(r'(?<!\s)-\s+(?=[a-z])', '-', str(c))
    return re.sub(r'\s+', ' ', t).strip()


def _key(s):
    return re.sub(r'[^a-z]', '', re.sub(r'\([^()]*\)', '', s).lower())


def parse(path):
    """-> (teams, rows, issues)
    teams: {tk: {'school','names','code','total','wins','cols'}}  (cols = debater names in point-column order)
    rows: dicts with tk, round, side, opp, judge_cell, dec, pts[2], rank[2], raw[2]"""
    teams, rows, issues = {}, [], []
    cur = None
    seen = set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or not row[0]:
                        continue
                    c0 = _n(row[0])
                    joined = ' '.join(_n(c) for c in row if c)
                    if ' - ' in c0 and joined.count('Total Points') == 1 and 'Win' in joined and len(joined) < 400:
                        m = re.match(r'^(.+?)\s+-\s+(.+)$', c0)
                        if not m:
                            continue
                        names = [x.strip() for x in m.group(2).split(' & ') if x.strip()]
                        tk = _key(c0)
                        if tk not in teams:
                            mt = re.search(r'([\d.]+)\s*Total Points', joined)
                            mw = re.search(r'(\d+)\s*Wins?', joined)
                            teams[tk] = {'school': m.group(1).strip(), 'names': names, 'code': c0,
                                         'total': float(mt.group(1)) if mt else None, 'wins': int(mw.group(1)) if mw else None}
                        cur = tk
                        continue
                    if len(row) < 5 or not row[1] or cur is None:
                        continue
                    if c0 == 'Rd' and len(row) >= 7 and 'cols' not in teams[cur]:
                        teams[cur]['cols'] = [_n(row[5]), _n(row[6])]
                        continue
                    side = _n(row[1]).lower()
                    if side not in ('aff', 'neg', 'gov', 'opp'):
                        continue
                    if (cur, c0) in seen:
                        continue
                    seen.add((cur, c0))
                    cells = [_n(c) for c in row[5:7]] + ['', '']
                    pts, rank = [], []
                    for c in cells[:2]:
                        mm = PTS.match(c)
                        pts.append(float(mm.group(2)) if mm else None)
                        rank.append(int(mm.group(1)) if mm and mm.group(1) else 0)
                    rows.append({'tk': cur, 'round': c0, 'side': 'Aff' if side in ('aff', 'gov') else 'Neg', 'opp': _n(row[2]),
                                 'judge_cell': _n(row[3]), 'dec': _n(row[4]), 'pts': pts, 'rank': rank, 'raw': cells[:2]})
    return teams, rows, issues

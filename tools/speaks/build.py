#!/usr/bin/env python3
"""Build the private speaker-points dataset (plaintext, never committed).

    python3 tools/speaks/build.py

Reads the archived result sheets in source_pdfs/ (same files the head-to-head build uses), keeps Open/Varsity
NPDA/NPTE prelim speaker points, and writes into tools/speaks/out/ (gitignored):

    speaks.plain.json     the payload that encrypt.py turns into data/speaks.enc.json
    coverage.csv          one line per calendar tournament: what was extracted, or why not
    validation.csv        every row that was excluded or looks odd (contains speaker points)
    judge_candidates.csv  look-alike judge names that are NOT merged, for review

Nothing in out/ may be committed: it holds readable speaker points."""
import csv, datetime, difflib, json, os, re, sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'h2h'))
from common import REPO, SRC, clean_name, key, load_site, strip_accents
import x_ftn, x_tabroom, x_speechwire as x_sw

OUT = os.path.join(HERE, 'out')
CAL = os.path.join(HERE, '..', 'h2h', 'inputs', 'tournament_calendar.csv')
DEBATER_ALIASES = os.path.join(HERE, '..', 'h2h', 'debater_aliases.csv')
JUDGE_ALIASES = os.path.join(HERE, 'judge_aliases.csv')
MATCHUPS = os.path.join(HERE, '..', 'h2h', 'matchups.csv')
TB, FT, SW = SRC + '/tabroom/', SRC + '/FTN/', SRC + '/speechwire/'
LO, HI = 20.0, 30.0          # valid speaker-point range; anything outside is excluded and listed in validation.csv

# tournament (calendar spelling) -> source file, where the file name is not simply "<tournament>.<ext>"
FTN_FILES = {
    'GGO - 2026': 'GGO26.pdf', 'Crossman - 2025Jan': 'Crossman - 2025jan.pdf', 'Crossman - 2026': 'Crossman Invitational - 2026.pdf',
    'Jannese Davidson - 2022Jan': 'Jannese Davidson - 2022jan.pdf', 'Jannese Davidson - 2023': 'Janesse Davidson - 2023.pdf',
    'Jannese Davidson - 2024Jan': 'Jannese Daviedson - 2024Jan.pdf', 'Jannese Davidson - 2024oct': 'Jannese Davidson - 2024oct.pdf',
    'Tabor Venitsky - 2022': 'Tabor Ventisky - 2022.pdf', 'Talk Hawk - 2025': 'TalkHawk - 2025.pdf',
    'BLCC - 2023': 'Biggest Little City Classic - 2023.pdf',
}
TAB_FILES = {  # tournament -> (file, event abbr or None = pick by overlap with the site's team list)
    'Mile High pt 2 - 2023': ('Mile High pt2 - 2023.json', None), 'Mound High pt 1 - 2024': ('Mound High pt1 - 2024.json', None),
    'Mound High pt 2 - 2024': ('Mound high pt2 - 2024.json', None),
    'William Jewell pt 1 - 2024': ('William Jewell Swing pt 1 - 2024.json', None),
    'William Jewell pt 2 - 2024': ('William Jewelll Swing pt 2 - 2024.json', None),
    'Gina Lane pt 1 - 2025': ('Gina Lane pt1 and pt 2.json', 'NPDA'), 'Gina Lane pt 2 - 2025': ('Gina Lane pt1 and pt 2.json', 'NPTE'),
    'GGI - 2026': ('Golden Gate Invitational - 2026.json', None),
    'Big Tent - 2022': ('Big Tent - 2022.json', 'VNPDA'), 'Big Tent - 2023': ('Big Tent - 2023.json', 'VNPDA'),
}
SW_FILES = {  # tournament -> (file, mode); 'ocr' = obfuscated-font export, needs Tesseract (milestone 3)
    'Steve Hunt - 2021': ('complete Steve Hunt - 2021.pdf', 'ocr'), 'Steve Hunt - 2022': ('complete Steve Hunt - 2022.pdf', 'grid'),
    'Steve Hunt - 2023': ('complete Steve Hunt - 2023.pdf', 'ocr'), 'Steve Hunt - 2024': ('complete Steve Hunt - 2024.pdf', 'grid'),
    'Steve Hunt - 2025': ('complete Steve Hunt - 2025.pdf', 'ocr'), 'Steve Hunt - 2026': ('Steve Hunt Prelims.pdf', 'tables'),
    'Paul Winters - 2022': ('complete Paul Winters - 2022.pdf', 'grid'), 'Paul Winters - 2023': ('complete Paul Winters - 2023.pdf', 'ocr'),
    'Paul Winters - 2024': ('complete Paul Winters - 2024.pdf', 'grid'), 'Paul Winters - 2025': ('complete Paul Winters - 2025.pdf', 'grid'),
    'Paul Winters - 2026': ('complete Paul Winters - 2026.pdf', 'ocr'),
}
PLACEHOLDER = {'n/a', 'na', 'tba', 'tbd', 'zz', ''}
PRONOUNS = r'(they/them|he/him|she/her|she/they|he/they|they/she|they/he|any/all)'

# ------------------------------------------------------------------ site data + names
SITE = load_site()
NAME_ALIASES = {k.lower(): v for k, v in SITE['name_aliases'].items()}
SCHOOL_ALIASES = {k.lower(): v for k, v in SITE['school_aliases'].items()}
PERSON = {}
for r in csv.DictReader(open(DEBATER_ALIASES)):
    PERSON[r['alias']] = r['canonical_debater_id']


def canon(n):
    n = clean_name(n)
    n = re.sub(r'\s+' + PRONOUNS + r'$', '', n, flags=re.I).strip()
    return NAME_ALIASES.get(n.lower(), n)


def person(n):
    c = canon(n)
    return PERSON.get(c, c)


def canon_school(s):
    s = re.sub(r'\s+', ' ', (s or '')).strip()
    return SCHOOL_ALIASES.get(s.lower(), s)


SITE_ROWS = defaultdict(list)
for _r in SITE['logs']:
    _names = [canon(_r.get('Debater 1') or ''), canon(_r.get('Debater 2') or '')]
    SITE_ROWS[_r['Tournament']].append({'names': [n for n in _names if n and n.lower() not in PLACEHOLDER],
                                        'school': canon_school(_r.get('School')), 'team': _r.get('Team', '')})


def name_sim(a, b):
    """Same scoring the head-to-head build uses to line a source spelling up with a site spelling."""
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return 0
    if ka == kb:
        return 2.0
    pa, pb = ka.split(), kb.split()
    if pa[-1] == pb[-1] and pa[0][:1] == pb[0][:1]:
        return 1.6
    if difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.85:
        return 1.4
    if pa[-1] == pb[-1]:
        return 1.0
    if pa[0] == pb[0] and difflib.SequenceMatcher(None, pa[-1], pb[-1]).ratio() >= 0.75:
        return 1.0
    return 0


def school_sim(a, b):
    a, b = key(canon_school(a)).replace(' ', ''), key(canon_school(b)).replace(' ', '')
    if not a or not b:
        return 0.5
    return 1.0 if (a[:4] == b[:4] or a in b or b in a) else difflib.SequenceMatcher(None, a, b).ratio()


class Resolver:
    """Source team -> {source debater name: canonical debater}, canonical school, matched-to-site flag."""

    def __init__(self, tournament):
        self.t, self.rows, self.cache = tournament, SITE_ROWS.get(tournament, []), {}

    def __call__(self, team):
        raw = [n for n in team['names'] if n and clean_name(n).lower() not in PLACEHOLDER]
        ck = (team.get('code') or '') + '|' + '|'.join(raw)
        if ck in self.cache:
            return self.cache[ck]
        names = [canon(n) for n in raw]
        best = second = None
        for r in self.rows:
            used, s, det = set(), 0, {}
            for i, n in enumerate(names):
                bv, bj = 0, None
                for j, m in enumerate(r['names']):
                    v = name_sim(n, m)
                    if j not in used and v > bv:
                        bv, bj = v, j
                if bj is not None:
                    used.add(bj); s += bv; det[i] = (r['names'][bj], bv)
            s += 0.3 * school_sim(team.get('school') or team.get('code') or '', r['school'] or r['team'])
            if best is None or s > best[0]:
                best, second = (s, r, det), best
            elif second is None or s > second[0]:
                second = (s, r, det)
        need = 2.6 if len(names) >= 2 else 1.3
        ok = bool(best) and (second is None or best[0] - second[0] > 0.5) and (best[0] >= need or (len(names) >= 2 and best[0] >= 1.3))
        out = {'map': {}, 'school': canon_school(team.get('school') or ''), 'site': ok, 'loose': []}
        for i, n in enumerate(raw):
            tgt = names[i]
            if ok and i in best[2]:
                tgt, v = best[2][i]
                if v < 2.0 and key(tgt) != key(names[i]):
                    out['loose'].append((names[i], tgt, v))
            out['map'][n] = PERSON.get(tgt, tgt)
        if ok:
            out['school'] = best[1]['school'] or out['school']
        self.cache[ck] = out
        return out


# ------------------------------------------------------------------ judges
JALIAS, JBASIS, ALIAS_USED = {}, {}, Counter()
if os.path.exists(JUDGE_ALIASES):
    for r in csv.DictReader(open(JUDGE_ALIASES)):
        JALIAS[key(r['alias'])] = r['canonical']
        JBASIS[key(r['alias'])] = r['basis']


def split_judge(cell):
    """'First Last - School' / 'XX12 First Last' / 'Dr. First Last (they/them) - ONLINE' -> (name, affiliation)."""
    c = re.sub(r'\s+', ' ', (cell or '').replace(' ', ' ')).strip()
    c = re.sub(r'-\s+(?=[A-Za-z])(?<=[a-z]-\s)', '-', c) if re.search(r'[a-z]-\s[A-Z][a-z]', c) and ' - ' not in c else c
    c = re.sub(r'[\s-]+(REMOTE|ONLINE)\s*$', '', c, flags=re.I)
    aff = ''
    if ' - ' in c:
        c, aff = c.split(' - ', 1)
    c = clean_name(c)
    c = re.sub(r'^[A-Z]{1,4}\d{1,3}\s+', '', c)
    c = re.sub(r'\s+' + PRONOUNS + r'$', '', c, flags=re.I)
    c = re.sub(r'^(dr|prof|professor|mr|mrs|ms|mx)\.?\s+', '', c, flags=re.I)
    c = re.sub(r'^[A-Z]{2,6}\s*-\s*(?=[A-Z][a-z])', '', c)      # "PLNU-First Last"
    if len(c.split()) >= 3:
        c = re.sub(r'\s+[A-Z]{2}$', '', c)                         # trailing two-letter school code
    c = re.sub(r'\s*-\s*', '-', c).strip(' -,.')
    if c and c == c.lower():
        c = c.title()
    return c, aff.strip()


def judge_name(cell):
    n, aff = split_judge(cell)
    if not n or key(n) in ('zzbye', 'zz bye', 'bye', 'zz', 'tba'):
        return None, ''
    n = NAME_ALIASES.get(n.lower(), n)
    n = PERSON.get(n, n)
    if key(n) in JALIAS:
        ALIAS_USED[(n, JALIAS[key(n)])] += 1
        n = JALIAS[key(n)]
    return n, aff


# ------------------------------------------------------------------ extraction
S = []        # speaker rows: dict(t, round, deb, partner, school, judge, side, win, pts, rank)
D = []        # decisions: dict(t, round, judge, aff_won, elim)
VAL = []      # validation rows
COV = {}      # tournament -> dict
JSEEN = defaultdict(Counter)   # judge key -> Counter(spelling)
JAFF = defaultdict(Counter)    # judge key -> Counter(affiliation)
JPID = defaultdict(set)        # tabroom person id -> {judge key}
JTOUR = defaultdict(set)


def val(t, kind, detail, **kw):
    VAL.append({'tournament': t, 'issue': kind, 'detail': detail, 'round': kw.get('round', ''), 'debater': kw.get('debater', ''),
                'judge': kw.get('judge', ''), 'points': kw.get('points', ''), 'action': kw.get('action', '')})


def see_judge(t, raw, pid=None):
    n, aff = judge_name(raw)
    if not n:
        return None
    k = key(n)
    JSEEN[k][n] += 1
    JTOUR[k].add(t)
    if aff:
        JAFF[k][aff] += 1
    if pid:
        JPID[pid].add(k)
    return k


def add_points(t, res, team, rnd, judge_k, side, win, pts_by_raw, rank_by_raw=None):
    """pts_by_raw: {source debater name: points}. Applies the range filter; returns rows added."""
    n = 0
    mapped = res['map']
    for raw, p in pts_by_raw.items():
        deb = mapped.get(raw) or person(raw)
        partner = next((mapped[x] for x in mapped if x != raw), None)
        if p is None:
            continue
        if '/' in deb:
            val(t, 'not an individual', 'entry is listed as a group, not as named debaters', round=rnd, debater=deb, points=p, action='excluded')
            continue
        if not (LO <= p <= HI):
            val(t, 'out of range', 'zero = no score entered / absent partner / forfeit' if p == 0 else f'outside {LO:g}-{HI:g}',
                round=rnd, debater=deb, judge=JSEEN[judge_k].most_common(1)[0][0] if judge_k else '', points=p, action='excluded')
            continue
        S.append({'t': t, 'round': rnd, 'deb': deb, 'partner': partner, 'school': res['school'], 'judge': judge_k,
                  'side': side, 'win': win, 'pts': p, 'rank': (rank_by_raw or {}).get(raw, 0)})
        n += 1
    return n


def note_resolution(t, res, team):
    for a, b, v in res['loose']:
        val(t, 'name matched loosely', f'source "{a}" counted as site debater "{b}" (similarity {v})', debater=b, action='included')


def do_ftn(t):
    path = FT + FTN_FILES.get(t, t + '.pdf')
    if not os.path.exists(path):
        return None
    teams, rows, _ = x_ftn.parse(path)
    R = Resolver(t)
    st = Counter()
    sums, byes = Counter(), Counter()
    for r in rows:
        team = teams[r['tk']]
        res = R(team)
        pre = r['round'].lower().startswith('rd')
        rnd = 'R' + re.sub(r'\D', '', r['round']) if pre else {'Finals': 'Final', 'Gold': 'Final'}.get(r['round'], r['round'])
        cells = [c.strip() for c in r['judge_cell'].split(';')]
        if not pre:
            m = re.match(r'^([WLS?])\s*\(([WL?]+)\)', r['dec'])
            if m and r['side'] == 'Aff' and r['opp'] != 'ZZ' and len(m.group(2)) == len(cells):
                for c, v in zip(cells, m.group(2)):
                    jk = see_judge(t, c)
                    if jk and v in 'WL':
                        D.append({'t': t, 'round': rnd, 'judge': jk, 'aff_won': v == 'W', 'elim': 1})
            continue
        st['prelim_team_rounds'] += 1
        scored = r['pts'][0] is not None or r['pts'][1] is not None
        if not scored:
            st['bye_rows'] += 1
            byes[r['tk']] += 1
            continue
        sums[r['tk']] += sum(p for p in r['pts'] if p is not None)
        jk = see_judge(t, cells[0]) if len(cells) == 1 else None
        if len(cells) != 1:
            val(t, 'more than one judge on a prelim', r['judge_cell'], round=rnd, action='points kept without a judge')
        elif not jk and r['opp'] != 'ZZ':
            val(t, 'no judge named', f'judge cell reads "{r["judge_cell"]}"', round=rnd, debater=' & '.join(res['map'].values()),
                points='/'.join(str(p) for p in r['pts']), action='points kept without a judge (raw stats only)')
        win = {'W': 1, 'L': 0}.get(r['dec'], -1)
        if r['opp'] == 'ZZ':
            val(t, 'scored round with no listed opponent', f'opponent "ZZ", decision "{r["dec"]}", judge "{r["judge_cell"]}": a real judge '
                'scored it (swing/exhibition team), so the points are kept; no win/loss is counted', round=rnd,
                debater=' & '.join(res['map'].values()), judge=r['judge_cell'], points='/'.join(str(p) for p in r['pts']), action='included')
            win = -1
        elif r['dec'] not in ('W', 'L'):
            val(t, 'non-standard decision', f'decision "{r["dec"]}"', round=rnd, debater=' & '.join(res['map'].values()),
                judge=r['judge_cell'], points='/'.join(str(p) for p in r['pts']), action='points kept, no win/loss')
        elif r['side'] == 'Aff' and jk:
            D.append({'t': t, 'round': rnd, 'judge': jk, 'aff_won': r['dec'] == 'W', 'elim': 0})
        names = team['names']
        pts = {names[i]: r['pts'][i] for i in range(min(2, len(names))) if clean_name(names[i]).lower() not in PLACEHOLDER}
        rk = {names[i]: r['rank'][i] for i in range(min(2, len(names)))}
        st['rows'] += add_points(t, res, team, rnd, jk, r['side'], win, pts, rk)
    for tk, team in teams.items():
        res = R(team)
        note_resolution(t, res, team)
        if not res['site']:
            st['teams_not_on_site'] += 1
        if team['total'] is not None and abs(sums[tk] - team['total']) > 0.051 and not byes[tk]:
            val(t, 'sheet total differs', f'{team["code"]}: parsed round points sum {sums[tk]:g}, sheet prints {team["total"]:g}', action='check')
    st['teams'] = len(teams)
    return st, os.path.relpath(path, REPO)


def tab_event(t, path):
    fn_ev = TAB_FILES.get(t, (None, None))[1]
    if fn_ev:
        return fn_ev
    site_last = {key(n).split()[-1] for r in SITE_ROWS[t] for n in r['names'] if key(n)}
    best = None
    for e in x_tabroom.events(path):
        nm = (str(e.get('name')) + ' ' + str(e.get('abbr'))).lower()
        if re.search(r'ipda|card|ndt|ceda|\bld\b|nfa|novice|\bjv\b|junior', nm):
            continue
        try:
            _, ents, ab = x_tabroom.parse(path, e.get('abbr') or e.get('name'))
        except Exception:
            continue
        ov = len({key(n).split()[-1] for en in ents.values() for n in en['names'] if key(n)} & site_last)
        if best is None or ov > best[0]:
            best = (ov, ab)
    return best[1] if best else None


def do_tabroom(t):
    path = TB + TAB_FILES.get(t, (t + '.json', None))[0]
    if not os.path.exists(path):
        return None
    ev = tab_event(t, path)
    recs, entries, ev = x_tabroom.parse(path, ev)
    R = Resolver(t)
    st = Counter()
    for r in recs:
        if r['sec_bye']:
            continue
        res = R(r['team'])
        jk = see_judge(t, r['judge'], r['judge_pid']) if r['judge'] else None
        if r['win'] is not None and r['side'] == 'Aff' and jk:
            D.append({'t': t, 'round': r['round'], 'judge': jk, 'aff_won': r['win'], 'elim': 0 if r['rtype'] == 'prelim' else 1})
            st['decisions'] += 1
        if r['rtype'] == 'prelim':
            st['prelim_team_rounds'] += 1
        if r['pts']:
            st['rows'] += add_points(t, res, r['team'], r['round'], jk, r['side'], -1 if r['win'] is None else int(r['win']), r['pts'])
    seen = set()
    for r in recs:
        if r['tid'] not in seen:
            seen.add(r['tid'])
            res = R(r['team'])
            note_resolution(t, res, r['team'])
            if not res['site']:
                st['teams_not_on_site'] += 1
    st['teams'] = len(seen)
    st['ballots'] = len(recs)
    return st, os.path.relpath(path, REPO) + f' [event {ev}]'


def do_speechwire(t):
    fn, mode = SW_FILES[t]
    path = SW + fn
    if not os.path.exists(path):
        return None
    if mode == 'ocr':
        return 'ocr', os.path.relpath(path, REPO)
    if mode == 'tables':
        blocks, div = x_sw.table_blocks(path), 'Senior Parliamentary Debate'
    else:
        divs = x_sw.grid_divisions(path)
        site_last = {key(n).split()[-1] for r in SITE_ROWS[t] for n in r['names'] if key(n)}
        div = x_sw.pick_division(divs, site_last)
        blocks = divs[div]
    recs, issues = x_sw.records(blocks)
    for i in issues:
        val(t, 'speechwire sheet', i, action='check')
    R = Resolver(t)
    st = Counter()
    for r in recs:
        res = R(r['team'])
        jk = see_judge(t, r['judge']) if r['judge'] else None
        st['prelim_team_rounds'] += 1
        if r['win'] is not None and r['side'] == 'Aff' and jk:
            D.append({'t': t, 'round': r['round'], 'judge': jk, 'aff_won': r['win'], 'elim': 0})
        st['rows'] += add_points(t, res, r['team'], r['round'], jk, r['side'], -1 if r['win'] is None else int(r['win']), r['pts'])
    for b in blocks:
        st['bye_rows'] += sum(1 for txt in b['rounds'].values() if re.match(r'^\s*BYE\b', txt))
    seen = set()
    for r in recs:
        c = r['team']['code']
        if c not in seen:
            seen.add(c)
            res = R(r['team'])
            note_resolution(t, res, r['team'])
            if not res['site']:
                st['teams_not_on_site'] += 1
    st['teams'] = len(seen)
    return st, os.path.relpath(path, REPO) + f' [division {div}]'


def matchup_decisions(t):
    """Prelim decisions for tournaments whose export has no per-ballot scores: taken from the head-to-head matchup table."""
    n = 0
    for r in MATCH.get(t, []):
        if r['round_type'] == 'prelim' and r['status'] == 'CONFIRMED' and r['sides_known'] == 'Y' and r['judges'] and ';' not in r['judges']:
            jk = see_judge(t, r['judges'])
            if jk:
                D.append({'t': t, 'round': r['round'], 'judge': jk, 'aff_won': r['winner'] == r['aff_debaters'], 'elim': 0})
                n += 1
    return n


MATCH = defaultdict(list)
if os.path.exists(MATCHUPS):
    for _r in csv.DictReader(open(MATCHUPS)):
        MATCH[_r['tournament']].append(_r)


def main():
    os.makedirs(OUT, exist_ok=True)
    cal = list(csv.DictReader(open(CAL)))
    for c in cal:
        t, plat = c['tournament'], c['platform']
        got = {'FTN': do_ftn, 'Tabroom': do_tabroom, 'SpeechWire': do_speechwire}[plat](t)
        cov = {'season': c['season'], 'order': c['order_in_season'], 'tournament': t, 'platform': plat, 'source': '', 'teams': 0,
               'speaker_rows': 0, 'judge_names': '', 'decisions': 0, 'bye_rows': 0, 'teams_not_on_site': 0, 'status': '', 'reason': ''}
        if got is None:
            cov.update(status='missing', reason='source file is not in the repository')
        elif got[0] == 'ocr':
            cov.update(status='pending', source=got[1], reason='image-only SpeechWire sheet: needs OCR (planned for the next milestone)')
            cov['decisions'] = matchup_decisions(t)
        else:
            st, src = got
            cov.update(source=src, teams=st['teams'], speaker_rows=st['rows'], bye_rows=st['bye_rows'], teams_not_on_site=st['teams_not_on_site'])
            if st['rows']:
                cov['status'] = 'included'
            else:
                cov['status'] = 'no points'
                has_wl = any(d['t'] == t for d in D)
                cov['reason'] = ('export records win/loss only, no speaker points' if has_wl
                                 else 'export has ballots but no scores at all (empty score arrays)')
                if not has_wl:
                    matchup_decisions(t)
        COV[t] = cov

    # ---- judges: merge by Tabroom person id (same account = same person), then pick the most common spelling
    parent = {}

    def find(k):
        while parent.get(k, k) != k:
            k = parent[k]
        return k
    for pid, ks in JPID.items():
        ks = sorted(ks, key=lambda k: -sum(JSEEN[k].values()))
        for k in ks[1:]:
            if find(k) != find(ks[0]):
                parent[find(k)] = find(ks[0])
                val('', 'judge spellings merged', f'"{JSEEN[k].most_common(1)[0][0]}" = "{JSEEN[ks[0]].most_common(1)[0][0]}" (same Tabroom account {pid})',
                    action='merged')
    groups = defaultdict(list)
    for k in JSEEN:
        groups[find(k)].append(k)
    jname, jaff, jtour = {}, {}, {}
    for g, ks in groups.items():
        c = Counter()
        a = Counter()
        tt = set()
        for k in ks:
            c.update(JSEEN[k]); a.update(JAFF[k]); tt |= JTOUR[k]
        jname[g] = c.most_common(1)[0][0]
        jaff[g] = a.most_common(1)[0][0] if a else ''
        jtour[g] = tt
    for s in S:
        if s['judge']:
            s['judge'] = find(s['judge'])
    for d in D:
        d['judge'] = find(d['judge'])
    for t, cov in COV.items():
        rows = [s for s in S if s['t'] == t]
        cov['judge_names'] = 'yes' if rows and all(s['judge'] for s in rows) else ('partly' if any(s['judge'] for s in rows) else ('no' if rows else ''))
        cov['decisions'] = sum(1 for d in D if d['t'] == t)

    # ---- duplicate guard: one score per debater per round per judge
    seen = {}
    keep = []
    for s in S:
        k = (s['t'], s['round'], s['deb'], s['judge'])
        if k in seen:
            val(s['t'], 'duplicate row', 'same debater, round and judge appears twice', round=s['round'], debater=s['deb'], points=s['pts'], action='second copy dropped')
            continue
        seen[k] = 1
        keep.append(s)
    S[:] = keep

    # ---- judge look-alikes (review file)
    nb = Counter(s['judge'] for s in S if s['judge'])
    nd = Counter(d['judge'] for d in D)
    cand = []
    gs = sorted(jname, key=lambda g: jname[g])
    NICK = [{'gabe', 'gabriel'}, {'matt', 'matthew'}, {'mike', 'michael'}, {'will', 'william', 'bill'}, {'joe', 'joseph', 'joey'}, {'nick', 'nicholas', 'nicolas', 'nico'},
            {'alex', 'alexander', 'alexandra', 'alexis'}, {'ben', 'benjamin'}, {'chris', 'christopher'}, {'dan', 'daniel', 'danny'}, {'max', 'maximus', 'maxwell'},
            {'sam', 'samuel', 'samantha'}, {'kate', 'katherine', 'katie', 'kaitlyn'}, {'jon', 'jonathan', 'john'}, {'tom', 'thomas'}, {'steve', 'steven', 'stephen'},
            {'josh', 'joshua'}, {'zach', 'zachary', 'zack'}, {'andy', 'andrew', 'drew'}, {'liz', 'elizabeth'}, {'jen', 'jennifer'}, {'rob', 'robert', 'bob'}]
    for i, a in enumerate(gs):
        pa = key(jname[a]).split()
        for b in gs[i + 1:]:
            pb = key(jname[b]).split()
            if not pa or not pb:
                continue
            ratio = difflib.SequenceMatcher(None, ' '.join(pa), ' '.join(pb)).ratio()
            why = ''
            if pa[-1] == pb[-1]:
                fa, fb = pa[0], pb[0]
                if fa == fb:
                    why = 'same first and last name, different middle'
                elif any(fa in n and fb in n for n in NICK):
                    why = 'same last name, first names are a known nickname pair'
                elif fa.startswith(fb) or fb.startswith(fa):
                    why = 'same last name, one first name is a short form of the other'
                elif ratio >= 0.8:
                    why = 'same last name, similar first name'
                elif fa[0] == fb[0]:
                    why = 'same last name and first initial (weak)'
            elif pa[0] == pb[0] and difflib.SequenceMatcher(None, pa[-1], pb[-1]).ratio() >= 0.75:
                why = 'same first name, similar last name'
            elif ratio >= 0.88:
                why = 'similar spelling'
            if why:
                cand.append({'name_a': jname[a], 'ballots_a': nb[a], 'decisions_a': nd[a], 'affiliation_a': jaff[a],
                             'name_b': jname[b], 'ballots_b': nb[b], 'decisions_b': nd[b], 'affiliation_b': jaff[b],
                             'similarity': round(ratio, 2), 'why_flagged': why,
                             'shared_tournaments': len(jtour[a] & jtour[b]),
                             'tournaments_a': '; '.join(sorted(jtour[a])[:6]), 'tournaments_b': '; '.join(sorted(jtour[b])[:6]),
                             'status': 'NOT merged', 'same_person? (Y/N)': ''})
    cand.sort(key=lambda c: (-c['similarity'], c['name_a']))
    for (alias, can), n in sorted(ALIAS_USED.items()):
        g = find(key(can))
        cand.append({'name_a': can, 'ballots_a': nb[g], 'decisions_a': nd[g], 'affiliation_a': jaff.get(g, ''), 'name_b': alias, 'ballots_b': '',
                     'decisions_b': '', 'affiliation_b': '', 'similarity': round(difflib.SequenceMatcher(None, key(can), key(alias)).ratio(), 2),
                     'why_flagged': f'listed in judge_aliases.csv ({JBASIS.get(key(alias), "")}); "{alias}" appears {n} times', 'shared_tournaments': '',
                     'tournaments_a': '', 'tournaments_b': '', 'status': 'MERGED (counted as name_a)', 'same_person? (Y/N)': ''})

    # ---- payload
    seasons = sorted({c['season'] for c in cal})
    t_idx = {c['tournament']: i for i, c in enumerate(cal)}
    schools, debs, judges = {}, {}, {}

    def ix(table, v):
        if v not in table:
            table[v] = len(table)
        return table[v]
    rows = []
    S.sort(key=lambda s: (t_idx[s['t']], s['round'], s['judge'] or '', s['deb']))
    for s in S:
        rows.append([t_idx[s['t']], s['round'], ix(debs, s['deb']), ix(debs, s['partner']) if s['partner'] else -1, ix(schools, s['school'] or '?'),
                     ix(judges, s['judge']) if s['judge'] else -1, {'Aff': 1, 'Neg': 2}.get(s['side'], 0), s['win'], s['pts'], s['rank'] or 0])
    dec = [[t_idx[d['t']], d['round'], ix(judges, d['judge']), 1 if d['aff_won'] else 0, d['elim']] for d in D]
    jl = [None] * len(judges)
    for g, i in judges.items():
        jl[i] = [jname[g], jaff[g]]
    status_code = {'included': 0, 'no points': 1, 'missing': 2, 'pending': 3}
    tourn = [[c['tournament'], seasons.index(c['season']), int(c['order_in_season']), c['platform'],
              1 if COV[c['tournament']]['judge_names'] in ('yes', 'partly') else 0, status_code[COV[c['tournament']]['status']],
              COV[c['tournament']]['speaker_rows'], COV[c['tournament']]['decisions'], c['start_date']] for c in cal]
    missing = [[c['season'], c['tournament'], c['platform'], COV[c['tournament']]['reason']] for c in cal if COV[c['tournament']]['status'] != 'included']
    payload = {
        'meta': {'built': datetime.date.today().isoformat(), 'tournaments_with_speaks': sum(1 for c in COV.values() if c['status'] == 'included'),
                 'tournaments_total': len(cal), 'rows': len(rows), 'decisions': len(dec), 'range': [LO, HI]},
        'seasons': seasons, 'tournaments': tourn, 'schools': list(schools), 'debaters': list(debs), 'judges': jl,
        'missing': missing, 'r': rows, 'd': dec,
    }
    json.dump(payload, open(os.path.join(OUT, 'speaks.plain.json'), 'w'), separators=(',', ':'), ensure_ascii=False)

    def wcsv(name, rws, cols):
        with open(os.path.join(OUT, name), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rws)
    wcsv('coverage.csv', [COV[c['tournament']] for c in cal],
         ['season', 'order', 'tournament', 'platform', 'status', 'reason', 'teams', 'speaker_rows', 'judge_names', 'decisions', 'bye_rows', 'teams_not_on_site', 'source'])
    wcsv('validation.csv', VAL, ['tournament', 'issue', 'round', 'debater', 'judge', 'points', 'action', 'detail'])
    wcsv('judge_candidates.csv', cand, list(cand[0].keys()) if cand else ['name_a'])
    st = Counter(c['status'] for c in COV.values())
    print(f"tournaments: {dict(st)}  speaker rows: {len(rows)}  debaters: {len(debs)}  judges: {len(judges)}  decisions: {len(dec)}")
    print(f"validation rows: {len(VAL)} {dict(Counter(v['issue'] for v in VAL))}")
    print(f"judge look-alike pairs to review: {len(cand)}")


if __name__ == '__main__':
    main()

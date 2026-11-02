#!/usr/bin/env python3
"""Rebuild the NPTE-Rankings round-by-round matchup table, per-season ELO, and the head-to-head page.

    python3 build.py            # everything, from the source files
Outputs (this folder): matchups.csv, debater_ids.csv, elo_partnerships.csv, elo_debaters.csv,
elo_history.csv, h2h.html, validation.csv, coverage.csv  (README.md is hand-written, numbers from coverage.csv)
"""
# ----------------------------------------------------------------------------- ELO config
ELO_START = 1500          # starting rating for every partnership / debater
ELO_K = 32                # K factor for prelims
ELO_K_ELIM = 32           # K factor for elims (set higher to weight elims more)
SEASON_CARRY_R = 0.75     # season-scope carry-over: new season start = 1500 + R * (previous season end - 1500)
                          # brand-new debaters start at ELO_START; a partnership starts each season at the average of its
                          # two debaters' carried-over ratings (R = 0 gives a hard reset every season)
BALLOT_WEIGHT = False     # False: score = 1/0 by decision. True: score = ballot share (2-1 -> 0.667 / 0.333)
ELO_STATUSES = ('CONFIRMED', 'INFERRED')   # statuses that count as debates for ELO
# -----------------------------------------------------------------------------
import csv, difflib, json, os, re, sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPO, SRC, NEW, HERE, CACHE, clean_name, key, load_site, strip_accents
import p_tabroom, p_ftn, p_speechwire as p_sw

CAL = os.path.join(HERE, 'inputs', 'tournament_calendar.csv')
MOUND24 = os.path.join(HERE, 'inputs', 'mound_high_pt1_2024_matchups.csv')
TB, FT, SW = SRC + '/tabroom/', SRC + '/FTN/', SRC + '/speechwire/'
PW24 = NEW + '/Paul Winters - 2024 PDFs/'

ELIM_ORDER = ['Triple Octos', 'Double Octos', 'Octos', 'Quarters', 'Semis', 'Final']

FTN_FILES = {
    'GGO - 2026': 'GGO26.pdf', 'Crossman - 2025Jan': 'Crossman - 2025jan.pdf', 'Crossman - 2026': 'Crossman Invitational - 2026.pdf',
    'Jannese Davidson - 2022Jan': 'Jannese Davidson - 2022jan.pdf', 'Jannese Davidson - 2023': 'Janesse Davidson - 2023.pdf',
    'Jannese Davidson - 2024Jan': 'Jannese Daviedson - 2024Jan.pdf', 'Jannese Davidson - 2024oct': 'Jannese Davidson - 2024oct.pdf',
    'Tabor Venitsky - 2022': 'Tabor Ventisky - 2022.pdf', 'Talk Hawk - 2025': 'TalkHawk - 2025.pdf',
    'BLCC - 2023': 'Biggest Little City Classic - 2023.pdf',
}
TAB_FILES = {
    'Mile High pt 2 - 2023': ('Mile High pt2 - 2023.json', None), 'Mound High pt 2 - 2024': ('Mound high pt2 - 2024.json', None),
    'William Jewell pt 1 - 2024': ('William Jewell Swing pt 1 - 2024.json', None),
    'William Jewell pt 2 - 2024': ('William Jewelll Swing pt 2 - 2024.json', None),
    'Gina Lane pt 1 - 2025': ('Gina Lane pt1 and pt 2.json', 'NPDA'), 'Gina Lane pt 2 - 2025': ('Gina Lane pt1 and pt 2.json', 'NPTE'),
    'GGI - 2026': ('Golden Gate Invitational - 2026.json', None),
    'Rice University Classic - 2022': (NEW + '/Rice University Classic - 2022.json', None),
    'Big Tent - 2022': ('Big Tent - 2022.json', 'VNPDA'), 'Big Tent - 2023': ('Big Tent - 2023.json', 'VNPDA'),
}
SW_FILES = {  # tournament -> (grid pdf, elim pdf or None, ocr?, mode)
    'Steve Hunt - 2021': (SW + 'complete Steve Hunt - 2021.pdf', None, True, 'grid'),
    'Steve Hunt - 2022': (SW + 'complete Steve Hunt - 2022.pdf', None, False, 'grid'),
    'Steve Hunt - 2023': (SW + 'complete Steve Hunt - 2023.pdf', None, True, 'grid'),
    'Steve Hunt - 2024': (SW + 'complete Steve Hunt - 2024.pdf', None, False, 'grid'),
    'Steve Hunt - 2025': (SW + 'complete Steve Hunt - 2025.pdf', None, True, 'grid'),
    'Steve Hunt - 2026': (SW + 'Steve Hunt Prelims.pdf', NEW + '/Steve Hunt - 2026 elim results.pdf', True, 'tables'),
    'Paul Winters - 2022': (SW + 'complete Paul Winters - 2022.pdf', None, False, 'grid'),
    'Paul Winters - 2023': (SW + 'complete Paul Winters - 2023.pdf', None, True, 'grid'),
    'Paul Winters - 2024': (PW24 + 'd3418171-paul_winter_24_win_loss.pdf', PW24 + 'eab7cbc1-paul_winters_24_-_elim_resuklts.pdf', False, 'grid'),
    'Paul Winters - 2025': (SW + 'complete Paul Winters - 2025.pdf', None, False, 'grid'),
}
# Same-person merges confirmed by Paul (Nov 2, 2026). alias -> canonical (most common / site spelling).
# Applied after site matching, so it only changes debater ids, never which site row a team matches.
PERSON_MERGE = {
    'Anaie Stephens': 'Angelina Stephens',
    'Belcher/Machado/Ruiz _': 'Belcher/Machado/Ruiz', 'Belcher/Machado/Ruiz __': 'Belcher/Machado/Ruiz',
    'Christopher Lapee': 'Chris Lapee', 'Christopher LaPee': 'Chris Lapee',
    'Gemma Margaret Caruso': 'Gemma Caruso',
    'Jamari Jackson': 'Jasmyne Jackson',
    'Julian MacKenzie': 'Julian Mackenzie',
    'Lukas LePage': 'Lucas Lepage', 'Lukas Lepage': 'Lucas Lepage',
    'Madeline Smith': 'Mason Smith',
    'Memon/Maszk/Wagner _': 'Memon/Maszk/Wagner', 'Memon/Maszk/Wagner __': 'Memon/Maszk/Wagner',
    'NIkki Stancik': 'Nikki Stancik',
    'Samantha Bush': 'Samantha Baldus',
    'Vik Fodor': 'Viktor Clinton Fodor',
    # Paul 2026-11-02: SpeechWire OCR spelling -> Tabroom/FTN spelling
    'Jasper Pachecho': 'Jasper Pacheco',
    'Angie Stephens': 'Angelina Stephens',
    # Paul 2026-11-02: correct spellings for SpeechWire-only names
    'Skv-Rose Jaamann': 'Sky-Rose Jaamann', 'Anvla Hall': 'Anyla Hall', 'Tan Woolridge': 'Ian Woolridge',
}
# NOT merged although flagged: Juliette Celis / Julissa Celis debate as partners on the same team (two people).
NOT_MERGED = {('Juliette Celis', 'Julissa Celis'): 'partners on the same team (Crossman 2025Jan, PSCFA Spring 2025), so two different people'}


def apply_person_merge(debs):
    done = set()
    for d in debs:
        for t in (d['a'], d['b']):
            if t and id(t) not in done:
                done.add(id(t))
                out = []
                names = [NAME_FILL.get((d['tournament'], next((m for m in t['names'] if m != n), ''), n), n) for n in t['names']]
                for n in names:
                    if n in PLACEHOLDER_NAMES:
                        continue
                    c = PERSON_MERGE.get(n, n)
                    if c != n:
                        MERGED_SEEN[c].add(n)
                    if c not in out:
                        out.append(c)
                t['names'] = out


MERGED_SEEN = defaultdict(set)
# Debater name gaps filled from the official result sheets (tournament, other team member, placeholder) -> real name
NAME_FILL = {('Crossman - 2021', 'Mae Riley', 'N/A'): 'Jose Chavez'}   # official FTN sheet: UCSD Mae Riley & Jose Chavez (site + PDF: "N/A")
PLACEHOLDER_NAMES = {'N/A', 'NA', 'TBA', 'TBD'}   # a "N/A" partner = one-person (maverick) team, never a debater id

# FTN tournaments where the site stores prelim losses as 4 - wins although the official sheets show 5 prelims
SITE_LOSSES_4_MINUS_W = {'Crossman - 2022', 'Crossman - 2023', 'Jannese Davidson - 2023', 'Talk Hawk - 2023', 'Talk Hawk - 2024',
                         'NCFA Spring Champs - 2022', 'NCFA Spring Champs - 2023', 'Gorlock Gala - 2023', 'Great Salt Lake - 2024'}
FTN_LIVE = {}
try:
    FTN_LIVE = json.load(open(os.path.join(HERE, 'cache', 'ftn_live.json')))
except Exception:
    pass


def _lastset(names):
    return frozenset(key(n).split()[-1] for n in names if key(n))


def ftn_official(raw, t, notes):
    """Cross-check an FTN parse with the official result sheets (cache/ftn_live.json, fetched by ftn_live.py).
    Double wins (both teams credited W, 'W&W') become DOUBLE_WIN; unknown decisions are filled from the sheet."""
    L = FTN_LIVE.get(t)
    if not L:
        return
    dec = {}
    for tm in L['teams']:
        me = _lastset(canon(re.sub(r'\(.*?\)', '', n).strip()) for n in tm['names'] if n.strip() not in PLACEHOLDER_NAMES)
        for r in tm['rounds']:
            m = re.match(r'Rd (\d+)', r['rd'])
            if m:
                dec[(me, 'R' + m.group(1))] = (r['dec'].strip(), r['opp'], r['judges'])
    for d in raw:
        if d['b'] is None or d['round_type'] != 'prelim':
            continue
        ka = _lastset(n for n in d['a']['names'] if n not in PLACEHOLDER_NAMES)
        kb = _lastset(n for n in d['b']['names'] if n not in PLACEHOLDER_NAMES)
        oa, ob = dec.get((ka, d['round'])), dec.get((kb, d['round']))
        if not oa and not ob:
            continue
        da, db = (oa or ('',))[0], (ob or ('',))[0]
        if da.startswith('W&W') or db.startswith('W&W'):
            d['status'], d['winner'] = 'DOUBLE_WIN', None
            d['note'] = (d['note'] + '; official FTN sheet: double win (W&W, both teams credited a win), not a decided debate').strip('; ')
            notes.append(f'{t} {d["round"]}: double win per official FTN sheet ({" & ".join(d["a"]["names"])} vs {" & ".join(d["b"]["names"])})')
        elif d['winner'] is None:
            w = 'a' if da[:1] == 'W' or db[:1] == 'L' else ('b' if db[:1] == 'W' or da[:1] == 'L' else None)
            if w:
                d['winner'], d['status'] = w, 'CONFIRMED'
                d['note'] = (d['note'] + '; decision from the official FTN result sheet').strip('; ')
SKIP = {'Mile High pt 1 - 2023': 'Paul: ignore (no matchups available)'}


def rel(p):
    for base, tag in ((SRC + '/', 'source_pdfs/'), (NEW + '/', 'new-sources/'), ('/workspace/npte-rankings/', '')):
        if p.startswith(base):
            return tag + p[len(base):]
    return p


# ============================================================== site data / names
SITE = load_site()
NAME_ALIASES = {k.lower(): v for k, v in SITE['name_aliases'].items()}
SCHOOL_ALIASES = {k.lower(): v for k, v in SITE['school_aliases'].items()}


def canon(n):
    n = clean_name(n)
    n = re.sub(r'\s+(they/them|he/him|she/her|she/they|he/they)$', '', n, flags=re.I)
    return NAME_ALIASES.get(n.lower().strip(), n.strip())


def canon_school(s):
    s = (s or '').strip()
    return SCHOOL_ALIASES.get(s.lower(), s)


SITE_ROWS = defaultdict(list)
for r in SITE['logs']:
    names = [canon(r.get('Debater 1') or ''), canon(r.get('Debater 2') or '')]
    r = dict(r, _names=[n for n in names if n], _school=canon_school(r.get('School')))
    SITE_ROWS[r['Tournament']].append(r)


def name_sim(a, b):
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return 0
    if ka == kb:
        return 2.0
    pa, pb = ka.split(), kb.split()
    if pa[-1] == pb[-1] and pa[0][:1] == pb[0][:1]:
        return 1.6
    r = difflib.SequenceMatcher(None, ka, kb).ratio()
    if r >= 0.85:
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


def team_score(names, row):
    used, s, detail = set(), 0, []
    for n in names:
        best = (0, None)
        for j, m in enumerate(row['_names']):
            if j not in used:
                v = name_sim(n, m)
                if v > best[0]:
                    best = (v, j)
        if best[1] is not None and best[0] > 0:
            used.add(best[1]); s += best[0]
            detail.append((n, row['_names'][best[1]], best[0]))
    return s, detail


UNCERTAIN = []          # (tournament, source team, site team, reason)
NAME_VARIANTS = defaultdict(set)   # debater_id -> {(source spelling, tournament)}
NOT_ON_SITE = []        # (tournament, team)


class Resolver:
    def __init__(self, tournament):
        self.t = tournament
        self.rows = SITE_ROWS.get(tournament, [])
        self.cache = {}

    def __call__(self, src):
        """src: {'school','names','code'} -> resolved team dict."""
        if src is None:
            return None
        names = [canon(n) for n in (src.get('names') or []) if n and clean_name(n)]
        ck = (src.get('code') or '') + '|' + '|'.join(names) + '|' + (src.get('school') or '')
        if ck in self.cache:
            return self.cache[ck]
        best, second = None, None
        for r in self.rows:
            s, det = team_score(names, r)
            s += 0.3 * school_sim(src.get('school') or src.get('code') or '', r['_school'] or r.get('Team', ''))
            if best is None or s > best[0]:
                best, second = (s, r, det), best
            elif second is None or s > second[0]:
                second = (s, r, det)
        res = None
        need = 2.6 if len(names) >= 2 else 1.3
        if best and best[0] >= need and (second is None or best[0] - second[0] > 0.5):
            r = best[1]
            res = {'names': list(r['_names']), 'school': r['_school'], 'site': True, 'site_row': r}
            for n, m, v in best[2]:
                if v < 2.0:
                    UNCERTAIN.append((self.t, ' & '.join(names), ' & '.join(r['_names']), f'"{n}" matched to site name "{m}" (similarity {v})'))
            if len(names) < len(r['_names']) and names:
                UNCERTAIN.append((self.t, ' & '.join(names) or src.get('code'), ' & '.join(r['_names']), 'source lists fewer debaters than the site'))
        elif not names and src.get('code'):
            # placeholder team (block not parsed): match by school + code initials
            code = src['code'].split()[-1]
            used = {id(v['site_row']) for v in self.cache.values() if v.get('site_row')}
            c = [r for r in self.rows if len(r['_names']) == len(code) and id(r) not in used and
                 sorted(x.split()[-1][0].upper() for x in r['_names']) == sorted(code.upper())]
            if len(c) > 1:
                c = [r for r in c if school_sim(src['code'], r['_school']) > 0.7] or c
            if len(c) == 1:
                r = c[0]
                res = {'names': list(r['_names']), 'school': r['_school'], 'site': True, 'site_row': r}
                UNCERTAIN.append((self.t, src['code'], ' & '.join(r['_names']), 'team block missing in source; matched by school + code initials'))
        elif best and best[0] >= 1.3 and (second is None or best[0] - second[0] > 0.5):
            r = best[1]
            res = {'names': list(r['_names']), 'school': r['_school'], 'site': True, 'site_row': r}
            UNCERTAIN.append((self.t, ' & '.join(names), ' & '.join(r['_names']), 'only one debater matched the site team'))
        if res is None:
            res = {'names': names, 'school': canon_school(src.get('school') or ''), 'site': False, 'site_row': None}
            if names:
                NOT_ON_SITE.append((self.t, ' & '.join(names), src.get('school') or src.get('code') or ''))
        for n, sn in zip(sorted(names, key=key), sorted(res['names'], key=key)):
            pass
        for n in src.get('names') or []:
            if n and clean_name(n):
                cn = canon(n)
                tgt = cn
                if res['site']:
                    m = max(res['names'], key=lambda x: name_sim(cn, x))
                    tgt = m
                NAME_VARIANTS[tgt].add((clean_name(n), self.t))
        res['code'] = src.get('code') or ''
        res['src_school'] = src.get('school') or ''
        self.cache[ck] = res
        return res


# ============================================================== per-source loaders -> raw debates
def mk(round_, rtype, a, b, side_a, winner, ballots='', judges=(), status='CONFIRMED', note='', order=None):
    return {'round': round_, 'round_type': rtype, 'a': a, 'b': b, 'side_a': side_a, 'winner': winner,
            'ballots': ballots, 'judges': list(judges), 'status': status, 'note': note, 'order': order}


def load_tabroom(t):
    fn, ev = TAB_FILES.get(t, (t + '.json', None))
    path = fn if fn.startswith('/') else TB + fn
    if not os.path.exists(path):   # not yet in source_pdfs/ (added by PR #3): use the raw Tabroom API copy in NEW
        base = os.path.splitext(os.path.basename(path))[0]
        for alt in (base + ' (Tabroom raw).json', base + '.json'):
            if os.path.exists(os.path.join(NEW, alt)):
                path = os.path.join(NEW, alt)
                break
    if ev is None:   # choose the event with the best overlap with the site's team list
        d = json.load(open(path))
        evs = [e for c in d.get('categories', []) for e in c.get('events', []) if e.get('rounds')]
        site_last = {key(n).split()[-1] for r in SITE_ROWS[t] for n in r['_names'] if key(n)}
        best = None
        for e in evs:
            try:
                deb, meta = p_tabroom.parse(path, e.get('abbr') or e.get('name'))
            except Exception:
                continue
            last = {key(n).split()[-1] for en in meta['entries'].values() for n in en['names'] if key(n)}
            ov = len(last & site_last) * 1000 + len(deb)
            if best is None or ov > best[0]:
                best = (ov, e.get('abbr') or e.get('name'))
        ev = best[1]
    deb, meta = p_tabroom.parse(path, ev)
    out = []
    for x in deb:
        a = {'school': x['a'].get('school'), 'names': x['a'].get('names'), 'code': x['a'].get('code'), 'tab_id': x['a'].get('id')}
        b = None if x['b'] is None else {'school': x['b'].get('school'), 'names': x['b'].get('names'), 'code': x['b'].get('code'), 'tab_id': x['b'].get('id')}
        out.append(mk(x['round'], x['round_type'], a, b, x['side_a'], x['winner'], x['ballots'], x['judges'], x['status'], x['note'],
                      order=x['round_order']))
    meta['event_used'] = ev
    return out, rel(path) + f' [event {ev}]', meta, []


def load_mound24():
    _, meta = p_tabroom.parse(TB + 'Mound High pt1 - 2024.json')
    by_code = {e['code']: e for e in meta['entries'].values()}
    out, issues = [], []
    for r in csv.DictReader(open(MOUND24)):
        if not r['aff']:
            issues.append(f"{r['round']}: {r['reasoning']}")
            continue
        rnd = {'Octs': 'Octos', 'Finals': 'Final'}.get(r['round'], r['round'])
        rtype = 'prelim' if rnd.startswith('R') else 'elim'
        def T(c):
            e = by_code.get(c)
            return {'school': e['school'], 'names': e['names'], 'code': c} if e else None
        if r['neg'] == 'BYE':
            out.append(mk(rnd, rtype, T(r['aff']), None, None, 'a', status='BYE', note=r['reasoning']))
            continue
        if ' or ' in r['neg']:
            issues.append(f"{rnd}: {r['aff']} vs {r['neg']} - opponent ambiguous in accepted CSV; not a usable debate")
            out.append(mk(rnd, rtype, T(r['aff']), {'school': '', 'names': [], 'code': r['neg']}, None,
                          'a' if r['winner'] == r['aff'] else None, status='UNKNOWN', note=r['reasoning'] + ' (opponent ambiguous)'))
            continue
        w = 'a' if r['winner'] == r['aff'] else ('b' if r['winner'] == r['neg'] else None)
        judges = [' '.join(reversed([p.strip() for p in j.split(',')])) for j in r['judges'].split(';') if j.strip()]
        side = 'Aff' if rtype == 'prelim' or r['status'] == 'CONFIRMED' else None
        out.append(mk(rnd, rtype, T(r['aff']), T(r['neg']), side, w, '', judges, r['status'], r['reasoning']))
    return out, rel(MOUND24) + ' (accepted as is)', {'locked': True}, issues


BRACKET_OVR = {'Mile High pt 2 - 2023': os.path.join(HERE, 'inputs', 'mile_high_pt2_2023.csv'),
               'GGI - 2025': os.path.join(HERE, 'inputs', 'ggi_2025.csv')}
ORD = {'Octos': 102, 'Quarters': 103, 'Semis': 104, 'Final': 105}


def apply_bracket_ovr(t, raw, meta):
    """Reconstructed elims from Tabroom bracket pages + site elim records (tabroom-brackets/)."""
    lines = open(BRACKET_OVR[t]).read().splitlines()
    first = lines[0].split(',')[1]
    for d in raw:   # the API's lone elim round is the first elim round, not the final
        if d['round_type'] == 'elim':
            d['round'], d['order'] = first, ORD[first]
    by_code = {e['code']: e for e in meta['entries'].values()}
    T = lambda c: {'school': by_code[c]['school'], 'names': by_code[c]['names'], 'code': c}
    for r in csv.DictReader(lines[1:]):
        rnd = r['round']
        if ' or ' in r['neg']:
            raw.append(mk(rnd, 'elim', T(r['aff']), {'school': '', 'names': [], 'code': r['neg']}, None, 'a',
                          status='UNKNOWN', note=r['reasoning'] + ' (opponent ambiguous)', order=ORD[rnd]))
            continue
        w = 'a' if r['winner'] == r['aff'] else ('b' if r['winner'] == r['neg'] else None)
        raw.append(mk(rnd, 'elim', T(r['aff']), T(r['neg']), None, w, '', (), r['status'], r['reasoning'], order=ORD[rnd]))
    return raw


def load_ftn(t):
    fn = FTN_FILES.get(t, t + '.pdf')
    deb, info = p_ftn.parse(FT + fn)
    out = []
    for x in deb:
        a = {'school': x['a']['school'], 'names': x['a']['names'], 'code': x['a']['code']}
        b = None if x['b'] is None else {'school': x['b'].get('school', ''), 'names': x['b'].get('names', []), 'code': x['b'].get('code', '')}
        st = x['status']
        if x['winner'] is None and st == 'CONFIRMED':
            st = 'UNKNOWN'
        out.append(mk(x['round'], x['round_type'], a, b, x['side_a'], x['winner'], x.get('ballots', ''), x['judges'], st, x['note'],
                      order=x['round_order']))
    return out, rel(FT + fn), {}, info['issues']


def load_sw(t):
    grid, elim, ocr, mode = SW_FILES[t]
    site_last = {key(n).split()[-1] for r in SITE_ROWS[t] for n in r['_names'] if key(n)}
    if mode == 'tables':
        teams, recs, elims, iss, div = p_sw.parse_tables(grid, elim)
    else:
        teams, recs, elims, iss, div = p_sw.parse(grid, elim, ocr=ocr, site_names=site_last)
    T = lambda i: None if i is None else {'school': teams[i]['school_text'], 'names': teams[i]['names'], 'code': teams[i]['code']}
    out = []
    for k, r in sorted(recs.items(), key=lambda kv: (kv[1]['rn'], kv[0])):
        if r.get('status') == 'BYE':
            out.append(mk(r['round'], 'prelim', T(r['a']), None, None, 'a', status='BYE'))
            continue
        w = None if r.get('win_a') is None else ('a' if r['win_a'] else 'b')
        note = '' if r.get('seen') == 2 else 'only one team\'s grid cell parsed'
        if ocr:
            note = ('OCR; ' + note).strip('; ')
        out.append(mk(r['round'], 'prelim', T(r['a']), T(r['b']), r.get('side_a'), w, '1-0' if w else '', r.get('judges', []),
                      'CONFIRMED' if w else 'UNKNOWN', note))
    for lbl, wi, li, sw_, sl, ball in elims:
        if li is None:
            out.append(mk(lbl, 'elim', T(wi), None, None, 'a', status='BYE'))
            continue
        side = None
        if sw_:
            side = 'Aff' if sw_.lower() in ('aff', 'gov') else 'Neg'
        elif sl:
            side = 'Neg' if sl.lower() in ('aff', 'gov') else 'Aff'
        out.append(mk(lbl, 'elim', T(wi), T(li), side, 'a', ball or '', [], 'CONFIRMED', 'OCR' if (ocr and (mode == 'grid' or elim)) else ''))
    src = rel(grid) + (' + ' + rel(elim) if elim else '') + (' (OCR)' if ocr else '') + f' [division {div}]'
    return out, src, {'list_order': True}, iss


# ============================================================== post-processing
def rnd_order(d):
    if d['round_type'] == 'prelim':
        m = re.search(r'(\d+)', d['round'])
        return int(m.group(1)) if m else 0
    return 100 + (ELIM_ORDER.index(d['round']) if d['round'] in ELIM_ORDER else 9)


def tkey(t):
    return None if t is None else tuple(sorted(key(n) for n in t['names'])) or ('?' + t.get('code', ''),)


def same_school(a, b):
    if a is None or b is None:
        return False
    sa, sb = a.get('school') or a.get('src_school'), b.get('school') or b.get('src_school')
    return bool(sa and sb) and key(canon_school(sa)) == key(canon_school(sb))


def site_elim(t):
    r = t and t.get('site_row')
    return None if not r else (r.get('Elim Wins') or 0, r.get('Elim Losses') or 0)


def site_prelim(t):
    r = t and t.get('site_row')
    return None if not r else (r.get('Prelim Wins') or 0, r.get('Prelim Losses') or 0)


def resolve_unknowns(debs, notes):
    """Fill unknown prelim winners from the site's per-team prelim W-L (only when forced)."""
    for _ in range(5):
        changed = False
        by_team = defaultdict(list)
        for d in debs:
            if d['round_type'] == 'prelim' and d['b'] is not None and d['status'] in ('CONFIRMED', 'INFERRED', 'UNKNOWN'):
                by_team[tkey(d['a'])].append((d, 'a')); by_team[tkey(d['b'])].append((d, 'b'))
        for tk, lst in by_team.items():
            unk = [(d, s) for d, s in lst if d['winner'] is None]
            if not unk:
                continue
            sp = site_prelim(lst[0][0][lst[0][1]])
            if not sp:
                continue
            byes = sum(1 for d in debs if d['round_type'] == 'prelim' and d['b'] is None and tkey(d['a']) == tk)
            wins_known = sum(1 for d, s in lst if d['winner'] == s)
            for bye_w in (byes, 0):
                need = sp[0] - wins_known - bye_w
                if need == 0 or need == len(unk):
                    for d, s in unk:
                        d['winner'] = s if need else ('b' if s == 'a' else 'a')
                        d['status'] = 'INFERRED'
                        d['note'] = (d['note'] + '; winner inferred from site prelim record').strip('; ')
                        if not d['ballots']:
                            d['ballots'] = '1-0'
                    changed = True
                    break
        if not changed:
            break


def bracket_positions(n):
    order = [1, 2]
    while len(order) < n:
        m = len(order) * 2
        order = [x for s in order for x in (s, m + 1 - s)]
    return {s: i for i, s in enumerate(order)}


def complete_elims(debs, meta, t, notes):
    """Fill unknown elim winners and missing later elim rounds from later appearances and the site's elim records."""
    el = [d for d in debs if d['round_type'] == 'elim']
    if not el:
        return
    rows = SITE_ROWS.get(t, [])
    if not rows:
        return
    n_rounds = max((r.get('Elim Wins') or 0) for r in rows)   # champion's elim wins (byes included) = number of elim rounds
    present = sorted({d['round'] for d in el}, key=lambda r: ELIM_ORDER.index(r) if r in ELIM_ORDER else 9)
    later_teams = defaultdict(set)
    for d in el:
        for s in ('a', 'b'):
            if d[s] is not None:
                later_teams[d['round']].add(tkey(d[s]))

    def appears_after(tk, rnd):
        i = present.index(rnd)
        return any(tk in later_teams[r] for r in present[i + 1:])

    # 1. unknown winners
    for d in el:
        if d['b'] is None or d['winner'] is not None:
            continue
        ka, kb = tkey(d['a']), tkey(d['b'])
        aa, ab = appears_after(ka, d['round']), appears_after(kb, d['round'])
        w = None
        how = ''
        if aa != ab:
            w, how = ('a' if aa else 'b'), 'winner appears in the next elim round'
        else:
            ea, eb = site_elim(d['a']), site_elim(d['b'])
            if ea and eb and ea[0] != eb[0]:
                w, how = ('a' if ea[0] > eb[0] else 'b'), 'winner inferred from site elim records'
            elif ea and eb and ea[1] != eb[1]:
                w, how = ('a' if ea[1] < eb[1] else 'b'), 'winner inferred from site elim losses'
        if w:
            d['winner'] = w
            if d['status'] in ('CONFIRMED', 'UNKNOWN'):
                d['status'] = 'INFERRED'
            d['note'] = (d['note'] + '; ' + how).strip('; ')
            d['ballots'] = d['ballots'] or ''
    # 2. missing later rounds
    if meta.get('locked'):
        return
    have = len(present)
    first_idx = ELIM_ORDER.index(present[-1]) if present[-1] in ELIM_ORDER else None
    if first_idx is None or have >= n_rounds or present[-1] == 'Final':
        return
    last = [d for d in el if d['round'] == present[-1]]
    adv = []
    for d in last:
        if d['winner'] is None:
            notes.append(f'{t}: cannot complete elims, {present[-1]} winner unknown')
            return
        adv.append(d[d['winner']])
    seeds = meta.get('seeds') or {}
    entrants = []
    for d in el:
        for s in ('a', 'b'):
            if d[s] is not None and tkey(d[s]) not in [tkey(x) for x in entrants]:
                entrants.append(d[s])
    rnd_i = ELIM_ORDER.index(present[-1])
    while len(adv) > 1 and rnd_i + 1 < len(ELIM_ORDER):
        rnd_i += 1
        rname = ELIM_ORDER[rnd_i]
        pairs = []
        if len(adv) == 2:
            pairs = [(adv[0], adv[1])]
        elif seeds and False:   # seed-bracket pairing disabled: it failed validation on complete Tabroom brackets
            sd = sorted(entrants, key=lambda x: seeds.get(x.get('tab_id'), 999))
            nbr = 1
            while nbr < len(sd):
                nbr *= 2
            pos = bracket_positions(nbr)
            es = {tkey(x): i + 1 for i, x in enumerate(sd)}
            depth = ELIM_ORDER.index(rname) - ELIM_ORDER.index(present[0])  # rounds after the first elim round
            groups = defaultdict(list)
            for x in adv:
                groups[pos[es[tkey(x)]] >> (depth + 1)].append(x)
            if all(len(g) == 2 for g in groups.values()):
                pairs = [tuple(g) for _, g in sorted(groups.items())]
        elif meta.get('list_order'):   # SpeechWire elim results list sections in bracket order
            if len(adv) % 2 == 0:
                pairs = [(adv[i], adv[i + 1]) for i in range(0, len(adv), 2)]
        if not pairs:
            notes.append(f'{t}: {rname} and later missing from source; pairings not inferable (left out)')
            return
        nxt = []
        for x, y in pairs:
            ex, ey = site_elim(x), site_elim(y)
            w = None
            if ex and ey:
                if ex[0] != ey[0]:
                    w = 'a' if ex[0] > ey[0] else 'b'
                elif ex[1] != ey[1]:
                    w = 'a' if ex[1] < ey[1] else 'b'
            st = 'WALKOVER' if same_school(x, y) else ('INFERRED' if w else 'UNKNOWN')
            d = mk(rname, 'elim', x, y, None, w, '', [], st,
                   'round missing from source; pairing from bracket/advancement, winner from site elim records')
            d['generated'] = True
            debs.append(d)
            notes.append(f'{t}: generated {rname} {" & ".join(x["names"])} vs {" & ".join(y["names"])} ({st})')
            if w is None:
                return
            nxt.append(x if w == 'a' else y)
        adv = nxt


def check_bracket_inference(debs, meta):
    """On a complete Tabroom bracket, test that the seed-based pairing reproduces the real later rounds."""
    seeds = meta.get('seeds') or {}
    el = [d for d in debs if d['round_type'] == 'elim']
    present = sorted({d['round'] for d in el}, key=lambda r: ELIM_ORDER.index(r) if r in ELIM_ORDER else 9)
    if not seeds or len(present) < 2:
        return None
    entrants = []
    for d in el:
        for s in ('a', 'b'):
            if d[s] is not None and tkey(d[s]) not in [tkey(x) for x in entrants]:
                entrants.append(d[s])
    sd = sorted(entrants, key=lambda x: seeds.get(x.get('tab_id'), 999))
    nbr = 1
    while nbr < len(sd):
        nbr *= 2
    pos = bracket_positions(nbr)
    es = {tkey(x): i + 1 for i, x in enumerate(sd)}
    ok = bad = 0
    for i, r in enumerate(present[1:], 1):
        for d in el:
            if d['round'] == r and d['b'] is not None:
                ga = pos[es[tkey(d['a'])]] >> (i + 1)
                gb = pos[es[tkey(d['b'])]] >> (i + 1)
                if ga == gb: ok += 1
                else: bad += 1
    return ok, bad


# ============================================================== main build
def main():
    cal = list(csv.DictReader(open(CAL)))
    cal.sort(key=lambda r: (r['season'], int(r['order_in_season'])))
    all_debs, coverage, notes, parse_issues = [], [], [], {}
    bracket_checks = {}
    for gi, c in enumerate(cal, 1):
        t, season = c['tournament'], c['season']
        if t in SKIP:
            coverage.append({'season': season, 'tournament': t, 'platform': c['platform'], 'source': '', 'status': 'SKIPPED: ' + SKIP[t]})
            continue
        try:
            if t == 'Mound High pt 1 - 2024':
                raw, src, meta, iss = load_mound24()
            elif c['platform'] == 'Tabroom':
                raw, src, meta, iss = load_tabroom(t)
                if t in BRACKET_OVR:
                    raw = apply_bracket_ovr(t, raw, meta)
                    src += ' + ' + 'tabroom-brackets/' + os.path.basename(BRACKET_OVR[t])
            elif c['platform'] == 'FTN':
                raw, src, meta, iss = load_ftn(t)
            else:
                raw, src, meta, iss = load_sw(t)
        except Exception as e:
            import traceback; traceback.print_exc()
            coverage.append({'season': season, 'tournament': t, 'platform': c['platform'], 'source': '', 'status': f'FAILED: {e}'})
            continue
        parse_issues[t] = iss
        R = Resolver(t)
        for d in raw:
            d['a'] = R(d['a'])
            d['b'] = R(d['b']) if d['b'] is not None else None
            # opponent lists with no names (e.g. ambiguous) stay unusable
            if d['b'] is not None and not d['b']['names'] and d['status'] != 'UNKNOWN':
                d['status'] = 'UNKNOWN'
        if c['platform'] == 'FTN':
            ftn_official(raw, t, notes)
            for d in raw:  # manual override: NCFA 2022 R5 W&W missing from cache/ftn_live.json
                if t == 'NCFA Spring Champs - 2022' and d['round'] == 'R5' and d['b'] is not None and \
                        {'Joseph Berck', 'Arshita Sandhiparthi'} <= set(d['a']['names']) | set(d['b']['names']):
                    d['status'], d['winner'] = 'DOUBLE_WIN', None
                    d['note'] = 'manual override: double win (W&W) per official FTN sheet; not in cache/ftn_live.json'
                    notes.append(f'{t} R5: double win (manual override)')
        # same-school elim = walkover; same-school prelim flagged
        for d in raw:
            if d['b'] is not None and same_school(d['a'], d['b']):
                if d['round_type'] == 'elim':
                    d['status'] = 'WALKOVER'
                    d['note'] = (d['note'] + '; same-school elim meeting (walkover, not a debate)').strip('; ')
                    if d['winner'] is None:
                        ea, eb = site_elim(d['a']), site_elim(d['b'])
                        if ea and eb and ea != eb:
                            d['winner'] = 'a' if (ea[0], -ea[1]) > (eb[0], -eb[1]) else 'b'
                else:
                    notes.append(f"{t} {d['round']}: same-school prelim {d['a']['names']} vs {d['b']['names']}")
        if c['platform'] == 'Tabroom' and not meta.get('locked'):
            bc = check_bracket_inference(raw, meta)
            if bc:
                bracket_checks[t] = bc
        if not meta.get('locked'):
            resolve_unknowns(raw, notes)
            complete_elims(raw, meta, t, notes)
        for d in raw:
            d.update(season=season, tournament=t, tourn_order=gi, source=src, platform=c['platform'])
            d['round_order'] = rnd_order(d)
        all_debs.extend(raw)
        coverage.append({'season': season, 'tournament': t, 'platform': c['platform'], 'source': src, 'status': 'parsed'})
        print(f'{t:40s} {len(raw):4d} debates  issues={len(iss)}', file=sys.stderr)

    all_debs.sort(key=lambda d: (d['tourn_order'], d['round_order']))
    apply_person_merge(all_debs)
    return all_debs, coverage, notes, parse_issues, bracket_checks


def team_label(t):
    return ' & '.join(t['names']) if t and t['names'] else (t or {}).get('code', '')


def pid(t):
    return ' & '.join(sorted(t['names'], key=lambda n: key(n).split()[-1] if key(n) else n))


SITE_ERRORS = {   # (tournament, last names) -> explanation, from official-source checks
    ('Rice University Classic - 2024', frozenset({'carrillo', 'gallon'})): 'SITE ERROR: Tabroom API (re-pulled 2026-11-02) has Anthony Carrillo & Gallon 0-1 in elims (lost octos to Surya/Sanderfer); site 2-1 looks swapped with Holden Carrillo & Lan',
    ('Rice University Classic - 2024', frozenset({'carrillo', 'lan'})): 'SITE ERROR: Tabroom API (re-pulled 2026-11-02) has Holden Carrillo & Lan 2-1 in elims (won octos + quarters, lost semis); site 1-1 looks swapped with Anthony Carrillo & Gallon',
}


def explain(t, row, sp, se, r, ok_p, ok_e, pw_opts):
    out = []
    if not ok_p:
        if t in SITE_LOSSES_4_MINUS_W and sp[0] in pw_opts and sp[1] == max(0, 4 - sp[0]):
            out.append(f'SITE ERROR: official FTN sheet has 5 prelims ({r[0]}-{r[1]}); site stores losses as 4 - wins')
        elif t == 'Mound High pt 1 - 2024':
            out.append('accepted Mound pt1 CSV: R1-R3/R5 pairings unknown by design')
    k = SITE_ERRORS.get((t, _lastset(row['_names'])))
    if k:
        out.append(k)
    return '; '.join(out)


def write_outputs(debs, coverage, notes, parse_issues, bracket_checks):
    # ---------------- matchups.csv
    rows = []
    for d in debs:
        a, b = d['a'], d['b']
        if d['side_a'] == 'Neg' and b is not None:
            aff, neg, wa = b, a, {'a': 'b', 'b': 'a'}.get(d['winner'])
        else:
            aff, neg, wa = a, b, d['winner']
        side_known = d['side_a'] is not None
        winner = '' if wa is None else team_label(aff if wa == 'a' else neg)
        rows.append({
            'season': d['season'], 'tournament': d['tournament'], 'tourn_order': d['tourn_order'], 'round': d['round'],
            'round_order': d['round_order'], 'round_type': d['round_type'],
            'aff_team': (aff['school'] + ' ' + aff['code']).strip() if aff else '', 'aff_debaters': team_label(aff),
            'neg_team': ((neg['school'] + ' ' + neg['code']).strip() if neg else ('BYE' if d['status'] == 'BYE' else '')),
            'neg_debaters': team_label(neg) if neg else '',
            'sides_known': 'Y' if side_known else 'N', 'winner': winner, 'ballots': d['ballots'], 'judges': '; '.join(d['judges']),
            'status': d['status'], 'note': d['note'], 'source': d['source']})
    cols = ['season', 'tournament', 'tourn_order', 'round', 'round_order', 'round_type', 'aff_team', 'aff_debaters', 'neg_team',
            'neg_debaters', 'sides_known', 'winner', 'ballots', 'judges', 'status', 'note', 'source']
    with open(os.path.join(HERE, 'matchups.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)

    # ---------------- debater ids
    all_names = Counter()
    on_site = set()
    for d in debs:
        for s in ('a', 'b'):
            t = d[s]
            if t:
                for n in t['names']:
                    all_names[n] += 1
                    if t['site']:
                        on_site.add(n)
    names = sorted(all_names, key=lambda n: key(n))
    dup = defaultdict(list)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            kx, ky = key(x), key(y)
            if not kx or not ky:
                continue
            r = difflib.SequenceMatcher(None, kx, ky).ratio()
            px, py = kx.split(), ky.split()
            if r >= 0.85 or (px[-1] == py[-1] and px[0][:2] == py[0][:2]) or (px[0] == py[0] and difflib.SequenceMatcher(None, px[-1], py[-1]).ratio() > 0.8):
                dup[x].append(y); dup[y].append(x)
    with open(os.path.join(HERE, 'debater_ids.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['debater_id', 'on_site', 'debates', 'source_spellings', 'flag'])
        for n in names:
            sp = sorted({v for a in [n] + sorted(MERGED_SEEN.get(n, ())) for v, _ in NAME_VARIANTS.get(a, set()) if v != n} | MERGED_SEEN.get(n, set()))
            flag = ''
            if MERGED_SEEN.get(n):
                flag = 'MERGED (confirmed by Paul): ' + '; '.join(sorted(MERGED_SEEN[n]))
            if dup.get(n):
                why = [NOT_MERGED.get(tuple(sorted((n, y))), '') for y in dup[n]]
                flag = (flag + ' | ' if flag else '') + 'POSSIBLE SAME PERSON AS: ' + '; '.join(dup[n]) + ' (not merged' + ('' if not any(why) else ': ' + '; '.join(x for x in why if x)) + ')'
            w.writerow([n, 'Y' if n in on_site else 'N', all_names[n], '; '.join(sp), flag])
    with open(os.path.join(HERE, 'debater_aliases.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['alias', 'canonical_debater_id', 'basis'])
        for a, c in sorted(PERSON_MERGE.items(), key=lambda x: x[1]):
            w.writerow([a, c, 'confirmed same person by Paul 2026-11-02'])
        for (a, b), why in NOT_MERGED.items():
            w.writerow([a + ' / ' + b, '(kept separate)', why])
    with open(os.path.join(HERE, 'uncertain_matches.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['tournament', 'source_team', 'site_team', 'reason'])
        for r in sorted(set(UNCERTAIN)):
            w.writerow(r)
    with open(os.path.join(HERE, 'teams_not_on_site.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['tournament', 'debaters', 'source_school_or_code'])
        for r in sorted(set(NOT_ON_SITE)):
            w.writerow(r)

    # ---------------- ELO
    hist = []
    def run(scope_fn, scope_name):
        P, D = {}, {}
        stats_p = defaultdict(lambda: {'games': 0, 'W': 0, 'L': 0, 'peak': ELO_START, 'schools': set(), 'last': ''})
        stats_d = defaultdict(lambda: {'games': 0, 'W': 0, 'L': 0, 'peak': ELO_START, 'schools': set(), 'last': ''})
        cur_scope = None
        D_start = None
        for i, d in enumerate(debs):
            if d['status'] not in ELO_STATUSES or d['b'] is None or d['winner'] is None or not d['a']['names'] or not d['b']['names']:
                continue
            sc = scope_fn(d)
            if sc != cur_scope:
                if scope_name == 'season':
                    # regression to the mean between seasons (not a hard reset)
                    D = {n: ELO_START + SEASON_CARRY_R * (r - ELO_START) for n, r in D.items()}
                    D_start = dict(D)
                    P = {}
                else:
                    D_start = None
                cur_scope = sc
            A, B = d['a'], d['b']
            pa, pb = pid(A), pid(B)
            for p_, t_ in ((pa, A), (pb, B)):
                if p_ not in P:   # partnership start = average of its debaters' (carried-over) ratings
                    base = D_start if D_start is not None else D
                    P[p_] = sum(base.get(n, ELO_START) for n in t_['names']) / len(t_['names'])
                    stats_p[(sc, p_)]['start'] = P[p_]
            ra, rb = P[pa], P[pb]
            sa = 1.0 if d['winner'] == 'a' else 0.0
            if BALLOT_WEIGHT and re.match(r'^\d+-\d+$', d['ballots'] or ''):
                x, y = map(int, d['ballots'].split('-'))
                if x + y > 1:
                    share = x / (x + y)
                    sa = share if d['winner'] == 'a' else 1 - share
            K = ELO_K if d['round_type'] == 'prelim' else ELO_K_ELIM
            ea = 1 / (1 + 10 ** ((rb - ra) / 400))
            P[pa] = ra + K * (sa - ea)
            P[pb] = rb + K * ((1 - sa) - (1 - ea))
            # debaters vs opposing team's average debater rating (pre-debate)
            da = {n: D.get(n, ELO_START) for n in A['names']}
            db = {n: D.get(n, ELO_START) for n in B['names']}
            avg_a, avg_b = sum(da.values()) / len(da), sum(db.values()) / len(db)
            for names_, own, opp_avg, s in ((A['names'], da, avg_b, sa), (B['names'], db, avg_a, 1 - sa)):
                for n in names_:
                    e = 1 / (1 + 10 ** ((opp_avg - own[n]) / 400))
                    D[n] = own[n] + K * (s - e)
            for t, p_, r0, s in ((A, pa, ra, sa), (B, pb, rb, 1 - sa)):
                st = stats_p[(sc, p_)]
                st['games'] += 1; st['W'] += s >= 0.5; st['L'] += s < 0.5
                st['peak'] = max(st.get('pk', st.get('start', ELO_START)), P[p_]); st['pk'] = st['peak']; st['rating'] = P[p_]; st['schools'].add(t['school']); st['last'] = d['tournament']
                hist.append([scope_name, sc, 'partnership', p_, d['season'], d['tournament'], d['round'], pid(B if t is A else A),
                             'W' if s >= 0.5 else 'L', round(r0, 1), round(P[p_], 1)])
            for t, own, s, opp in ((A, da, sa, B), (B, db, 1 - sa, A)):
                for n in t['names']:
                    st = stats_d[(sc, n)]
                    if 'start' not in st:
                        st['start'] = own[n]; st['pk'] = own[n]
                    st['games'] += 1; st['W'] += s >= 0.5; st['L'] += s < 0.5
                    st['peak'] = max(st['pk'], D[n]); st['pk'] = st['peak']; st['rating'] = D[n]; st['schools'].add(t['school']); st['last'] = d['tournament']
                    hist.append([scope_name, sc, 'debater', n, d['season'], d['tournament'], d['round'], pid(opp),
                                 'W' if s >= 0.5 else 'L', round(own[n], 1), round(D[n], 1)])
        return stats_p, stats_d
    sp_s, sd_s = run(lambda d: d['season'], 'season')
    sp_a, sd_a = run(lambda d: 'all-time', 'all-time')

    def dump(fn, stats_list, label):
        with open(os.path.join(HERE, fn), 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['scope', 'season', 'rank', label, 'schools', 'rating', 'season_start', 'peak', 'games', 'wins', 'losses', 'last_tournament'])
            for scope, stats in stats_list:
                bys = defaultdict(list)
                for (sc, ent), st in stats.items():
                    bys[sc].append((ent, st))
                for sc in sorted(bys):
                    lst = sorted(bys[sc], key=lambda x: -x[1]['rating'])
                    for rk, (ent, st) in enumerate(lst, 1):
                        w.writerow([scope, sc, rk, ent, '; '.join(sorted(s for s in st['schools'] if s)), round(st['rating'], 1),
                                    round(st.get('start', ELO_START), 1), round(st['peak'], 1), st['games'], st['W'], st['L'], st['last']])
    dump('elo_partnerships.csv', [('season', sp_s), ('all-time', sp_a)], 'partnership')
    dump('elo_debaters.csv', [('season', sd_s), ('all-time', sd_a)], 'debater')
    with open(os.path.join(HERE, 'elo_history.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['scope', 'scope_key', 'entity_type', 'entity', 'season', 'tournament', 'round', 'opponent_partnership', 'result',
                    'rating_before', 'rating_after'])
        w.writerows(hist)

    # ---------------- validation vs site W-L
    val = []
    by_t = defaultdict(list)
    for d in debs:
        by_t[d['tournament']].append(d)
    for t, ds in by_t.items():
        rec = defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # pw pl ew el prelim_byes elim_byes/walkover wins
        rowmap = {}
        for d in ds:
            for s in ('a', 'b'):
                tm = d[s]
                if tm is None or not tm.get('site_row'):
                    continue
                k = id(tm['site_row']); rowmap[k] = tm['site_row']
                r = rec[k]
                if d['b'] is None:
                    if d['round_type'] == 'prelim': r[4] += 1
                    else: r[5] += 1
                    continue
                if d['status'] == 'DOUBLE_WIN':
                    r[0] += 1
                    continue
                if d['winner'] is None:
                    continue
                won = d['winner'] == s
                if d['round_type'] == 'prelim':
                    r[0 if won else 1] += 1
                else:
                    if d['status'] == 'WALKOVER' and won:
                        r[5] += 1
                    elif d['status'] == 'WALKOVER':
                        r[3] += 1
                    else:
                        r[2 if won else 3] += 1
        prelim_bye_counts = None
        for row in SITE_ROWS[t]:
            k = id(row)
            r = rec.get(k, [0, 0, 0, 0, 0, 0])
            sp = (row.get('Prelim Wins') or 0, row.get('Prelim Losses') or 0)
            se = (row.get('Elim Wins') or 0, row.get('Elim Losses') or 0)
            pw_opts = {r[0], r[0] + r[4]}
            ew_opts = {r[2], r[2] + r[5], 1 + r[2] if r[5] else r[2]}
            ok_p = sp[0] in pw_opts and sp[1] == r[1]
            ok_e = se[0] in ew_opts and se[1] == r[3]
            parsed = k in rec
            why = ''
            if not (ok_p and ok_e) and parsed:
                why = explain(t, row, sp, se, r, ok_p, ok_e, pw_opts)
            val.append({'season': row['Year'], 'tournament': t, 'team': ' & '.join(row['_names']), 'school': row['_school'],
                        'site_prelim': f'{sp[0]}-{sp[1]}', 'parsed_prelim': f'{r[0]}-{r[1]}' + (f' +{r[4]} bye' if r[4] else ''),
                        'site_elim': f'{se[0]}-{se[1]}', 'parsed_elim': f'{r[2]}-{r[3]}' + (f' +{r[5]} bye/walkover' if r[5] else ''),
                        'match': 'Y' if (ok_p and ok_e) else ('NOT FOUND IN SOURCE' if not parsed else 'N'),
                        'explanation': why})
    with open(os.path.join(HERE, 'validation.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(val[0].keys())); w.writeheader(); w.writerows(val)

    # ---------------- coverage
    cov = []
    vt = defaultdict(list)
    for v in val:
        vt[v['tournament']].append(v)
    for c in coverage:
        t = c['tournament']
        ds = by_t.get(t, [])
        st = Counter(d['status'] for d in ds)
        rows_ = SITE_ROWS.get(t, [])
        exp_p = sum((r.get('Prelim Wins') or 0) + (r.get('Prelim Losses') or 0) for r in rows_) / 2
        exp_e = sum((r.get('Elim Losses') or 0) for r in rows_)
        got_p = sum(1 for d in ds if d['round_type'] == 'prelim' and d['b'] is not None)
        got_e = sum(1 for d in ds if d['round_type'] == 'elim' and d['b'] is not None)
        vv = vt.get(t, [])
        cov.append(dict(c, site_teams=len(rows_), parsed_prelim_debates=got_p, site_prelim_upper_bound=int(exp_p),
                        parsed_elim_debates=got_e, site_elim_losses=exp_e,
                        confirmed=st['CONFIRMED'], inferred=st['INFERRED'], unknown=st['UNKNOWN'], walkover=st['WALKOVER'],
                        forfeit=st['FORFEIT'], bye=st['BYE'],
                        wl_match=sum(1 for v in vv if v['match'] == 'Y'), wl_mismatch=sum(1 for v in vv if v['match'] == 'N'),
                        site_team_not_found=sum(1 for v in vv if v['match'].startswith('NOT')),
                        parse_issues=len(parse_issues.get(t, []))))
    with open(os.path.join(HERE, 'coverage.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(cov[0].keys()) if cov else ['x']); w.writeheader(); w.writerows(cov)
    with open(os.path.join(HERE, 'build_notes.txt'), 'w') as f:
        f.write('# inference / generation notes\n' + '\n'.join(notes) + '\n\n# bracket inference check on complete Tabroom brackets (ok, bad)\n')
        for t, bc in bracket_checks.items():
            f.write(f'{t}: {bc}\n')
        f.write('\n# parse issues by tournament\n')
        for t, iss in parse_issues.items():
            for i in iss:
                f.write(f'{t}: {i}\n')

    write_html(debs, sp_s, sd_s, sp_a, sd_a)
    return rows, cov, val


def write_html(debs, sp_s, sd_s, sp_a, sd_a):
    M = []
    for d in debs:
        if d['b'] is None:
            continue   # byes are not debates
        a, b = d['a'], d['b']
        M.append([d['season'], d['tournament'], d['round'], d['round_type'][0], a['names'], a['school'], b['names'], b['school'],
                  d['side_a'] or '', d['winner'] or '', d['ballots'], '; '.join(d['judges']), d['status'], d['note'], d['tourn_order'], d['round_order'],
                  pid(a) if a['names'] else a.get('code', ''), pid(b) if b['names'] else b.get('code', '')])
    def board(stats):
        out = defaultdict(list)
        for (sc, ent), st in stats.items():
            out[sc].append([ent, '; '.join(sorted(s for s in st['schools'] if s)), round(st['rating'], 1), round(st['peak'], 1), st['games'], st['W'], st['L']])
        return {k: sorted(v, key=lambda x: -x[2]) for k, v in out.items()}
    data = {'m': M, 'bp': board(sp_s), 'bd': board(sd_s), 'ap': board(sp_a)['all-time'] if sp_a else [], 'ad': board(sd_a)['all-time'] if sd_a else [],
            'cfg': {'start': ELO_START, 'k': ELO_K, 'kelim': ELO_K_ELIM, 'ballot_weight': BALLOT_WEIGHT, 'carry': SEASON_CARRY_R}}
    # site data file read by /h2h.html and /elo.html
    os.makedirs(os.path.join(REPO, 'data'), exist_ok=True)
    with open(os.path.join(REPO, 'data', 'elo.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'))


if __name__ == '__main__':
    debs, coverage, notes, parse_issues, bc = main()
    rows, cov, val = write_outputs(debs, coverage, notes, parse_issues, bc)
    import readme
    readme.main({'start': ELO_START, 'k': ELO_K, 'kelim': ELO_K_ELIM, 'carry': SEASON_CARRY_R})
    st = Counter(r['status'] for r in rows)
    print('debate rows:', len(rows), dict(st))

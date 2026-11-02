import csv, json, re, sys, collections
sys.path.insert(0, '.')
from common import key
L = json.load(open('cache/ftn_live.json'))
M = collections.defaultdict(list)
for r in csv.DictReader(open('matchups.csv')):
    M[r['tournament']].append(r)
PERSON = {}
try:
    import build
    PERSON = build.PERSON_MERGE
    canon = build.canon
except Exception:
    canon = lambda n: n

def lastset(names):
    out = set()
    for n in names:
        n = re.sub(r'\(.*?\)', '', n).strip()
        if not n or n in ('_', '__'):
            continue
        k = key(PERSON.get(canon(n), canon(n)))
        if k:
            out.add(k.split()[-1])
    return frozenset(out)

def rd_norm(rd):
    m = re.match(r'Rd (\d+)', rd)
    if m: return 'R' + m.group(1)
    rd = rd.lower()
    for a, b in (('triple', 'Triple Octos'), ('double', 'Double Octos'), ('octo', 'Octos'), ('quarter', 'Quarters'), ('semi', 'Semis'), ('final', 'Final')):
        if a in rd: return b
    return rd

def compare(t):
    live = L[t]; rows = M.get(t, [])
    idx = collections.defaultdict(list)
    for r in rows:
        for s in ('aff_debaters', 'neg_debaters'):
            idx[(r['round'], lastset(r[s].split(' & ')))].append(r)
    issues = []
    for tm in live['teams']:
        me = lastset(tm['names'])
        for rd in tm['rounds']:
            R = rd_norm(rd['rd']); dec = rd['dec'].strip()
            opp = rd['opp']
            oppn = opp.split(' - ', 1)[1].split('&') if ' - ' in opp else []
            os_ = lastset(oppn)
            cand = idx.get((R, me), [])
            if not cand:
                issues.append((t, ' & '.join(tm['names']), R, 'missing in parse', opp, dec)); continue
            r = cand[0]
            mine_side = 'aff' if lastset(r['aff_debaters'].split(' & ')) == me else 'neg'
            other = r['neg_debaters' if mine_side == 'aff' else 'aff_debaters']
            if os_ and lastset(other.split(' & ')) != os_:
                issues.append((t, ' & '.join(tm['names']), R, f'opponent differs: parsed {other!r}', opp, dec))
            won = r['winner'] and lastset(r['winner'].split(' & ')) == me
            lost = r['winner'] and not won
            d0 = dec[:1].upper()
            if d0 == 'W' and not won or d0 == 'L' and not lost:
                issues.append((t, ' & '.join(tm['names']), R, f"decision differs: parsed winner {r['winner']!r} status {r['status']}", opp, dec))
    return issues

if __name__ == '__main__':
    allis = []
    for t in L:
        allis += compare(t)
    c = collections.Counter(i[0] for i in allis)
    for t in L:
        print(f'{t:32s} {c.get(t,0)}')
    with open('cache/ftn_compare.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['tournament', 'team', 'round', 'issue', 'official_opponent', 'official_decision']); w.writerows(allis)

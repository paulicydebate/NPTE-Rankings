"""Tabroom JSON -> debates."""
import json, re
from collections import defaultdict
from common import clean_name, elim_label

PRELIM_TYPES = ('prelim', 'highlow', 'highhigh')


def pick_event(d, want=None):
    evs = [(c, e) for c in d.get('categories', []) for e in c.get('events', []) if e.get('rounds')]
    if want:
        for c, e in evs:
            if e.get('abbr') == want or e.get('name') == want:
                return e
        raise ValueError(want)
    best = None
    for c, e in evs:
        nm = (str(e.get('name')) + ' ' + str(e.get('abbr')) + ' ' + str(c.get('name'))).lower()
        if 'ipda' in nm or 'cx' in nm.split() or 'ndt' in nm or 'ld' in nm.split() or 'card' in nm:
            continue
        n = sum(len(r.get('sections', [])) for r in e['rounds'])
        if best is None or n > best[0]:
            best = (n, e)
    return best[1]


def ballots_text(event):
    best = {}
    for rs in event.get('result_sets', []):
        keys = {k['id']: k for k in rs.get('result_keys', [])}
        for row in rs.get('results', []):
            eid = str(row.get('entry'))
            for v in row.get('values', []):
                k = keys.get(v.get('result_key'))
                if k and k.get('tag') == 'Ballots':
                    t = v.get('value') or ''
                    if len(t) > len(best.get(eid, '')):
                        best[eid] = t
    return best


def round_letters(text):
    """{round_number: (W count, L count)} from Ballots text."""
    out = {}
    for m in re.finditer(r'R(\d+)(.*?)(?=R\d+|$)', text or '', re.S):
        letters = re.findall(r'(?<![A-Za-z])([WL])(?![A-Za-z])', m.group(2))
        if letters:
            out[int(m.group(1))] = (letters.count('W'), letters.count('L'))
    return out


def seeds(event):
    for rs in event.get('result_sets', []):
        if 'seed' in (rs.get('label') or '').lower():
            return {str(r.get('entry')): r.get('rank') for r in rs.get('results', []) if r.get('entry')}
    return {}


def parse(path, event_name=None, round_filter=None):
    d = json.load(open(path))
    ev = pick_event(d, event_name)
    students, entries = {}, {}
    for s in d.get('schools', []):
        for st in s.get('students', []):
            students[str(st['id'])] = st
    for s in d.get('schools', []):
        for en in s.get('entries', []):
            names = []
            for sid in en.get('students', []):
                st = students.get(str(sid))
                if st:
                    names.append(clean_name(f"{st.get('first','')} {st.get('last','')}"))
            entries[str(en['id'])] = {'school': s.get('name', ''), 'names': names, 'code': en.get('code', ''),
                                      'tab_name': en.get('name', ''), 'id': str(en['id'])}
    btext = ballots_text(ev)
    letters = {e: round_letters(t) for e, t in btext.items()}
    rounds = sorted(ev['rounds'], key=lambda r: int(r.get('name') or 0))
    if round_filter:
        rounds = [r for r in rounds if round_filter(r)]
    elim_rounds = [r for r in rounds if r.get('type') not in PRELIM_TYPES]
    # elim rounds that exist only in Ballots text (no round object / no sections)
    debates = []
    nelim = len(elim_rounds)

    def ent(eid, b=None):
        e = entries.get(str(eid))
        if e is None:
            e = {'school': '', 'names': [n.strip() for n in (b or {}).get('entry_name', '').split('&')], 'code': (b or {}).get('entry_code', ''), 'id': str(eid)}
            entries[str(eid)] = e
        return e

    for ri, r in enumerate(rounds):
        rnum = int(r.get('name') or 0)
        is_prelim = r.get('type') in PRELIM_TYPES
        if is_prelim:
            label = f'R{rnum}'
        else:
            label = elim_label(nelim - 1 - elim_rounds.index(r))
        for sec in r.get('sections', []):
            by = defaultdict(list)
            for b in sec.get('ballots', []):
                by[str(b['entry'])].append(b)
            ids = list(by)
            rec = {'round': label, 'round_order': ri + 1, 'round_type': 'prelim' if is_prelim else 'elim',
                   'judges': [], 'ballots': '', 'status': 'CONFIRMED', 'note': '', 'tabroom_round': rnum}
            judges = []
            for b in sec.get('ballots', []):
                j = clean_name(f"{b.get('judge_first','')} {b.get('judge_last','')}")
                if j and j not in judges:
                    judges.append(j)
            rec['judges'] = judges
            if len(ids) == 1:
                rec.update(a=ent(ids[0], by[ids[0]][0]), b=None, side_a=None, winner='a', status='BYE')
                debates.append(rec)
                continue
            if len(ids) != 2:
                continue
            A, B = ids
            side_a = {1: 'Aff', 2: 'Neg'}.get(by[A][0].get('side'))
            # count ballots by judge
            wa = wb = 0
            scored = False
            for eid in (A, B):
                for b in by[eid]:
                    for s in b.get('scores') or []:
                        if s.get('tag') == 'winloss':
                            scored = True
                            if s.get('value') in (1, '1'):
                                if eid == A: wa += 1
                                else: wb += 1
            forfeit = any(b.get('forfeit') for eid in (A, B) for b in by[eid])
            secbye = bool(sec.get('bye')) or any(b.get('bye') for eid in (A, B) for b in by[eid])
            src = 'ballot scores'
            if not scored or wa == wb:
                la, lb = letters.get(A, {}).get(rnum), letters.get(B, {}).get(rnum)
                if la or lb:
                    if la:
                        wa, wb = la
                    else:
                        wb, wa = lb
                    src = 'Ballots text'
            rec.update(a=ent(A, by[A][0]), b=ent(B, by[B][0]), side_a=side_a)
            if wa > wb:
                rec['winner'] = 'a'; rec['ballots'] = f'{wa}-{wb}'
            elif wb > wa:
                rec['winner'] = 'b'; rec['ballots'] = f'{wb}-{wa}'
            else:
                rec['winner'] = None
            if src == 'Ballots text':
                rec['note'] = 'result from Tabroom Ballots text (no ballot scores)'
            if forfeit:
                rec['note'] = (rec['note'] + '; forfeit flagged').strip('; ')
                rec['status'] = 'FORFEIT'
            elif secbye and not scored:
                rec['note'] = (rec['note'] + '; section flagged bye').strip('; ')
                rec['status'] = 'WALKOVER'
            debates.append(rec)
    meta = {'event': ev.get('name'), 'start': d.get('start'), 'seeds': seeds(ev), 'letters': letters,
            'entries': entries, 'elim_round_nums': [int(r['name']) for r in elim_rounds],
            'all_round_nums': sorted({n for L in letters.values() for n in L})}
    return debates, meta

"""Tabroom JSON export -> per-ballot speaker points and decisions for one event.

One record per ballot (= one judge's scoring of one team in one debate):
  {'round','rtype','team':{'school','names','code'},'side','win','judge','judge_pid','pts':{name: value},'opp_code'}"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'h2h'))
from common import clean_name
import p_tabroom

ELIM_LABELS = ['Final', 'Semis', 'Quarters', 'Octos', 'Double Octos', 'Triple Octos']


def events(path):
    d = json.load(open(path))
    return [e for c in d.get('categories', []) for e in c.get('events', []) if e.get('rounds')]


def parse(path, event_name=None):
    d = json.load(open(path))
    ev = p_tabroom.pick_event(d, event_name)
    students, entries = {}, {}
    for s in d.get('schools', []):
        for st in s.get('students', []):
            students[str(st['id'])] = clean_name(f"{st.get('first', '')} {st.get('last', '')}")
    for s in d.get('schools', []):
        for en in s.get('entries', []):
            ids = [str(x) for x in en.get('students', [])]
            entries[str(en['id'])] = {'school': s.get('name', ''), 'names': [students[i] for i in ids if i in students],
                                      'ids': ids, 'code': en.get('code', '')}
    rounds = sorted(ev['rounds'], key=lambda r: int(r.get('name') or 0))
    elims = [r for r in rounds if r.get('type') not in p_tabroom.PRELIM_TYPES]
    recs, n_pre = [], 0
    for r in rounds:
        pre = r.get('type') in p_tabroom.PRELIM_TYPES
        if pre:
            n_pre += 1
            label = f'R{n_pre}'
        else:
            k = len(elims) - 1 - elims.index(r)
            label = ELIM_LABELS[k] if k < len(ELIM_LABELS) else f'Elim -{k}'
        for sec in r.get('sections', []):
            bl = sec.get('ballots', []) or []
            ents = {str(b.get('entry')) for b in bl}
            for b in bl:
                en = entries.get(str(b.get('entry')))
                if not en or b.get('bye') or b.get('forfeit'):
                    continue
                win, pts = None, {}
                for sc in b.get('scores') or []:
                    if sc.get('tag') == 'winloss':
                        win = bool(int(sc.get('value') or 0))
                    elif sc.get('tag') == 'point' and sc.get('speaker') is not None:
                        nm = students.get(str(sc['speaker']))
                        if nm:
                            pts[nm] = float(sc.get('value') or 0)
                judge = clean_name(f"{b.get('judge_first') or ''} {b.get('judge_last') or ''}")
                opp = [e for e in ents if e != str(b.get('entry'))]
                recs.append({'round': label, 'rtype': 'prelim' if pre else 'elim', 'team': en, 'tid': str(b.get('entry')),
                             'side': {1: 'Aff', 2: 'Neg'}.get(b.get('side')), 'win': win, 'judge': judge,
                             'judge_pid': b.get('judge_person') or b.get('judge'), 'pts': pts,
                             'opp': opp[0] if len(opp) == 1 else None, 'sec_bye': bool(sec.get('bye')) or len(ents) < 2})
    return recs, entries, (ev.get('abbr') or ev.get('name'))

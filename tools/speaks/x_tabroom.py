"""Tabroom JSON export -> per-ballot speaker points and decisions for one event.

One record per ballot (= one judge's scoring of one team in one debate):
  {'round','rtype','team':{'school','names','code'},'side','win','judge','judge_pid','pts':{name: value},'opp_code'}

Points come from each ballot's `point` scores when present. If those arrays are empty (common
on some published Tabroom exports) but a result set such as Speaker Awards or Prelim Seeds still
lists per-round points in its Ballots text, those values are used for prelims and attached to
the matching ballot so the judge and side stay the ones Tabroom recorded.
"""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'h2h'))
from common import clean_name
import p_tabroom

ELIM_LABELS = ['Final', 'Semis', 'Quarters', 'Octos', 'Double Octos', 'Triple Octos']


def events(path):
    d = json.load(open(path))
    return [e for c in d.get('categories', []) for e in c.get('events', []) if e.get('rounds')]


def _key_map(rs):
    return {k['id']: k for k in rs.get('result_keys') or []}


def _value(row, keys, tag):
    for v in row.get('values') or []:
        k = keys.get(v.get('result_key'))
        if k and k.get('tag') == tag:
            return v.get('value') or ''
    return ''


def _parse_seed_ballots(text):
    """Prelim Seeds Ballots text -> {round_num: ('BYE', []) or ('W'/'L', [points...])}."""
    out = {}
    for m in re.finditer(r'R(\d+)\s+(BYE|[WL]\s+[0-9.]+(?:,\s*[0-9.]+)*)', text or '', re.I):
        rn = int(m.group(1))
        body = m.group(2)
        if body.upper() == 'BYE':
            out[rn] = ('BYE', [])
        else:
            dec = body[0].upper()
            pts = [float(x) for x in re.findall(r'[0-9.]+', body[1:])]
            out[rn] = (dec, pts)
    return out


def _parse_award_ballots(text):
    """Speaker Awards Ballots text -> [(W/L, points), ...] in printed order (bye rounds omitted)."""
    t = (text or '').replace('\xa0', ' ').replace('&nbsp;', ' ')
    return [(m.group(1), float(m.group(2))) for m in re.finditer(r'([WL])\s+([0-9.]+)', t)]


def points_from_result_sets(event, entries, students):
    """Map entry id -> {tabroom_round_num: {debater_name: points}} from published result sets."""
    seeds = awards = None
    for rs in event.get('result_sets') or []:
        lab = (rs.get('label') or '').lower()
        if 'seed' in lab:
            seeds = rs
        elif 'speaker' in lab:
            awards = rs
    if not seeds:
        return {}

    seed_map = {}
    keys = _key_map(seeds)
    for row in seeds.get('results') or []:
        eid = str(row.get('entry') or '')
        if eid:
            seed_map[eid] = _parse_seed_ballots(_value(row, keys, 'Ballots'))

    award_map = {}
    if awards:
        keys = _key_map(awards)
        for row in awards.get('results') or []:
            eid = str(row.get('entry') or '')
            sid = str(row.get('student') or '')
            if eid and sid:
                award_map[(eid, sid)] = _parse_award_ballots(_value(row, keys, 'Ballots'))

    def assign(ids, seeds_r, order_ids):
        rec = {}
        for rn, (dec, pts) in seeds_r.items():
            if dec == 'BYE' or not pts:
                continue
            rec[rn] = {}
            for i, sid in enumerate(order_ids):
                if i < len(pts) and sid in students:
                    rec[rn][students[sid]] = pts[i]
        return rec

    def awards_ok(ids, seeds_r, rec):
        checked = 0
        for sid in ids:
            aw = award_map.get((str(entries and ''), sid))  # placeholder, fixed below
        return True  # replaced in loop body

    out = {}
    for eid, en in entries.items():
        ids = [str(i) for i in (en.get('ids') or [])]
        seeds_r = seed_map.get(eid) or {}
        if not seeds_r:
            continue

        def _ok(rec):
            for sid in ids:
                aw = award_map.get((eid, sid))
                if not aw:
                    continue
                got = []
                for rn in sorted(seeds_r):
                    if seeds_r[rn][0] == 'BYE':
                        continue
                    nm = students.get(sid)
                    if nm in rec.get(rn, {}):
                        got.append(rec[rn][nm])
                if len(got) != len(aw) or any(abs(a - b) > 0.011 for a, b in zip(got, [x[1] for x in aw])):
                    return False
            return True

        rec = assign(ids, seeds_r, ids)
        if not _ok(rec) and len(ids) >= 2:
            # try reversing speaker-column order
            rec2 = assign(ids, seeds_r, list(reversed(ids)))
            if _ok(rec2):
                rec = rec2
        if rec:
            out[eid] = rec
    return out


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
    prelim_name_to_label = {}
    for r in rounds:
        pre = r.get('type') in p_tabroom.PRELIM_TYPES
        if pre:
            n_pre += 1
            label = f'R{n_pre}'
            rnum = int(r.get('name') or n_pre)
            prelim_name_to_label[rnum] = label
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
    fill = points_from_result_sets(ev, entries, students)
    if fill:
        by_label = {}
        for eid, by_rn in fill.items():
            for rn, pts in by_rn.items():
                lab = prelim_name_to_label.get(rn)
                if lab:
                    by_label[(eid, lab)] = pts
        # Only attach result-set points when the ballot itself has none, and only on
        # a unique prelim ballot for that team and round (so a panel is not given one score twice).
        counts = {}
        for rec in recs:
            if rec['rtype'] == 'prelim' and not rec['pts'] and not rec.get('sec_bye'):
                counts[(rec['tid'], rec['round'])] = counts.get((rec['tid'], rec['round']), 0) + 1
        for rec in recs:
            key = (rec['tid'], rec['round'])
            if rec['rtype'] != 'prelim' or rec['pts'] or rec.get('sec_bye') or counts.get(key) != 1:
                continue
            pts = by_label.get(key)
            if pts:
                rec['pts'] = pts
    return recs, entries, (ev.get('abbr') or ev.get('name'))

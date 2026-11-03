"""SpeechWire PDFs -> debates.

Prelim grid ("Competitor | Round 1..N | Totals | Results") is read by word
coordinates: pdfplumber words for real-text PDFs, Tesseract TSV words for the
obfuscated-font exports (OCR). Elim results come from the "Elimination round
results" text ("X def. Y (side) 2-1")."""
import re, os, subprocess, csv, io, hashlib, logging, difflib
import pdfplumber
from common import clean_name, CACHE

logging.getLogger('pdfminer').setLevel(logging.ERROR)
OCR_DPI = 300


def ocr_words(path, pno, page):
    h = hashlib.md5((path + str(pno)).encode()).hexdigest()[:12]
    tsv = os.path.join(CACHE, f'ocr_{h}.tsv')
    if not os.path.exists(tsv):
        png = os.path.join(CACHE, f'ocr_{h}')
        subprocess.run(['pdftoppm', '-r', str(OCR_DPI), '-f', str(pno + 1), '-l', str(pno + 1), '-png', '-singlefile', path, png], check=True)
        subprocess.run(['tesseract', png + '.png', tsv[:-4], '--psm', '11', 'tsv'], check=True, capture_output=True)
        os.remove(png + '.png')
    scale = 72.0 / OCR_DPI
    words = []
    with open(tsv) as f:
        for row in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            t = (row.get('text') or '').strip()
            if not t or row['conf'] in ('-1',):
                continue
            x0 = float(row['left']) * scale; top = float(row['top']) * scale
            words.append({'x0': x0, 'x1': x0 + float(row['width']) * scale, 'top': top,
                          'bottom': top + float(row['height']) * scale, 'text': t})
    return words


def ocr_text(path, pno):
    h = hashlib.md5((path + str(pno) + 'psm6').encode()).hexdigest()[:12]
    out = os.path.join(CACHE, f'ocr6_{h}.txt')
    if not os.path.exists(out):
        png = os.path.join(CACHE, f'ocr6_{h}')
        subprocess.run(['pdftoppm', '-r', str(OCR_DPI), '-f', str(pno + 1), '-l', str(pno + 1), '-png', '-singlefile', path, png], check=True)
        subprocess.run(['tesseract', png + '.png', out[:-4], '--psm', '6'], check=True, capture_output=True)
        os.remove(png + '.png')
    return open(out).read()


def page_words(path, ocr):
    out = []
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages):
            ws = ocr_words(path, i, p) if ocr else p.extract_words(keep_blank_chars=False, use_text_flow=False)
            txt = p.extract_text() or '' if not ocr else None
            if ocr and any(w['text'].startswith('Elimination') for w in ws):
                txt = ocr_text(path, i)
            out.append((ws, txt))
    return out


def lines_of(words, tol=2.5):
    ws = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines = []
    for w in ws:
        if lines and abs(lines[-1][0]['top'] - w['top']) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w['x0']) for l in lines]


def ltext(l):
    return ' '.join(w['text'] for w in l)


SCORE = re.compile(r'^\d{2}\.\d{1,2}$')
CODE_TOK = re.compile(r'^[A-Z]{2,5}$')


def parse_grid(pages, want_division=None):
    """Returns {division: [team blocks]}; each block has code_line, names, rounds{n: text}."""
    divisions = {}
    cols = None
    division = None
    pending = []  # words of current partial block
    for ws, _txt in pages:
        lines = lines_of(ws)
        hdr = None
        for i, l in enumerate(lines):
            t = ltext(l)
            if re.search(r'Competitor', t) and re.search(r'Round\s*1', t):
                hdr = i
                rx = [w for w in l if w['text'].lower().startswith('round')]
                tot = [w for w in l if w['text'].lower().startswith('total')]
                bounds = [w['x0'] - 15 for w in rx] + [tot[0]['x0'] - 4 if tot else rx[-1]['x1'] + 60]
                cols = refine_bounds(bounds, lines[i + 1:])
                # division = previous non-empty line
                division = ltext(lines[i - 1]) if i > 0 else division
                divisions.setdefault(division, [])
                pending = []
                break
            if re.search(r'Elimination round|Competitors in order|Individual speakers|Speaker', t):
                break
        if cols is None:
            continue
        if hdr is None:
            # continuation page only if no other section marker
            alltxt = ' '.join(ltext(l) for l in lines[:6])
            if re.search(r'Elimination round|Competitors in order|Individual speakers|Code\s+Team', alltxt):
                cols = None
                continue
            body = lines
        else:
            body = lines[hdr + 1:]
        for l in body:
            t = ltext(l)
            if re.match(r'^(https?:|This tournament|©|\d+/\d+/\d+,)', t) or 'SpeechWire' in t:
                continue
            pending.append(l)
            # score line: competitor-column words + a score in round-1 column
            comp = [w for w in l if w['x1'] < cols[0] + 5]
            r1 = [w for w in l if cols[0] <= w['x0'] < cols[1] and SCORE.match(w['text'].replace(',', '.'))]
            if comp and r1:
                l.append({'__score': True, 'x0': -1, 'x1': -1, 'top': l[0]['top'], 'text': ''})
                scored = [p for p in pending if any(w.get('__score') for w in p)]
                if len(scored) == 2:
                    divisions[division].append(make_block(pending, cols))
                    pending = []
    return divisions


def refine_bounds(bounds, lines):
    """Move each round-column left edge to just before the left-most 'W -'/'L -' token that
    clusters with that column (result tokens can start left of the header word)."""
    starts = []
    for l in lines:
        for a, b in zip(l, l[1:]):
            if a['text'] in ('W', 'L', 'W-', 'L-') and (b['text'].startswith('-') or a['text'].endswith('-')):
                starts.append(a['x0'])
    nb = list(bounds)
    n = len(bounds) - 1
    hdr = [b + 15 for b in bounds[:-1]]
    for k in range(n):
        lo = hdr[k] - (hdr[k] - hdr[k - 1]) * 0.6 if k else hdr[k] - 60
        xs = [x for x in starts if lo <= x <= hdr[k] + 10]
        if xs:
            nb[k] = min(xs) - 2
    return nb


def make_block(lines, cols):
    names = []
    comp_words = []
    rounds = {i + 1: [] for i in range(len(cols) - 1)}
    for l in lines:
        is_score = any(w.get('__score') for w in l)
        real = [w for w in l if not w.get('__score')]
        if is_score:
            nm = ' '.join(w['text'] for w in real if w['x1'] < cols[0] + 5)
            names.append(clean_name(nm))
            continue
        for w in real:
            cx = w['x0']
            if cx < cols[0]:
                comp_words.append(w)
            else:
                for k in range(len(cols) - 1):
                    if cols[k] <= cx < cols[k + 1]:
                        rounds[k + 1].append(w)
    comp = ltext_sorted(comp_words)
    rtext = {k: ltext_sorted(v) for k, v in rounds.items()}
    return {'comp': comp, 'names': names, 'rounds': rtext}


def ltext_sorted(ws):
    return ' '.join(ltext(l) for l in lines_of(ws, tol=2.0))


ROUND_RE = re.compile(r'^\s*([WL])\s*-\s*(.+?)\s*-\s*(AFF|Aff|Neg|NEG|Gov|Opp)\b\s*(.*)$', re.S)


def despace(t):
    # rejoin letter-spaced words ("U O P ECJT - N e g" -> "UOP ECJT - Neg")
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r'(?<![A-Za-z])([A-Za-z]) (?=[A-Za-z](?![A-Za-z]))', r'\1', t)
        t = re.sub(r'(?<![A-Za-z])([A-Za-z]{1,2}) ([a-z]{1,3})(?![A-Za-z])', r'\1\2', t)
    return t


def team_code(comp):
    toks = comp.split()
    idx = [i for i, t in enumerate(toks[:6]) if CODE_TOK.match(t)]
    # code = last all-caps token among the first tokens that is followed by a capitalised school word,
    # prefer index >= 1
    idx = [i for i in idx if i >= 1] or idx
    if not idx:
        return toks[0] if toks else '', toks[:1]
    i = idx[0]
    # if next token also caps code-like (e.g. 'UOP JABB'), take the later
    while i + 1 < len(toks) and CODE_TOK.match(toks[i + 1]) and i + 1 <= 3:
        i += 1
    return toks[i], toks[:i]


def build_prelims(blocks):
    teams = []
    for b in blocks:
        ct = b['comp'].split()
        stray = [x for x in ct if x in ('W', 'L', '|', ']', '[')]
        if stray and b['rounds']:
            b['comp'] = ' '.join(x for x in ct if x not in ('W', 'L', '|', ']', '['))
            k1 = min(b['rounds'])
            wl = [x for x in stray if x in ('W', 'L')]
            if wl:
                b['rounds'][k1] = wl[0] + ' ' + b['rounds'][k1]
        code, prefix = team_code(b['comp'])
        school = b['comp']
        teams.append({'code': ' '.join(prefix + [code]), 'codetok': code, 'prefix': ' '.join(prefix),
                      'school_text': b['comp'], 'names': [n for n in b['names'] if n][:2], 'school': '', 'rounds': b['rounds']})
    return teams


def match_ref(ref, teams, exclude=None):
    """ref like 'UTTyler ACTE' or 'Rice Universit GW' -> team index list."""
    toks = re.sub(r'[^A-Za-z\' ]', ' ', ref).split()
    if not toks:
        return []
    codes = [t for t in toks if CODE_TOK.match(t)]
    code = codes[-1] if codes else toks[-1]
    first = toks[0].lower()
    def compat(i):
        p = (teams[i]['prefix'] or teams[i]['school_text']).lower().replace(' ', '')
        f = ''.join(toks[:-1]).lower() if len(toks) > 1 else first
        return not f or p.startswith(f[:3]) or f.startswith(p[:3])
    c1 = [i for i, t in enumerate(teams) if t['codetok'] == code and i != exclude and compat(i)]
    if len(c1) > 1:
        c2 = [i for i in c1 if (teams[i]['prefix'] or teams[i]['school_text']).lower().startswith(first[:4])]
        if c2:
            c1 = c2
    if not c1:
        flat = ref.replace(' ', '').lower()
        c1 = [i for i, t in enumerate(teams) if i != exclude and flat.endswith(t['codetok'].lower()) and
              t['code'].replace(' ', '').lower()[:3] == flat[:3]]
    if not c1:  # fuzzy (OCR)
        best = difflib.get_close_matches(code, [t['codetok'] for t in teams], n=3, cutoff=0.7)
        c1 = [i for i, t in enumerate(teams) if t['codetok'] in best and i != exclude and not t.get('placeholder')]
        c2 = [i for i in c1 if compat(i)]
        if not c2 and len(c1) > 1:
            c2 = [i for i in c1 if (teams[i]['prefix'] or teams[i]['school_text']).lower()[:1] == first[:1]]
        c1 = c2
    return c1


def prelim_debates(teams):
    recs = {}
    issues = []
    for i, t in enumerate(list(teams)):
        for rn, txt in t['rounds'].items():
            txt = txt.strip()
            if not txt or re.search(r'\d{2}\.\d', txt) and not re.search(r'[WL]\s*-', txt):
                continue
            if re.match(r'^BYE', txt, re.I) or re.search(r'\bBYE\b', txt) and not re.search(r'[WL]\s*-', txt):
                recs[(rn, i, None)] = {'round': f'R{rn}', 'rn': rn, 'a': i, 'b': None, 'status': 'BYE'}
                continue
            m = ROUND_RE.match(txt)
            if not m:
                m = ROUND_RE.match(despace(txt))
            if not m:
                issues.append(f'R{rn} {t["code"]}: unparsed "{txt[:60]}"')
                continue
            res, ref, side, rest = m.groups()
            cand = match_ref(ref, teams, exclude=i)
            judge = re.sub(r'^[A-Z]{1,3}\d+\s*', '', rest.strip())
            judge = re.sub(r'\s*\d{3}\.\d.*$', '', judge)
            if not cand and not t.get('placeholder'):
                # opponent's own block was not parsed (e.g. split across a page break): placeholder team
                ref_clean = ' '.join(despace(ref).split())
                ph = [k for k, tt in enumerate(teams) if tt.get('placeholder') and tt['code'] == ref_clean]
                if not ph:
                    toks2 = ref_clean.split()
                    teams.append({'code': ref_clean, 'codetok': toks2[-1], 'prefix': ' '.join(toks2[:-1]), 'school_text': ref_clean,
                                  'names': [], 'school': '', 'rounds': {}, 'placeholder': True})
                    ph = [len(teams) - 1]
                    issues.append(f'placeholder team created for unparsed block "{ref_clean}"')
                cand = ph
            if len(cand) != 1:
                issues.append(f'R{rn} {t["code"]}: opponent "{ref}" -> {len(cand)} matches')
                continue
            j = cand[0]
            k = (rn,) + tuple(sorted((i, j)))
            side = 'Aff' if side.lower() in ('aff', 'gov') else 'Neg'
            r = recs.get(k)
            if r is None:
                recs[k] = {'round': f'R{rn}', 'rn': rn, 'a': i, 'b': j, 'side_a': side, 'win_a': res == 'W',
                           'judges': [clean_name(judge)] if judge else [], 'seen': 1}
            else:
                r['seen'] = 2
                if r['a'] == j and (res == 'W') == r['win_a']:
                    issues.append(f'R{rn} {t["code"]} vs {teams[j]["code"]}: both sides report {res}')
                    r['conflict'] = True
    return recs, issues


def elim_text(pages, division_pred):
    """Concatenate text of 'Elimination round results' pages whose division matches."""
    chunks = []
    for ws, txt in pages:
        if txt is None:
            txt = '\n'.join(ltext(l) for l in lines_of(ws))
        if 'Elimination round results' not in txt and 'Elimination round resu' not in txt:
            continue
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        i = next(k for k, l in enumerate(lines) if l.startswith('Elimination round resu'))
        div = lines[i - 1] if i else ''
        if division_pred(div):
            chunks.append('\n'.join(lines[i + 1:]))
    return '\n'.join(chunks)


ELIM_ROUNDS = [('Double', 'Double Octos'), ('Octafinal', 'Octos'), ('Quarterfinal', 'Quarters'), ('Semifinal', 'Semis'), ('Final', 'Final')]


def parse_elims(text, teams):
    """Returns list of (round_label, winner_idx, loser_idx|None, side_w, side_l, ballots)."""
    out, issues = [], []
    cur = None
    parts = re.split(r'^\s*((?:Double\s+)?(?:Octafinal|Quarterfinal|Semifinal|Final)\s+round)\s*$', text, flags=re.M)
    for k in range(1, len(parts), 2):
        hdr, body = parts[k], parts[k + 1]
        label = next(v for kk, v in ELIM_ROUNDS if kk in hdr)
        body = body.split('Champion:')[0]
        body = re.sub(r'\s+', ' ', body)
        body = re.sub(r'(\d)\s*-\s+(\d)', r'\1-\2', body)
        # locate team code occurrences
        occ = []
        for i, t in enumerate(teams):
            for m in re.finditer(r'(?<![A-Za-z])' + re.escape(t['code']) + r'(?![A-Za-z])', body):
                occ.append((m.start(), m.end(), i))
        occ.sort()
        # drop overlapping
        clean = []
        for o in occ:
            if clean and o[0] < clean[-1][1]:
                continue
            clean.append(o)
        idx = 0
        while idx < len(clean):
            s, e, i = clean[idx]
            nxt = clean[idx + 1] if idx + 1 < len(clean) else None
            seg = body[e: nxt[0] if nxt else len(body)]
            if ' def.' in seg or 'def.' in seg:
                if not nxt:
                    issues.append(f'{label}: dangling def. after {teams[i]["code"]}')
                    break
                j = nxt[2]
                after = body[nxt[1]: clean[idx + 2][0] if idx + 2 < len(clean) else len(body)]
                sw = re.search(r'\((AFF|Neg|Gov|Opp)\)', seg)
                sl = re.search(r'\((AFF|Neg|Gov|Opp)\)', after)
                bl = re.search(r'(\d)-(\d)', after)
                out.append((label, i, j, sw.group(1) if sw else None, sl.group(1) if sl else None, bl.group(0) if bl else ''))
                idx += 2
            elif 'BYE' in seg:
                out.append((label, i, None, None, None, ''))
                idx += 1
            else:
                issues.append(f'{label}: no def./BYE after {teams[i]["code"]}: "{seg[:50]}"')
                idx += 1
    return out, issues


def parse(grid_pdf, elim_pdf=None, ocr=False, elim_ocr=None, division=None, site_names=None):
    pages = page_words(grid_pdf, ocr)
    divs = parse_grid(pages)
    # choose division: given, else most matching site names, else first with 'Open'
    def score(blocks):
        if not site_names:
            return 0
        s = 0
        for b in blocks:
            for n in b['names']:
                if n.lower().split()[-1:] and any(n.lower().split()[-1] == x for x in site_names):
                    s += 1
        return s
    cand = {d: b for d, b in divs.items() if d and re.search(r'parli|senior|open', d, re.I) and not re.search(r'ipda|novice', d, re.I)} or divs
    if division:
        cand = {d: b for d, b in divs.items() if d == division} or cand
    div = max(cand, key=lambda d: (score(cand[d]), len(cand[d])))
    teams = build_prelims(divs[div])
    recs, issues = prelim_debates_loose(teams) if ocr else prelim_debates(teams)
    epages = pages if elim_pdf is None else page_words(elim_pdf, elim_ocr if elim_ocr is not None else ocr)
    etext = elim_text(epages, lambda d: d.strip() == div.strip() or not d)
    elims, eiss = parse_elims(etext, teams) if etext else ([], ['no elim results text'])
    return teams, recs, elims, issues + eiss, div


def parse_grid_tables(path):
    """'Tab grouping' sheet (Steve Hunt 2026): real table cells, 3 rows per team."""
    blocks = []
    with pdfplumber.open(path) as pdf:
        rows = []
        for p in pdf.pages:
            for t in p.find_tables():
                rows.extend(t.extract())
    i = 0
    while i < len(rows):
        r = rows[i]
        c0 = (r[0] or '')
        if c0.strip() == 'Competitor' or '\n' not in c0:
            i += 1
            continue
        code_line, school = c0.split('\n', 1)
        names = []
        for k in (1, 2):
            if i + k < len(rows) and rows[i + k][0] and '\n' not in rows[i + k][0]:
                names.append(clean_name(rows[i + k][0]))
        rounds = {k: ' '.join((r[k] or '').split()) for k in range(1, 6)}
        blocks.append({'comp': code_line.strip() + ' ' + ' '.join(school.split()), 'names': names, 'rounds': rounds,
                       'code_line': code_line.strip()})
        i += 1 + len(names)
    return blocks


def parse_tables(grid_pdf, elim_pdf=None, elim_ocr=True):
    teams = build_prelims(parse_grid_tables(grid_pdf))
    recs, issues = prelim_debates(teams)
    elims, eiss = [], ['no elim results text']
    if elim_pdf:
        etext = elim_text(page_words(elim_pdf, elim_ocr), lambda d: True)
        elims, eiss = parse_elims(etext, teams) if etext else ([], ['no elim results text'])
    return teams, recs, elims, issues + eiss, 'Senior Parliamentary Debate'


SIDE_TOK = re.compile(r'^(AFF|AF|Aff|Neg|NEG|Ne|Gov|GOV|Opp|OPP)$')


def prelim_debates_loose(teams):
    """OCR-tolerant prelim parse: pick result (W/L), side, and opponent code from a scrambled cell.
    Both teams' cells are merged; a missing result/side on one side is filled from the other."""
    obs = {}
    issues = []
    codes = {}
    for i, t in enumerate(teams):
        codes.setdefault(t['codetok'], []).append(i)
    for i, t in enumerate(teams):
        for rn, txt in t['rounds'].items():
            toks = re.sub(r'[^A-Za-z0-9 ]', ' ', txt).split()
            if not toks:
                continue
            if 'BYE' in [x.upper() for x in toks] and not any(x in ('W', 'L') for x in toks):
                obs.setdefault((rn, i, None), []).append({'bye': True})
                continue
            res = next((x for x in toks if x in ('W', 'L')), None)
            side = next((x for x in toks if SIDE_TOK.match(x)), None)
            side = None if side is None else ('Aff' if side.lower() in ('aff', 'af', 'gov') else 'Neg')
            cand = []
            for x in toks:
                if x in codes and x != t['codetok'] and len(x) >= 2 and x not in ('W', 'L'):
                    cand = [k for k in codes[x] if k != i]
                    if cand:
                        break
            if not cand:
                ups = [x for x in toks if x.isupper() and 3 <= len(x) <= 5 and not re.search(r'\d', x) and x not in ('AFF', 'NEG', 'GOV', 'OPP', 'BYE')]
                for x in ups:
                    best = difflib.get_close_matches(x, [c for c in codes if c != t['codetok']], n=1, cutoff=0.75)
                    if best:
                        cand = [k for k in codes[best[0]] if k != i]
                        break
            if len(cand) > 1:
                pre = [k for k in cand if any(teams[k]['prefix'].lower()[:3] == x.lower()[:3] for x in toks if len(x) > 2)]
                cand = pre if len(pre) == 1 else cand
            if len(cand) != 1:
                issues.append(f'R{rn} {t["code"]}: OCR cell unresolved "{txt[:60]}"')
                continue
            j = cand[0]
            m = re.search(r'\b[A-Z]{1,4}\d{1,2}\s+([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z\'-]+){1,2})', txt)
            obs.setdefault((rn,) + tuple(sorted((i, j))), []).append(
                {'from': i, 'res': res, 'side': side, 'judge': clean_name(m.group(1)) if m else ''})
    recs = {}
    for k, ol in obs.items():
        rn = k[0]
        if k[2] is None:
            recs[k] = {'round': f'R{rn}', 'rn': rn, 'a': k[1], 'b': None, 'status': 'BYE'}
            continue
        a, b = k[1], k[2]
        wa = set()
        sa = set()
        judges = [o['judge'] for o in ol if o['judge']]
        for o in ol:
            if o['res']:
                wa.add((o['res'] == 'W') == (o['from'] == a))
            if o['side']:
                sa.add(o['side'] if o['from'] == a else ('Neg' if o['side'] == 'Aff' else 'Aff'))
        r = {'round': f'R{rn}', 'rn': rn, 'a': a, 'b': b, 'side_a': sa.pop() if len(sa) == 1 else None,
             'win_a': wa.pop() if len(wa) == 1 else None, 'judges': judges[:1], 'seen': len(set(o['from'] for o in ol))}
        if r['win_a'] is None:
            issues.append(f'R{rn} {teams[a]["code"]} vs {teams[b]["code"]}: OCR result unknown/conflicting')
        recs[k] = r
    return recs, issues

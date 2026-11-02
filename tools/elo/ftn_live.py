"""Official FTN (forensicstournament.net) result sheets: URL map, fetch via fetch-cached, parse.
The live result-sheet page is the HTML version of the printed PDFs; it is used to verify / override the PDF parse."""
import re, html, os, subprocess, json
from common import SRC
FT = SRC + '/FTN/'
CACHE = '/workspace/cache/files/ftn/live'

EXTRA_URLS = {   # tournaments whose PDF has no printed URL (found from the tournament's results index)
    'Crossman - 2021': 'https://forensicstournament.net/crossmaninvitational/21/results/et/46424',
    'DVC Thing - 2021': 'https://forensicstournament.net/TheDVCThingSunday/21/results/et/46121',
    'GGO - 2022': 'https://forensicstournament.net/GGO/22/results/et/49101',
}


def url_for(t, pdf):
    if t in EXTRA_URLS:
        return EXTRA_URLS[t]
    try:
        txt = subprocess.run(['pdftotext', '-l', '1', FT + pdf, '-'], capture_output=True, text=True).stdout
    except Exception:
        return None
    m = re.search(r'forensicstournament\.net/\S+/results/et/\d+', txt)
    return 'https://' + m.group(0) if m else None


def fetch(url):
    eid = url.rstrip('/').split('/')[-1]
    dest = os.path.join(CACHE, eid)
    p = os.path.join(dest, eid)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return p
    out = subprocess.run(['/workspace/bin/fetch-cached', url, '--type', 'archive', '--dest', dest], capture_output=True, text=True).stdout
    m = re.search(r'(?:HIT|MISS)\S* (?:\([^)]*\) )?(\S.*)$', out.strip().splitlines()[-1]) if out.strip() else None
    return m.group(1).strip() if m and os.path.exists(m.group(1).strip()) else (p if os.path.exists(p) else None)


def _txt(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def parse(path):
    """-> {'title', 'event', 'teams': [{'school','names','wins','seed','rounds':[{'rd','side','opp','judges','dec'}]}]}"""
    t = open(path, encoding='utf-8', errors='replace').read()
    title = _txt(re.search(r'<h3 class="page-title.*?</h3>', t, re.S).group(0)) if '<h3 class="page-title' in t else ''
    ev = re.search(r'<h1>(.*?)</h1>', t, re.S)
    teams = []
    for tb in re.findall(r'<table class="table".*?</table>', t, re.S):
        th = re.findall(r'<th[^>]*>(.*?)</th>', tb, re.S)
        if len(th) < 2:
            continue
        head, rec = _txt(th[0]), _txt(th[1])
        school, _, names = head.partition(' - ')
        wins = re.search(r'(\d+) Wins?', rec)
        seed = re.search(r'Seed:\s*(\d+)', rec)
        rounds = []
        for tr in re.findall(r'<tr>(.*?)</tr>', tb, re.S):
            td = [_txt(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            if len(td) < 5 or td[0] in ('Rd', ''):
                continue
            rounds.append({'rd': td[0], 'side': td[1], 'opp': td[2], 'judges': td[3], 'dec': td[4]})
        teams.append({'school': school.strip(), 'names': [n.strip() for n in names.split('&')], 'wins': int(wins.group(1)) if wins else None,
                      'seed': int(seed.group(1)) if seed else None, 'rounds': rounds})
    return {'title': title, 'event': _txt(ev.group(1)) if ev else '', 'teams': teams}

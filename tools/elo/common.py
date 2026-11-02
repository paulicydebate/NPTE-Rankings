"""Shared helpers for the NPTE-Rankings matchup / ELO build."""
import json, os, re, subprocess, unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
SRC = REPO + '/source_pdfs'
# Extra sources not yet in source_pdfs/ (Rice 2022/2026 JSON, Paul Winters 2024, Steve Hunt 2026 elims); PR #3 adds them
NEW = os.environ.get('NPTE_NEW_SOURCES', '/workspace/npte-rankings/new-sources')
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
os.makedirs(CACHE, exist_ok=True)

ELIM_NAMES = ['Final', 'Semis', 'Quarters', 'Octos', 'Double Octos', 'Triple Octos']


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def clean_name(s):
    """Remove pronoun/nickname parentheticals and extra whitespace."""
    s = (s or '').replace('\u00a0', ' ')
    s = re.sub(r'\s*\([^()]*\)', '', s)
    s = re.sub(r'\s*\(.*', '', s)
    s = s.replace('"', '').replace('\u201c', '').replace('\u201d', '')
    return re.sub(r'\s+', ' ', s).strip()


def key(s):
    s = strip_accents(clean_name(s)).lower()
    return re.sub(r'[^a-z ]', '', s.replace('-', ' ')).strip()


def last_key(name):
    p = key(name).split()
    return p[-1] if p else ''


def load_site():
    out = os.path.join(CACHE, 'site.json')
    data = subprocess.check_output(['node', os.path.join(HERE, 'site_extract.js'), REPO + '/index.html'])
    open(out, 'wb').write(data)
    return json.loads(data)


def elim_label(idx_from_end):
    return ELIM_NAMES[idx_from_end] if idx_from_end < len(ELIM_NAMES) else f'Elim -{idx_from_end}'


def norm_elim_label(lbl):
    l = lbl.lower().replace('.', '').strip()
    table = [('triple', 'Triple Octos'), ('double', 'Double Octos'), ('doub', 'Double Octos'), ('octa', 'Octos'), ('octo', 'Octos'),
             ('quart', 'Quarters'), ('semi', 'Semis'), ('final', 'Final'), ('gold', 'Final'), ('bronze', 'Bronze')]
    for k, v in table:
        if k in l:
            return v
    return lbl

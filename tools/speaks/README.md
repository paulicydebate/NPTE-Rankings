# Private speaker-points page (`speaks.html`)

Unlisted, passphrase-gated page with Open/Varsity NPDA/NPTE speaker points by competitor and by judge.
There is no server: the dataset is published only as ciphertext (`data/speaks.enc.json`) and decrypted in the
browser with the passphrase.

**Never commit** the passphrase, `tools/speaks/out/`, or any `*.plain.json` (all gitignored). `validation.csv`
also contains speaker points and stays out of git. **Never link** `speaks.html` from `index.html` or `h2h.html`.

The encryption protects the compiled dataset and the page, not the archived result sheets in `source_pdfs/`,
which are already public in this repository.

## Rebuild

```
pip3 install pdfplumber cffi cryptography
python3 tools/speaks/build.py                              # -> tools/speaks/out/ (plaintext, gitignored)
SPEAKS_PASSPHRASE='...' python3 tools/speaks/encrypt.py    # -> data/speaks.enc.json (commit this)
```

Run `encrypt.py` without the variable to be prompted instead. To change the passphrase, run it again with the
new one and commit the new `data/speaks.enc.json`; the old passphrase stops working as soon as that is live.

## Files

| File | What it does |
| --- | --- |
| `build.py` | Walks `tools/h2h/inputs/tournament_calendar.csv`, extracts points per platform, resolves names to the site's spelling (`NAME_ALIASES`, `SCHOOL_ALIASES`, `tools/h2h/debater_aliases.csv`), writes the payload and the three review files |
| `x_ftn.py` | FTN result-sheet PDFs: one row per team per round, both debaters' points, judge, decision |
| `x_tabroom.py` | Tabroom JSON: one record per ballot (`point` and `winloss` scores) |
| `x_speechwire.py` | SpeechWire prelim grids (real-text and OCR'd exports); reuses `tools/h2h/p_speechwire.py` unchanged |
| `encrypt.py` | gzip, PBKDF2-HMAC-SHA256 (600,000 iterations, 16-byte salt), AES-256-GCM (12-byte IV) |
| `judge_aliases.csv` | Judge spellings counted as one person (names only). Lines marked "provisional" await review |

## Review files (`tools/speaks/out/`)

- `coverage.csv` - every calendar tournament: included, no points in the export, source missing, or awaiting OCR.
- `validation.csv` - every excluded or unusual row (out-of-range scores, group entries, rounds with no judge named).
- `judge_candidates.csv` - look-alike judge names: which were merged via `judge_aliases.csv` and which were left apart.

## What is and is not counted

- Prelim speaker points, one per debater per judge per round, as printed. Valid range 20-30; anything else is
  excluded and listed in `validation.csv`.
- Byes are excluded (the sheets print an average for them, not a judge's score).
- Judge decisions (for Aff/Neg percentages) come from prelims plus elims where each panel member's vote is
  recorded (FTN prints it, Tabroom stores a ballot per judge). For Tabroom exports with no scores at all, prelim
  decisions are taken from `tools/h2h/matchups.csv`.
- Image-only SpeechWire sheets are read with Tesseract (`apt-get update && apt-get install -y tesseract-ocr`), using the
  OCR routine in `tools/h2h/p_speechwire.py`. A debater's points are kept only if their round points add up to the
  printed total. Without Tesseract the build still runs and lists those sheets as pending.

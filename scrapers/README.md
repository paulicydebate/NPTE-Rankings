# Scrapers

Local tools that turn a tournament's results export into a sheet matching the
"Data Entry Template" layout `sync_ingest.py` expects (header row 4, data from
row 5: Year, School, Debater 1/2 First/Last Name, Prelim Wins, Prelim Losses,
Advanced, Partial Elim, 1st-7th Full Win). None of these run as part of the
deployed site - they're offline tools you run locally to produce the xlsx you
then hand to `sync_ingest.py` (or to Claude to merge in directly).

## `tabroom_scraper.py`

Input: a single tournament's JSON export from Tabroom.

Dependencies: `openpyxl`.

```
python3 tabroom_scraper.py tournament.json output.xlsx
# or batch mode - processes every *.json in the current folder:
python3 tabroom_scraper.py
```

Reads round/section/ballot data directly. Falls back to the tournament's own
posted "Ballots" text summary when an export has no per-ballot winloss scores
at all (some Tabroom exports are missing that field tournament-wide - see the
docstring on `event_has_ballot_scores()`).

## `FTN_Scraper.py`

Input: PDF tab reports exported from FTN (Forensics Tournament Network).

Dependencies: `pandas`, `pdfplumber`, `openpyxl`.

```
python3 FTN_Scraper.py   # batch mode - processes every *.pdf in the current folder
```

Reads the embedded PDF text/tables directly (FTN's PDFs use real fonts).

## `speechwire_scraper.py`

Input: PDF tab reports exported from SpeechWire.

Dependencies: `pandas`, `pdfplumber`, `openpyxl`, Pillow, and Tesseract OCR
installed separately (not a Python package - see the script's own docstring
for install links).

```
python3 speechwire_scraper.py   # batch mode - processes every *.pdf in the current folder
```

SpeechWire PDFs draw every character with a custom Type 3 font with no real
character mapping, so the embedded text can't be read directly - this script
renders each page to an image and OCRs it instead, using the PDF's real
vector table borders/bracket lines to know exactly where to crop. This is the
least reliable of the three scrapers since it depends on OCR accuracy rather
than reading real text - known issue as of writing: the standings-table
parser can pick up the wrong 6-column table on some tournament PDFs (e.g. an
"Individual Speakers" table SpeechWire also formats with 6 columns), and OCR
occasionally misreads certain letters (e.g. "y" as "v").

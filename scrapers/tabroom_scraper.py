#!/usr/bin/env python3
"""
Tabroom tournament JSON -> "Master Tournament Tabs" spreadsheet.

Produces one row per prelim entry with:

    Year | School | Debater 1 First Name | Debater 1 Last Name |
    Debater 2 First Name | Debater 2 Last Name | Prelim Wins | Prelim Losses |
    Advanced | Partial Elim | 1st Full Win | 2nd Full Win | ... | 7th Full win

Everything (schools, student first/last names, entries, prelim ballots, and
elim-round ballots) comes from one Tabroom tournament JSON export.

--- How each column is derived ---

Prelim Wins / Losses: counted from the round-by-round W/L letters in the
"Ballots" text of the event's "Prelim Seeds" result set (same as before).

Advanced: True if the entry appears in any elimination round at all
(including as the recipient of a bye straight into a later round).

Nth Full Win: elim rounds are sorted chronologically. Column N corresponds
to the Nth *real, full-strength* outround played by the field, EXCLUDING
the partial round if one is detected (see Partial Elim below) - so if the
field's first round was a short "Doubles"/"Partials" round, "1st Full Win"
is the next round after that (Octas/Quarters/whatever), not the short
round itself. True if the entry won its debate in that round. A bye is
not a win: it advances the entry but leaves that round's own column False
(and, for the partial round specifically, is excluded from the Full Win
numbering entirely rather than just being False).

Partial Elim: a debate-bracket round is expected to have
2**(rounds_remaining_after_and_including_this_one) debates (Finals=1,
Semis=2, Quarters=4, Octas=8, ...). If a round actually has fewer debates
than that (because an odd number of teams broke and someone got a bye),
the fraction actual/expected is awarded to the winners of that round's
real debates AND to any entry that received a bye into the next round
(a bye counts as a win for this purpose); losers in that round, and any
entry uninvolved in that round, get 0. If no round came up short, every
entry gets 0. Only one partial round is expected per tournament; if more
than one round is short, the LAST such round found is the one used
(flagged in the printed summary so you can sanity-check it).

Year: derived from the tournament's start date as an academic year
("2022-2023" for a tournament starting in fall 2022). Override with
--year if you want something else written into every row.
"""

import argparse
import copy
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

import openpyxl

HEADERS = [
    "Year",
    "School",
    "Debater 1 First Name",
    "Debater 1 Last Name",
    "Debater 2 First Name",
    "Debater 2 Last Name",
    "Prelim Wins",
    "Prelim Losses",
    "Advanced",
    "Partial Elim",
    "1st Full Win",
    "2nd Full Win",
    "3rd Full Win",
    "4th Full Win",
    "5th Full win",
    "6th Full win",
    "7th Full win",
]
MAX_FULL_WIN_COLS = 7

# When no --category/--event is given, auto-prefer an event whose name/abbr
# matches one of these (checked as a case-insensitive substring), in
# priority order. Tournaments label parli inconsistently -- some just say
# "Parli" or "NPDA", others spell out "Varsity NPDA/NPTE" -- so this list
# covers the common variants rather than assuming a single exact name.
PARLI_EVENT_HINTS = [
    "varsity npda/npte",
    "npda/npte",
    "npda",
    "npte",
    "parliamentary",
    "parli",
]


def _event_hint_score(ev):
    """Lower is a better/earlier match in PARLI_EVENT_HINTS; None = no match."""
    name = (ev.get("name") or "").lower()
    abbr = (ev.get("abbr") or "").lower()
    for i, hint in enumerate(PARLI_EVENT_HINTS):
        if hint in name or hint in abbr:
            return i
    return None

# When no --category/--event is given (e.g. in batch mode, where you can't
# pass per-file overrides), a tournament JSON with multiple divisions
# (Novice/JV/Varsity, etc.) auto-selects the first event whose name matches
# one of these, checked in order, case-insensitively. Add more names here if
# other divisions should also be auto-picked over whatever happens to be
# first in the JSON.
PREFERRED_EVENT_NAMES = [
    "Varsity NPDA/NPTE",
    "NPDA",
]


# ---------------------------------------------------------------- loading --

def load_data(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_categories_and_events(data):
    pairs = []
    for cat in data.get("categories", []):
        for ev in cat.get("events", []):
            pairs.append((cat, ev))
    return pairs


def _event_has_data(ev):
    """An event with zero rounds is an unused/placeholder division slot
    (e.g. a Novice division that didn't run, or a 'Topic Area Tournament'
    stub never actually contested) - it should lose any tie against a
    same-named division that actually has round data."""
    return bool(ev.get("rounds"))


def pick_event(data, category_name, event_name):
    pairs = list_categories_and_events(data)
    if not pairs:
        raise ValueError("No categories/events found in this JSON export.")

    if category_name or event_name:
        for cat, ev in pairs:
            if category_name and cat.get("name") != category_name and cat.get("abbr") != category_name:
                continue
            if event_name and ev.get("name") != event_name and ev.get("abbr") != event_name:
                continue
            return cat, ev
        available = ", ".join(f"{cat.get('name')}/{ev.get('name')}" for cat, ev in pairs)
        raise ValueError(
            f"Couldn't find category={category_name!r} event={event_name!r}. Available: {available}"
        )

    # No explicit override: try to auto-pick the parli event by name/abbr,
    # since tournaments don't all label it the same way.
    scored = [(cat, ev, _event_hint_score(ev)) for cat, ev in pairs]
    matched = [(cat, ev, score) for cat, ev, score in scored if score is not None]
    if matched:
        matched.sort(key=lambda t: t[2])
        best_score = matched[0][2]
        best_matches = [(cat, ev) for cat, ev, score in matched if score == best_score]
        # Ties are common - e.g. "Novice NPDA" and "Open NPDA" both match
        # the "npda" hint equally, as do "NPDA pt. 1" and "NPDA pt. 2". Prefer
        # whichever tied match actually has round data; picking arbitrarily
        # (list order) previously meant an empty placeholder division could
        # silently win over the real one, producing zero usable rows.
        with_data = [(cat, ev) for cat, ev in best_matches if _event_has_data(ev)]
        chosen = with_data or best_matches
        if len(pairs) > 1:
            print(f"Auto-selected event matching {PARLI_EVENT_HINTS[best_score]!r}: "
                  f"{chosen[0][0].get('name')!r}/{chosen[0][1].get('name')!r}. "
                  "Re-run with --category/--event to pick a different one:", file=sys.stderr)
            for cat, ev in pairs:
                print(f"  --category {cat.get('name')!r} --event {ev.get('name')!r}", file=sys.stderr)
        return chosen[0]

    if len(pairs) > 1:
        print("Multiple categories/events found and none matched a known parli name; "
              "using the first one with data. Re-run with --category/--event to pick another:", file=sys.stderr)
        for cat, ev in pairs:
            print(f"  --category {cat.get('name')!r} --event {ev.get('name')!r}", file=sys.stderr)

    with_data = [(cat, ev) for cat, ev in pairs if _event_has_data(ev)]
    return (with_data or pairs)[0]


def build_entry_and_student_maps(data):
    entry_map = {}
    student_map = {}
    for school in data.get("schools", []):
        for student in school.get("students", []):
            student_map[str(student["id"])] = student
        for entry in school.get("entries", []):
            entry_map[str(entry["id"])] = {
                "school": school.get("name", ""),
                "name": entry.get("name", ""),
                "code": entry.get("code", ""),
                "student_ids": [str(sid) for sid in entry.get("students", [])],
            }
    return entry_map, student_map


def academic_year(start_str):
    try:
        dt = datetime.strptime(start_str.split(" ")[0], "%Y-%m-%d")
    except (ValueError, AttributeError):
        return ""
    if dt.month >= 7:
        return f"{dt.year}-{dt.year + 1}"
    return f"{dt.year - 1}-{dt.year}"


# ----------------------------------------------------------- prelim wins --

def find_prelim_result_set(event):
    """Picks whichever result_set actually has usable prelim ballot data,
    rather than trusting tag/label naming alone - real Tabroom exports have
    used tags like "seed" AND "final" for this depending on the tournament,
    and sometimes (as seen with a "Speaker Awards" set) a result_set can have
    a "Ballots" key whose text just doesn't carry per-round W/L letters at
    all. Blindly falling back to result_sets[0] previously produced rows
    with no win/loss data whenever that first set happened to be unusable,
    and - since "Speaker Awards" has one row per STUDENT rather than per
    entry - duplicated every team's row too.
    """
    result_sets = event.get("result_sets", [])
    if not result_sets:
        return None

    def usable(rs):
        keys_by_id = {k["id"]: k for k in rs.get("result_keys", [])}
        has_winpm = any(k.get("tag") == "WinPm" for k in keys_by_id.values())
        if not has_winpm:
            return False
        # Confirm at least one row's Ballots text actually has round-numbered
        # W/L letters in it (the format parse_wins_losses expects) rather
        # than e.g. a flat list of per-round speaker points with no "Rn" tag.
        for row in rs.get("results", [])[:5]:
            for val in row.get("values", []):
                key = keys_by_id.get(val.get("result_key"))
                if key and key.get("tag") == "Ballots":
                    if re.search(r"\bR\d+\s+[WL]\b", val.get("value") or ""):
                        return True
        return False

    # Prefer a set that both looks like a prelim/seed set by name AND is
    # actually usable; then any usable set regardless of name; then fall
    # back to the naming heuristic alone; then just the first set.
    named_candidates = [
        rs for rs in result_sets
        if "seed" in (rs.get("tag") or "").lower() or "prelim" in (rs.get("label") or "").lower()
    ]
    for rs in named_candidates:
        if usable(rs):
            return rs
    for rs in result_sets:
        if usable(rs):
            return rs
    if named_candidates:
        return named_candidates[0]
    return result_sets[0]


def prelim_round_numbers(event):
    """Round numbers (as they appear in Ballots text, e.g. "R3") whose type
    is prelim or power-matched ("highlow"/"highhigh") - i.e. NOT elim/final.
    Needed because a result_set's Ballots text can be one combined string
    covering a team's entire tournament (prelims AND elims together), so
    counting every "Rn W"/"Rn L" in it without filtering would fold
    elim-round outcomes into the prelim win/loss tally."""
    numbers = set()
    for rnd in event.get("rounds", []):
        if rnd.get("type") in ("prelim", "highlow", "highhigh"):
            try:
                numbers.add(int(rnd.get("name")))
            except (TypeError, ValueError):
                pass
    return numbers


def parse_wins_losses(result_row, result_keys_by_id, prelim_round_nums=None):
    wins_from_key = None
    ballots_text = None
    for val in result_row.get("values", []):
        key = result_keys_by_id.get(val.get("result_key"))
        if not key:
            continue
        tag = key.get("tag", "")
        if tag == "WinPm":
            try:
                wins_from_key = float(val.get("value"))
            except (TypeError, ValueError):
                pass
        elif tag == "Ballots":
            ballots_text = val.get("value")

    if ballots_text:
        # Majority-vote per round rather than just the first letter after
        # "Rn" - a single-letter prelim round's majority is trivially that
        # letter, but this also gets a multi-judge panel round right
        # (see parse_round_letter_outcomes' docstring).
        outcomes = parse_round_letter_outcomes(ballots_text)
        if prelim_round_nums:
            outcomes = {n: o for n, o in outcomes.items() if n in prelim_round_nums}
        if outcomes:
            wins = sum(1 for o in outcomes.values() if o == "win")
            losses = sum(1 for o in outcomes.values() if o == "loss")
            return wins, losses

    if wins_from_key is not None:
        return int(wins_from_key), None

    return None, None


# ------------------------------------------------------------- elim logic --

def event_has_ballot_scores(event):
    """Whether ANY ballot anywhere in this event's round data carries a
    'winloss' score at all. Some Tabroom exports include full round/
    section/ballot structure (who debated whom, in which section) but no
    "scores" key on any ballot whatsoever - not just missing winloss
    values, the key itself is absent from every ballot. When that's the
    case, analyze_prelim_rounds() and the score-based half of
    analyze_elim_rounds() have literally nothing to compute a winner
    from, and silently fall back to "everyone's tied at 0" tie-breaking
    (which picks whichever entry happens first in ballot-list order,
    producing a fabricated result) or, for elim rounds, never record a
    result for anyone at all (leaving every entry looking like it never
    advanced). Both are wrong whenever this returns False - the caller
    should use the tournament's own posted Ballots-text summary instead,
    which is reliable in exactly this situation."""
    for rnd in event.get("rounds", []):
        for section in rnd.get("sections", []):
            for ballot in section.get("ballots", []):
                for score in ballot.get("scores") or []:
                    if score.get("tag") == "winloss":
                        return True
    return False


def parse_round_letter_outcomes(ballots_text):
    """Parses a Ballots-text string into {round_number: 'win'|'loss'}.

    Each "Rn" marker is followed by that round's judge letter(s) - a
    single-judge or already-decided prelim round shows exactly one W/L
    letter (e.g. "R1  W  29.3, 29.2"), but a multi-judge elim panel shows
    one letter PER JUDGE plus a "(m-k)" tally (e.g. "R7  W  L  L  (1-2)").
    Naively taking the first letter after "Rn" (as the original prelim-
    only regex did) is correct for the former but wrong for the latter
    whenever the first-listed judge's vote isn't the panel majority - so
    this counts every W/L letter in the round's chunk and takes the
    majority instead, which is correct for both formats (a single-letter
    round is trivially its own majority)."""
    outcomes = {}
    for m in re.finditer(r"R(\d+)(.*?)(?=R\d+|$)", ballots_text, re.S):
        round_num = int(m.group(1))
        letters = re.findall(r"(?<![A-Za-z])([WL])(?![A-Za-z])", m.group(2))
        wins, losses = letters.count("W"), letters.count("L")
        if wins > losses:
            outcomes[round_num] = "win"
        elif losses > wins:
            outcomes[round_num] = "loss"
        # an exact tie (only possible with an even-sized panel) is left
        # out rather than guessed at
    return outcomes


def collect_ballots_by_entry(event):
    """{entry_id: Ballots-text} using, for each entry, the LONGEST
    Ballots-text string found across every result_set - different
    result_sets (seed/bracket/final/...) can carry a partial vs. a fully
    combined prelim+elim history for the same entry, and the longest one
    seen is a reliable proxy for "most complete" regardless of which tag
    name a given tournament happens to use."""
    best = {}
    for rs in event.get("result_sets", []):
        keys_by_id = {k["id"]: k for k in rs.get("result_keys", [])}
        for row in rs.get("results", []):
            entry_id = str(row.get("entry"))
            for val in row.get("values", []):
                key = keys_by_id.get(val.get("result_key"))
                if key and key.get("tag") == "Ballots":
                    text = val.get("value") or ""
                    if len(text) > len(best.get(entry_id, "")):
                        best[entry_id] = text
    return best


def analyze_elim_rounds(event, ballots_by_entry=None):
    """Returns (per_entry_round_status, partial_info)

    per_entry_round_status: {entry_id: {round_index (0-based): 'win'|'loss'|'bye'}}
    partial_info: {'round_index': int, 'fraction': float} or None

    ballots_by_entry (optional): the result of collect_ballots_by_entry(event),
    used per-debate whenever that specific section has no ballot-level
    winloss scores (not just when the whole event lacks them - prelims
    can be fully scored while elims haven't been judged yet at all, e.g.
    an export pulled mid-tournament before outrounds happen). Round
    debate-counts/bye detection stay structural (which entries appear in
    a round's sections) either way, since that never depended on scores
    being present in the first place. A debate with neither scores nor
    Ballots-text for either entry is left undetermined rather than
    guessed at.
    """
    elim_rounds = sorted(
        (r for r in event.get("rounds", []) if r.get("type") in ("elim", "final")),
        key=lambda r: r.get("name", 0),
    )

    per_entry_status = defaultdict(dict)
    round_debate_counts = []  # actual number of real (2-sided) debates per round

    for round_idx, rnd in enumerate(elim_rounds):
        section_scores = defaultdict(lambda: defaultdict(float))  # section_id -> entry_id -> summed winloss
        section_entries = defaultdict(list)  # section_id -> [entry_id, ...] seen, regardless of scores
        for section in rnd.get("sections", []):
            sec_id = section.get("id")
            for ballot in section.get("ballots", []):
                entry_id = str(ballot.get("entry"))
                if entry_id not in section_entries[sec_id]:
                    section_entries[sec_id].append(entry_id)
                for score in ballot.get("scores") or []:
                    if score.get("tag") == "winloss":
                        try:
                            section_scores[sec_id][entry_id] += float(score.get("value", 0))
                        except (TypeError, ValueError):
                            pass

        winners, losers, byes = set(), set(), set()
        real_debate_count = 0
        for sec_id, seen in section_entries.items():
            if len(seen) >= 2:
                real_debate_count += 1
                entries = section_scores[sec_id]
                if entries:
                    # Scores exist for at least one side of this debate -
                    # trust them (defaulting a scoreless entry to 0 rather
                    # than letting it vanish from consideration, same as
                    # analyze_prelim_rounds does).
                    for entry_id in seen:
                        entries.setdefault(entry_id, 0.0)
                    winner_id = max(entries, key=entries.get)
                    for entry_id in seen:
                        if entry_id == winner_id:
                            winners.add(entry_id)
                        else:
                            losers.add(entry_id)
                elif ballots_by_entry:
                    round_num = rnd.get("name")
                    for entry_id in seen:
                        outcome = parse_round_letter_outcomes(
                            ballots_by_entry.get(entry_id, "")
                        ).get(round_num)
                        if outcome == "win":
                            winners.add(entry_id)
                        elif outcome == "loss":
                            losers.add(entry_id)
                        # unknown outcome (no Ballots text for this entry/
                        # round) is left unrecorded rather than guessed
                # else: no scores and no Ballots-text for this debate at
                # all - genuinely no data yet (e.g. an elim round that
                # hasn't been judged). Leave undetermined rather than
                # fabricating a winner or crashing on an empty max().
            elif len(seen) == 1:
                # only one entry recorded for this section: a bye
                byes.add(seen[0])

        for entry_id in winners:
            per_entry_status[entry_id][round_idx] = "win"
        for entry_id in losers:
            per_entry_status[entry_id][round_idx] = "loss"
        for entry_id in byes:
            per_entry_status[entry_id][round_idx] = "bye"

        round_debate_counts.append(real_debate_count)

    n_rounds = len(elim_rounds)

    # Some byes aren't represented as a single-entry section at all -- the
    # entry simply doesn't appear anywhere in that round and shows up
    # straight in the next one. In a single-elim bracket the only way to
    # reach round k+1 without a recorded result in round k is a bye, so
    # backfill those in.
    for round_idx in range(n_rounds - 1):
        entries_next = set(per_entry_status.keys()) & {
            eid for eid, statuses in per_entry_status.items() if (round_idx + 1) in statuses
        }
        for entry_id in entries_next:
            if round_idx not in per_entry_status[entry_id]:
                per_entry_status[entry_id][round_idx] = "bye"
    partial_info = None
    for round_idx in range(n_rounds):
        expected = 2 ** (n_rounds - 1 - round_idx)
        actual = round_debate_counts[round_idx]
        if actual < expected and actual > 0:
            fraction = actual / expected
            partial_info = {"round_index": round_idx, "fraction": fraction}
            # keep scanning; if multiple rounds are short we keep the last one

    return per_entry_status, partial_info, n_rounds


def full_win_flags(entry_id, per_entry_status, partial_round_idx=None):
    """Nth Full Win corresponds to the Nth *real, full-strength* elim round
    the field played - the partial (bye-shortened) round, if any, is
    excluded from this numbering entirely, not just skipped for bye
    recipients. A win in the partial round is Partial Elim credit only
    (see partial_elim_value), matching how the tabulation-desk scrapers for
    other tabulation platforms treat a short first round.

    Without this exclusion, every entry that received a bye in the partial
    round (the common case - that's why the round was short) shows False
    in its "first" round instead of the numbering simply not counting that
    round at all, so every real win after it lands one column later than
    it should: an entry who was bye/win/win/win over Doubles-Octos-Quarters-
    Semis showed False/True/True/True across columns 1-4 instead of
    True/True/True across columns 1-3."""
    statuses = per_entry_status.get(entry_id, {})
    max_round = max(statuses.keys(), default=-1)
    flags = []
    for round_idx in range(max_round + 1):
        if round_idx == partial_round_idx:
            continue
        flags.append(statuses.get(round_idx) == "win")
    flags = flags[:MAX_FULL_WIN_COLS]
    while len(flags) < MAX_FULL_WIN_COLS:
        flags.append(False)
    return flags


def partial_elim_value(entry_id, per_entry_status, partial_info):
    if partial_info is None:
        return 0
    round_idx = partial_info["round_index"]
    status = per_entry_status.get(entry_id, {}).get(round_idx)
    if status in ("win", "bye"):
        return partial_info["fraction"]
    return 0


# --------------------------------------------------------------- assembly --

def analyze_prelim_rounds(event):
    """Returns {entry_id: (wins, losses)} computed directly from ballot
    winloss scores in prelim/power-matched rounds - "highlow" AND
    "highhigh" both occur across real tournaments depending on how a given
    round was paired, and both are prelim rounds, not just "highlow". This
    reads the same raw round/section/ballot data analyze_elim_rounds
    already uses for outrounds, rather than depending on a result_set -
    some Tabroom exports have no result_sets at all yet (results not
    "posted" in that sense) even though the underlying round data is fully
    there, and this works regardless."""
    tallies = defaultdict(lambda: [0, 0])  # entry_id -> [wins, losses]
    for rnd in event.get("rounds", []):
        if rnd.get("type") not in ("prelim", "highlow", "highhigh"):
            continue
        for section in rnd.get("sections", []):
            entry_ids_here = []  # every entry with a ballot in this section,
            entry_scores = defaultdict(float)  # regardless of whether it carries a score
            for ballot in section.get("ballots", []):
                entry_id = str(ballot.get("entry"))
                if entry_id not in entry_ids_here:
                    entry_ids_here.append(entry_id)
                for score in ballot.get("scores") or []:
                    if score.get("tag") == "winloss":
                        try:
                            entry_scores[entry_id] += float(score.get("value", 0))
                        except (TypeError, ValueError):
                            pass

            if len(entry_ids_here) >= 2:
                # A ballot's "scores" key can be entirely absent even in a
                # real 2-entry debate; treat a missing winloss as 0 rather
                # than letting that entry vanish from consideration.
                for eid in entry_ids_here:
                    entry_scores.setdefault(eid, 0.0)
                winner_id = max(entry_scores, key=entry_scores.get)
                for entry_id in entry_ids_here:
                    if entry_id == winner_id:
                        tallies[entry_id][0] += 1
                    else:
                        tallies[entry_id][1] += 1
            elif len(entry_ids_here) == 1:
                # A prelim bye: only one entry has a ballot in this section
                # at all - whether or not that ballot happens to carry an
                # explicit winloss score (some exports record a bye as
                # winloss=1, others omit "scores" from the ballot entirely).
                # Tabroom's own Ballots-text record counts a bye as a WIN
                # (confirmed against several tournaments' result_sets) -
                # crediting neither a win nor a loss here undercounted every
                # bye recipient's win total by exactly one, and dropped the
                # round from their tally altogether when "scores" was absent.
                tallies[entry_ids_here[0]][0] += 1
    return {eid: (int(w), int(l)) for eid, (w, l) in tallies.items()}


def collect_event_entries(event):
    """Every entry_id that appears anywhere in the event's round data.
    Used when there's no result_set to enumerate entries from at all."""
    ids = set()
    for rnd in event.get("rounds", []):
        for section in rnd.get("sections", []):
            for ballot in section.get("ballots", []):
                if ballot.get("entry") is not None:
                    ids.add(str(ballot.get("entry")))
    return ids


def _matches_hint_word(cat, ev, word):
    text = f"{cat.get('name') or ''} {ev.get('name') or ''} {ev.get('abbr') or ''}".lower()
    return word in text


def find_npda_and_npte_events(data):
    """Detects tournaments that ran NPDA and NPTE as two genuinely separate
    events in the same JSON (e.g. one category named 'NPDA', another named
    'NPTE', each with its own real round data) - these should produce two
    separate tabs rather than the normal single auto-pick silently keeping
    only one. Returns (npda_pair, npte_pair), either of which is None if
    that format isn't present as its own real (non-empty) event.

    Deliberately requires real round data on both sides and excludes any
    event matching *both* words (e.g. a combined "Varsity NPDA/NPTE" event,
    or an empty same-tournament placeholder that merely happens to be
    abbreviated "NPTE" while the real data lives in a separately-named
    "NPDA" event) - those are single-event tournaments and should go
    through the normal pick_event path instead."""
    pairs = list_categories_and_events(data)
    npda_cands = [(c, e) for c, e in pairs if _matches_hint_word(c, e, "npda") and _event_has_data(e)]
    npte_cands = [(c, e) for c, e in pairs if _matches_hint_word(c, e, "npte") and _event_has_data(e)]
    npda_only = [p for p in npda_cands if p not in npte_cands]
    npte_only = [p for p in npte_cands if p not in npda_cands]
    npda_pair = npda_only[0] if npda_only else None
    npte_pair = npte_only[0] if npte_only else None
    if npda_pair and npte_pair:
        return npda_pair, npte_pair
    return None, None


def build_rows(data, category_name=None, event_name=None, year_override=None):
    category, event = pick_event(data, category_name, event_name)
    return build_rows_for_event(data, category, event, year_override)


def build_rows_for_event(data, category, event, year_override=None):
    entry_map, student_map = build_entry_and_student_maps(data)

    # Some Tabroom exports carry full round/section/ballot structure but
    # no "scores" key on any ballot at all - not spotty, just absent
    # tournament-wide. analyze_prelim_rounds()/analyze_elim_rounds()'s
    # score-based logic can't compute anything real from that (see
    # event_has_ballot_scores' docstring) and must not be trusted; fall
    # back to the tournament's own posted Ballots-text summary instead,
    # for prelims AND elims, rather than silently producing made-up wins/
    # losses and an empty (looks-like-nobody-advanced) elim record.
    has_scores = event_has_ballot_scores(event)
    if not has_scores:
        print("  [WARNING] This event's ballots carry no winloss score data at all - "
              "falling back to the tournament's posted Ballots-text for both prelim "
              "and elim results instead of the round/ballot data.", file=sys.stderr)

    # Ground truth for prelim wins/losses: computed straight from ballot
    # data, so it doesn't depend on a result_set existing at all, let alone
    # picking the right one. Skipped entirely when there's no score data
    # to compute it from (see above) so the Ballots-text fallback below
    # is used for every entry instead of a fabricated tally.
    prelim_tally = analyze_prelim_rounds(event) if has_scores else {}

    result_set = find_prelim_result_set(event)
    result_keys_by_id = {}
    prelim_rounds = set()
    result_rows_by_entry = {}
    if result_set is not None:
        result_keys_by_id = {k["id"]: k for k in result_set.get("result_keys", [])}
        prelim_rounds = prelim_round_numbers(event)
        for result_row in result_set.get("results", []):
            eid = str(result_row.get("entry"))
            result_rows_by_entry.setdefault(eid, result_row)  # first one wins on dupes

    # Always computed (not gated on has_scores): analyze_elim_rounds() now
    # decides per-debate whether to trust scores or fall back to this,
    # since prelims and elims can differ in whether they're scored yet
    # (e.g. an export pulled mid-tournament, prelims judged but outrounds
    # not yet entered).
    ballots_by_entry = collect_ballots_by_entry(event)
    per_entry_status, partial_info, n_elim_rounds = analyze_elim_rounds(event, ballots_by_entry)
    year = year_override or academic_year(data.get("start", ""))

    # Entries to output: prefer whatever a result_set enumerates (keeps the
    # tournament's own ranking order); if there's no result_set at all,
    # fall back to every entry seen anywhere in the round data.
    if result_rows_by_entry:
        entry_ids = list(result_rows_by_entry.keys())
    else:
        entry_ids = sorted(collect_event_entries(event))

    rows = []
    for entry_id in entry_ids:
        entry = entry_map.get(entry_id)
        if entry is None:
            continue

        if entry_id in prelim_tally:
            wins, losses = prelim_tally[entry_id]
        elif entry_id in result_rows_by_entry:
            wins, losses = parse_wins_losses(result_rows_by_entry[entry_id], result_keys_by_id, prelim_rounds)
        else:
            wins, losses = None, None

        student_ids = entry["student_ids"]
        debaters = []
        for sid in student_ids[:2]:
            s = student_map.get(sid, {})
            debaters.append((s.get("first", ""), s.get("last", "")))
        while len(debaters) < 2:
            debaters.append(("", ""))

        advanced = entry_id in per_entry_status
        full_wins = full_win_flags(
            entry_id, per_entry_status,
            partial_info["round_index"] if partial_info else None,
        )
        partial_elim = partial_elim_value(entry_id, per_entry_status, partial_info)

        result_row = result_rows_by_entry.get(entry_id)
        rank = result_row.get("rank") if result_row else None
        if rank is None:
            # No result_set rank available - order by prelim record instead
            # (best win count, then fewest losses) so the sheet still comes
            # out in a sensible, deterministic order.
            rank = (-(wins or 0), losses if losses is not None else 999)
        rows.append({
            "rank": rank,
            "year": year,
            "school": entry["school"],
            "d1_first": debaters[0][0],
            "d1_last": debaters[0][1],
            "d2_first": debaters[1][0],
            "d2_last": debaters[1][1],
            "wins": wins if wins is not None else "",
            "losses": losses if losses is not None else "",
            "advanced": advanced,
            "partial_elim": partial_elim,
            "full_wins": full_wins,
        })

    # rank is either a plain int (from a result_set) or a (-wins, losses)
    # tuple (the no-result_set fallback) - normalize so sorting never mixes
    # incomparable types even if one somehow slipped in per-row.
    def _sort_key(r):
        rank = r["rank"]
        return (1, rank) if isinstance(rank, tuple) else (0, rank)

    rows.sort(key=_sort_key)
    return rows, category, event, partial_info, n_elim_rounds


# ------------------------------------------------------------------ xlsx --

def sheet_name_for(data, event, label=None):
    year = academic_year(data.get("start", ""))
    tourney_year = year.split("-")[0] if year else ""
    name = data.get("name") or event.get("name") or "Tournament"
    base = f"{name} - {tourney_year}" if tourney_year else name
    if label:
        base = f"{base} ({label})"
    return base[:31]  # Excel sheet name limit


def write_rows_to_sheet(ws, rows, header_row=4):
    """Writes headers at `header_row` and data starting the row after it,
    matching the "Data Entry Template" layout sync_ingest.py expects
    (header row 4, data from row 5), leaving rows 1-3 free for a title/
    notes block."""
    for col_idx, header in enumerate(HEADERS, start=1):
        ws.cell(row=header_row, column=col_idx, value=header)

    for i, row in enumerate(rows, start=header_row + 1):
        values = [
            row["year"], row["school"], row["d1_first"], row["d1_last"],
            row["d2_first"], row["d2_last"], row["wins"], row["losses"],
            row["advanced"], row["partial_elim"],
        ] + row["full_wins"]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row=i, column=col_idx, value=value)


def write_new_file(sheets, output_path):
    """sheets: list of (sheet_name, rows) tuples - normally one, or two for
    a tournament that ran NPDA and NPTE as separate events."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(title=name[:31])
        write_rows_to_sheet(ws, rows)
    wb.save(output_path)


def append_to_master(sheets, master_path, output_path):
    """sheets: list of (sheet_name, rows) tuples - see write_new_file."""
    wb = openpyxl.load_workbook(master_path)

    # Match an existing sheet's formatting (font) if any sheet already exists
    template_font = None
    if wb.sheetnames:
        existing = wb[wb.sheetnames[0]]
        if existing.max_row >= 5:
            template_font = copy.copy(existing.cell(row=5, column=1).font)

    for name, rows in sheets:
        name = name[:31]
        if name in wb.sheetnames:
            del wb[name]
        ws = wb.create_sheet(title=name)

        write_rows_to_sheet(ws, rows)

        if template_font is not None:
            for row in ws.iter_rows(min_row=5, max_row=ws.max_row, max_col=len(HEADERS)):
                for cell in row:
                    cell.font = template_font

    wb.save(output_path)


# ------------------------------------------------------------ batch mode --

BATCH_OUTPUT_NAME = "Tabroom Ingest Data.xlsx"


def unique_sheet_name(base_name, used_names):
    """Excel sheet names must be unique and <=31 chars; dedupe by suffixing
    ' (2)', ' (3)', etc., trimming the base so the suffix still fits."""
    name = base_name[:31]
    if name not in used_names:
        used_names.add(name)
        return name
    n = 2
    while True:
        suffix = f" ({n})"
        trimmed = base_name[: 31 - len(suffix)]
        candidate = f"{trimmed}{suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        n += 1


def run_batch_folder(folder, category_name=None, event_name=None, year_override=None):
    """Process every *.json file in `folder` and (re)write
    '<folder>/Tabroom Ingest Data.xlsx' from scratch, one sheet per
    tournament JSON found."""
    json_paths = sorted(
        p for p in os.listdir(folder)
        if p.lower().endswith(".json")
    )
    if not json_paths:
        print(f"No .json files found in {folder!r}. "
              f"Drop your Tabroom JSON export(s) in this folder and re-run.")
        return

    output_path = os.path.join(folder, BATCH_OUTPUT_NAME)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop the default blank sheet; we add one per tournament
    used_names = set()

    processed = 0
    for filename in json_paths:
        full_path = os.path.join(folder, filename)
        try:
            data = load_data(full_path)
        except Exception as exc:  # noqa: BLE001 - keep batch going on a bad file
            print(f"  [SKIPPED] {filename}: {exc}")
            continue

        npda_pair, npte_pair = (None, None) if (category_name or event_name) else find_npda_and_npte_events(data)
        if npda_pair and npte_pair:
            plan = [("NPDA", *npda_pair), ("NPTE", *npte_pair)]
        else:
            try:
                cat, ev = pick_event(data, category_name, event_name)
            except Exception as exc:  # noqa: BLE001
                print(f"  [SKIPPED] {filename}: {exc}")
                continue
            plan = [(None, cat, ev)]

        for label, category, event in plan:
            try:
                rows, category, event, partial_info, n_elim_rounds = build_rows_for_event(
                    data, category, event, year_override
                )
            except Exception as exc:  # noqa: BLE001 - keep batch going on a bad file
                print(f"  [SKIPPED] {filename} ({label or event.get('name')}): {exc}")
                continue

            sheet_name = unique_sheet_name(sheet_name_for(data, event, label), used_names)
            ws = wb.create_sheet(title=sheet_name)
            write_rows_to_sheet(ws, rows)

            print(f"  [OK] {filename}{f' [{label}]' if label else ''} -> sheet {sheet_name!r} "
                  f"({len(rows)} entries, {n_elim_rounds} elim round(s)"
                  + (f", partial round fraction {partial_info['fraction']:.4f}" if partial_info else "")
                  + ")")
            processed += 1

    if processed == 0:
        print("No tournament sheets were generated (every JSON file failed to parse). "
              f"{output_path} was not written.")
        return

    wb.save(output_path)
    print(f"\nWrote {output_path} ({processed} sheet(s)).")


# ---------------------------------------------------------------- main() --

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_path", nargs="?", default=None,
                         help="Path to a single Tabroom tournament JSON export. "
                              "Omit this (and output_path) to instead process every "
                              f".json file in the current folder into {BATCH_OUTPUT_NAME!r}.")
    parser.add_argument("output_path", nargs="?", default=None,
                         help="Path to write the output .xlsx (single-file mode only)")
    parser.add_argument("--category", default=None, help="Category name to use, e.g. 'NPDA'")
    parser.add_argument("--event", default=None, help="Event name to use, e.g. 'NPDA'")
    parser.add_argument("--master", default=None,
                         help="Path to an existing Master_Tournament_Tabs.xlsx to append a new sheet to "
                              "(instead of writing a plain new file). Single-file mode only.")
    parser.add_argument("--sheet-name", default=None, help="Override the auto-generated sheet name (single-file mode only)")
    parser.add_argument("--year", default=None, help="Override the auto-derived academic year, e.g. '2022-2023'")
    parser.add_argument("--folder", default=None,
                         help="Folder to batch-process (defaults to the current directory) when "
                              "json_path/output_path are omitted.")
    args = parser.parse_args()

    if args.json_path is None and args.output_path is None:
        folder = args.folder or os.getcwd()
        print(f"Batch mode: scanning {folder!r} for .json files...")
        run_batch_folder(folder, args.category, args.event, args.year)
        return

    if args.json_path is None or args.output_path is None:
        parser.error("json_path and output_path must both be given (or both omitted for batch mode).")

    data = load_data(args.json_path)

    if args.category or args.event:
        plan = [(None, *pick_event(data, args.category, args.event))]
    else:
        npda_pair, npte_pair = find_npda_and_npte_events(data)
        if npda_pair and npte_pair:
            print("Detected separate NPDA and NPTE events in this JSON - writing both to separate tabs.")
            plan = [("NPDA", *npda_pair), ("NPTE", *npte_pair)]
        else:
            plan = [(None, *pick_event(data, args.category, args.event))]

    sheets = []
    for label, category, event in plan:
        rows, category, event, partial_info, n_elim_rounds = build_rows_for_event(
            data, category, event, args.year
        )

        print(f"Using category={category.get('name')!r} event={event.get('name')!r}")
        print(f"Found {len(rows)} entries with prelim results.")
        print(f"Found {n_elim_rounds} elimination round(s).")
        if partial_info:
            print(f"Partial round detected: elim round index {partial_info['round_index']} "
                  f"(0-based, chronological) -> fraction {partial_info['fraction']:.4f}")
        else:
            print("No partial (bye-affected) elim round detected; Partial Elim = 0 for all entries.")

        if args.sheet_name and len(plan) == 1:
            sheet_name = args.sheet_name
        else:
            sheet_name = sheet_name_for(data, event, label)
        sheets.append((sheet_name, rows))

    if args.master:
        append_to_master(sheets, args.master, args.output_path)
        print(f"Wrote {args.output_path} (added/replaced sheet(s) {', '.join(n for n, _ in sheets)})")
    else:
        write_new_file(sheets, args.output_path)
        print(f"Wrote {args.output_path}")


if __name__ == "__main__":
    main()

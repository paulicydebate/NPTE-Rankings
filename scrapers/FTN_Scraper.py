import pandas as pd
import pdfplumber
import re
import glob
import os

# Known elimination round names -> priority for determining the tournament's
# earliest/first elim round (lower = earlier in the bracket). Unknown round
# names (e.g. a tournament-specific label) fall back to a high number so they
# never get mistaken for the "first" round.
ROUND_PRIORITY = {
    "DOUBLE OCTOS": 1, "OCTOS": 2, "QUARTERS": 3, "SEMIS": 4,
    "BRONZE": 5, "GOLD": 6, "FINALS": 7,
}
FULL_BRACKET_SIZE = {
    "DOUBLE OCTOS": 32, "OCTOS": 16, "QUARTERS": 8, "SEMIS": 4, "BRONZE": 4,
}


def _norm(cell):
    """Collapse a table cell's internal line-wraps/whitespace into single spaces."""
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def _is_team_header_row(row):
    """A genuine team-summary row: cell0 = 'School - D1 & D2', and somewhere
    in the row the phrase 'Total Points' appears EXACTLY once. (The junk
    full-page 'blob' tables pdfplumber sometimes also detects contain the
    phrase many times, since they smash the whole page into one cell - this
    filters those out.)"""
    if not row or not row[0]:
        return False
    cell0 = _norm(row[0])
    if " - " not in cell0 or " & " not in cell0:
        return False
    joined = " ".join(_norm(c) for c in row if c)
    return joined.count("Total Points") == 1 and "Wins" in joined


def _is_column_header_row(row):
    return (
        row and len(row) > 1 and row[0] and row[1]
        and _norm(row[0]).lower() == "rd"
        and _norm(row[1]).lower() == "side"
    )


def _is_round_data_row(row):
    """A real round row always has Side = Aff/Neg (NPDA-style) or Gov/Opp
    (Parliamentary-style). This is a much more reliable discriminator than
    pattern-matching the round-name cell, because it can never be confused
    with prelim-round opponent text."""
    if not row or len(row) < 5:
        return False
    if not row[1]:
        return False
    side = _norm(row[1]).lower()
    return side in ("aff", "neg", "gov", "opp") and row[0] is not None


def parse_ftn_pdf_dynamic(pdf_path, season_year="2025-2026"):
    teams_dict = {}
    current_key = None
    max_prelim_round = 0  # discovered from "Rd N" labels - NOT assumed to be 4

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if _is_team_header_row(row):
                        cell0 = _norm(row[0])
                        wins_cell = next(
                            (c for c in row if c and "Wins" in _norm(c)), ""
                        )
                        m_name = re.match(r"^(.+?)\s*-\s*(.+?)\s*&\s*(.+)$", cell0)
                        m_wins = re.search(r"(\d+)\s*Wins?", _norm(wins_cell))
                        if not (m_name and m_wins):
                            continue

                        school = m_name.group(1).strip()
                        d1_clean = re.sub(r"\s*\(.*?\)", "", m_name.group(2)).strip()
                        d2_clean = re.sub(r"\s*\(.*?\)", "", m_name.group(3)).strip()
                        wins = int(m_wins.group(1))

                        d1_parts, d2_parts = d1_clean.split(), d2_clean.split()
                        d1_first = d1_parts[0] if d1_parts else ""
                        d1_last = d1_parts[-1] if len(d1_parts) > 1 else ""
                        d2_first = d2_parts[0] if d2_parts else ""
                        d2_last = d2_parts[-1] if len(d2_parts) > 1 else ""

                        current_key = (school.lower(), d1_last.lower(), d2_last.lower())

                        if current_key not in teams_dict:
                            teams_dict[current_key] = {
                                "Year": season_year,
                                "School": school,
                                "Debater 1 First Name": d1_first,
                                "Debater 1 Last Name": d1_last,
                                "Debater 2 First Name": d2_first,
                                "Debater 2 Last Name": d2_last,
                                "Prelim Wins": wins,
                                "Advanced": wins >= 3,
                                "Partial Elim": 0,
                                "ElimRounds": [],
                            }
                        else:
                            # Header re-appears on a page-break continuation;
                            # ElimRounds is NOT reset, only wins refreshed if higher.
                            if wins > teams_dict[current_key]["Prelim Wins"]:
                                teams_dict[current_key]["Prelim Wins"] = wins
                                if wins >= 3:
                                    teams_dict[current_key]["Advanced"] = True
                        continue

                    if _is_column_header_row(row):
                        continue

                    if current_key and _is_round_data_row(row):
                        round_label = _norm(row[0])
                        is_prelim = round_label.upper().startswith("RD")
                        if is_prelim:
                            # Prelim W/L totals come from the header count, not
                            # these rows - but the row label ("Rd 1".."Rd N")
                            # is the only place the tournament's actual number
                            # of prelim rounds is recorded, so track its max
                            # instead of assuming every tournament runs 4.
                            m_round_num = re.search(r"(\d+)", round_label)
                            if m_round_num:
                                max_prelim_round = max(max_prelim_round, int(m_round_num.group(1)))
                            continue

                        decision = _norm(row[4]) if len(row) > 4 else ""
                        opponent = _norm(row[2]) if len(row) > 2 else ""
                        judge = _norm(row[3]) if len(row) > 3 else ""

                        team_won = decision.strip().upper().startswith("W")
                        # A true bye is signaled ONLY by the opponent placeholder "ZZ".
                        # Some real pairings (e.g. two teams from the same school forced
                        # to meet with no eligible judges left) get a "zz-bye" filler in
                        # the judge column even though a real opponent is listed - that
                        # round still counts as having occurred and must NOT be treated
                        # as a bye just because "bye" appears in the judge text.
                        has_bye = opponent.strip().upper() == "ZZ"

                        teams_dict[current_key]["Advanced"] = True
                        teams_dict[current_key]["ElimRounds"].append(
                            (round_label.upper(), team_won, has_bye)
                        )

    # Determine the tournament's earliest elim round across all teams
    tournament_first_round = None
    min_priority = 99
    for team_data in teams_dict.values():
        for r_name, _, _ in team_data["ElimRounds"]:
            p = ROUND_PRIORITY.get(r_name, 99)
            if p < min_priority:
                min_priority = p
                tournament_first_round = r_name

    # Count total / bye teams ONLY in that first round, to size the bracket
    first_round_total = first_round_byes = 0
    if tournament_first_round:
        for team_data in teams_dict.values():
            rounds_here = [r for r in team_data["ElimRounds"] if r[0] == tournament_first_round]
            if rounds_here:
                first_round_total += 1
                if rounds_here[0][2]:
                    first_round_byes += 1

    partial_val = 0
    if first_round_byes > 0 and tournament_first_round:
        full_team_count = FULL_BRACKET_SIZE.get(tournament_first_round, 8)
        partial_val = round((first_round_total - first_round_byes) / full_team_count, 4)

    records = []
    total_prelim_rounds = max_prelim_round or 4  # fallback only if no "Rd N" rows were found at all
    for team_data in teams_dict.values():
        elim_rounds = team_data.pop("ElimRounds")
        wins = team_data["Prelim Wins"]
        team_data["Prelim Losses"] = total_prelim_rounds - wins if wins <= total_prelim_rounds else 0

        seen, unique_rounds = set(), []
        for r in elim_rounds:
            if r[0] not in seen:
                seen.add(r[0])
                unique_rounds.append(r)

        full_wins = []
        source_rounds = unique_rounds[1:] if partial_val > 0 else unique_rounds
        for r_name, r_win, r_bye in source_rounds:
            if r_win:
                full_wins.append(True)

        # Partial Elim is credit for winning the tournament's under-strength
        # first round - it belongs only to the team(s) who actually won that
        # specific round (whether by a real win or a bye), not to everyone
        # who merely played in it or advanced further afterward.
        won_first_round = bool(unique_rounds) and unique_rounds[0][0] == tournament_first_round and unique_rounds[0][1]
        team_data["Partial Elim"] = partial_val if won_first_round else 0
        col_names = [
            "1st Full Win", "2nd Full Win", "3rd Full Win", "4th Full Win",
            "5th Full win", "6th Full win", "7th Full win",
        ]
        for i, col in enumerate(col_names):
            team_data[col] = i < len(full_wins) and full_wins[i]

        records.append(team_data)

    df = pd.DataFrame(records)
    if not df.empty:
        # Enforce a fixed column order rather than relying on dict insertion
        # order, which shifted once "Prelim Losses" started being filled in
        # during the later records pass instead of at initial creation.
        column_order = [
            "Year", "School",
            "Debater 1 First Name", "Debater 1 Last Name",
            "Debater 2 First Name", "Debater 2 Last Name",
            "Prelim Wins", "Prelim Losses", "Advanced", "Partial Elim",
            "1st Full Win", "2nd Full Win", "3rd Full Win", "4th Full Win",
            "5th Full win", "6th Full win", "7th Full win",
        ]
        df = df[column_order]
        df.sort_values(by="Advanced", ascending=False, inplace=True)
        df = df.drop_duplicates(
            subset=["Year", "School", "Debater 1 First Name", "Debater 1 Last Name",
                    "Debater 2 First Name", "Debater 2 Last Name"],
            keep="first",
        )
    return df


def process_all_pdfs_to_multitab_excel(season_year="2025-2026"):
    pdf_files = glob.glob("*.pdf")
    if not pdf_files:
        print("Error: No PDF files found in this folder!")
        return

    output_excel = "Master_Tournament_Tabs.xlsx"
    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        for pdf in pdf_files:
            sheet_name = os.path.splitext(os.path.basename(pdf))[0][:31]
            print(f"Scraping '{pdf}' -> writing to Excel sheet tab '{sheet_name}'...")
            df_pdf = parse_ftn_pdf_dynamic(pdf, season_year)
            df_pdf.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"Success! Multi-data workbook saved to: {os.path.abspath(output_excel)}")


if __name__ == "__main__":
    process_all_pdfs_to_multitab_excel("2025-2026")
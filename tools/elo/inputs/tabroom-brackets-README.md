# Tabroom bracket reconstructions (open NPDA elims)
Override files: mile_high_pt2_2023.csv and ggi_2025.csv. build.py reads them through BRACKET_OVR / apply_bracket_ovr(), which runs right after load_tabroom. The first line, `relabel,<round>`, renames the API's single elim round, which the API had mislabeled "Final". Screenshots: *.png. A backup of the pre-change build.py is at elo/build.py.bak.

## Mile High pt 2 2023 (tourn 25894), 11-team octos bracket, seeds 1-5 on byes
- Octos: MS over AS, Zhu over TY, SP over GR. These were already in the API, inferred.
- QF: MS over Mercer PS, RS over SK, BC over Zhu, SP over UTTyl PS. All INFERRED from site elim W-L.
- SF: RS over MS, BC over SP. Final: RS over BC. All INFERRED.
- The site has no elim row for Zhu, so Zhu shows 0-0 on the site versus 1-1 parsed. That is the only validation mismatch.

## GGI 2025 (tourn 34235), Open
- QF: TZ over DK 3-0 and CG over SMC LP 2-1, both CONFIRMED. SL over LJ is a WALKOVER. BC had a bye (top seed).
- SF: all 4 semifinalists are Berkeley teams, so both semis were walkovers. CG and BC advanced over TZ and SL, but which opponent each one met is unknown, so both semis are marked UNKNOWN.
- Final: CG vs BC, a Berkeley WALKOVER. CG is listed as advancing because the site has CG at 2-0 and BC at 0-0.
- None of the semis or the final is rated in ELO.
- Remaining mismatches come from the site's inconsistent walkover credit: SL is 1-1 on the site, TZ is 1-1 on the site versus 1-0 parsed, and BC is 0-0 on the site.

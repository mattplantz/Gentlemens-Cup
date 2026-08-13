# Tournament History

Each past year's final results live here as a single file: `<year>_results.json`
(e.g. `2025_results.json`). These are plain files checked into the repo -
separate from `tournament_data.db`, which is just the live working data for
whichever tournament is currently in progress. That split is on purpose:
`tournament_data.db` can be wiped by a redeploy/reboot, but files in this repo
never are.

The app's **Tournament History** page automatically picks up any file named
`<year>_results.json` in this folder - just add the file and commit it, no
code changes needed.

## Format

```json
{
  "year": 2025,
  "format_notes": {
    "day1": "Short description of that year's Day 1 rules",
    "day2": "Short description of that year's Day 2 rules",
    "course_par_used_for_to_par_stats": { "1": 4, "2": 4, "...": "..." }
  },
  "results": {
    "day1_team_totals": { "Team Name": { "scramble": 0, "alt_shot": 0, "holes_completed": 0, "scramble_to_par": 0, "alt_shot_to_par": 0 } },
    "day1_scramble_points": { "Team Name": 0 },
    "day1_alt_shot_points": { "Team Name": 0 },
    "day2_skins_points": { "Team Name": 0 },
    "golfer_skins": [
      { "golfer": "Name", "team": "Team Name", "skins": 0 }
    ],
    "overall_points": { "Team Name": 0 },
    "champion": "Team Name"
  },
  "raw_data": {
    "day1_scores": [ { "Team": "...", "Hole": 1, "Scramble_Score": 0, "Alt_Shot_Score": 0, "Timestamp": "..." } ],
    "day2_scores": [ { "Group": 1, "Hole": 1, "Team": "...", "Score": 0, "Timestamp": "..." } ],
    "day2_skins": [ { "Group": 1, "Hole": 1, "Winner": "...", "Winning_Score": 0, "Tied": 0 } ]
  }
}
```

Only `results.champion` and `results.overall_points` are required for a year
to show up on the Champions summary table. `raw_data` is optional - it's kept
around so the underlying hole-by-hole scores aren't lost even if the app's
scoring logic changes in some future year.

`results.golfer_skins` is optional per-golfer Day 2 skins (Day 1 is a team
scramble/alt-shot and has no individual scores). When present, the History
detail view shows an "Individual Skins" table. At season end, ask Claude to
generate it from the `golfer` column now stamped on each `day2_scores` row.

## Adding this year's results at the end of the season

Ask Claude to pull the current season's data out of `tournament_data.db` (or
the CSV/DB backups downloaded from the app's sidebar) and write a new
`<year>_results.json` file in this format.

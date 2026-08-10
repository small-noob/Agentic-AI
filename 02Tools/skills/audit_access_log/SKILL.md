---
name: audit_access_log
description: Audit door-access logs against a clearance policy. Use when asked to find policy violations, identify a suspect badge, or produce an access-audit report code.
---

## When to use this skill

Any request to review badge/door access records for policy violations, rank
badges by violations, or compute an audit report code.

## Inputs to gather first

Read all three before counting anything — the log alone cannot tell you whether
a record is a violation:

| File | What it gives you |
| --- | --- |
| `policy.json` | allowed hours, per-door minimum clearance, the violation rules, the report-code formula |
| `employees.json` | badge_id → clearance level and status |
| `logs/*.csv` | the raw records: `timestamp,badge_id,door,result` |

## Procedure

1. `list_files` on `.` and on `logs` to learn the exact filenames. Do not guess them.
2. `read_file` `policy.json`. Note the allowed-hours boundary convention, each
   door's `min_clearance`, and the report-code formula.
3. `read_file` `employees.json`. Build the badge → (clearance, status) mapping.
4. `read_file` the log CSV. If the output is truncated, call `read_file` again
   with a larger `max_bytes` rather than extrapolating from what you saw.
5. Walk the records once and mark each one as violating or not:
   - Skip any record whose `result` is not `granted`. A denied attempt is the
     system working, not a violation.
   - `revoked_badge` — the holder's `status` is not `active`.
   - `insufficient_clearance` — holder clearance is below the door's `min_clearance`.
   - `outside_allowed_hours` — the entry hour falls outside the allowed window.
   - A record with two or three reasons still counts as **one** violation.
6. Total the violating records, and tally them per badge. The `suspect` is the
   badge with the highest tally.
7. Compute the report code with the `calculate` tool using the formula in
   `policy.json`. The badge number is the digits of the badge_id without the
   leading `B`. Never do this arithmetic mentally.
8. `write_file` the report to `reports/audit.md`, naming the suspect.
9. `finish` with `{"suspect":"Bxxxx","violations":0,"code":"xxxxxx"}`.

## Common mistakes

- Counting `denied` rows as violations. They are the control working correctly.
- Counting *reasons* instead of *records*, which inflates the total.
- Treating the end of the allowed-hours window as inclusive. Check the `note`
  field in the policy before deciding the boundary.
- Reporting the code with fewer than six digits after the modulo drops a leading
  zero. Pad it back.

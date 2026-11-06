# Case sheets (for HR and developers)

Each row of a `.csv` file here is **one test**: a day of a staff member, with the checks, leave and requests
we describe, and the result the system must give. Open the files in Excel (UTF-8, comma separated).
To add a case, copy a row, give it a new `id`, change the cells. Nothing else is needed.

Files: `status_cases.csv` (marks O, X, 1/2 O, L, H, SH, OH, flags late_in / early_out), `ot_cases.csv` (overtime hours),
`ah_cases.csv` (one month with 4 working Saturdays: which Saturdays become AH).

## Columns of status_cases.csv and ot_cases.csv
| column | meaning |
|---|---|
| id | unique name of the case, e.g. `ST-02-03`. The first part is the rule id in `attendance_rules.md` |
| rule | the rule(s) in `attendance_rules.md` that this case checks |
| basis | `rules` = the expected result comes from a rule Thanh/HR confirmed. `code` = it is what the system does today and nobody confirmed it: **please confirm or correct these** |
| title | one sentence in plain words (shown in the result list) |
| profile | the staff member: `normal`, `child_care` (60-minute allowance), `no_need_check`, `early_45` (early check-in rule), `no_morning_ot` (rule forbids morning OT), `no_ot` (rule without OT allowance), `g8` (group G8) |
| day | `weekday` (Wed 11 Mar 2026), `sunday`, `public_holiday`, `company_day`, `saturday` (28 Feb, not one of the last 2), `last_saturday` (14 Mar, one of the last 2) |
| check_in, check_out | face-ID times in Vietnam time `HH:MM`; empty = no check |
| leave | `full done`, `am waiting_fman`, `pm waiting_fhr`: part (full / am = morning off / pm = afternoon off), then how far the request got (`waiting_fman` = submitted, `waiting_fhr` = manager approved, `done` = HR validated). Substitute leave for a holiday worked: `sub full done worked=sunday 08:00-17:00` |
| request | OT or working-time (WT) requests, several separated by `\|`. Form: `<type> <from>-<to> [state] [out_by_reg] [estimate] [no_plan]`. OT types: `am` `pm` `both`. WT types: `biz_trip` `meet_out` `work_out` `forget_in` `forget_out` `wfh` `early_in` `others`. States: `draft` `waiting_fman` `waiting_fhr` `done` `refuse` (default `done`). Example: `forget_in 08:00- done \| forget_out -17:00 done` |
| expect_status | marks joined by `+`, then flags after `;`: `1/2 O+1/2 X; late_in`. Flags not listed must be absent |
| expect_status_worked_day | for substitute leave: the marks of the holiday that was worked |
| expect_ot | hours: `wd_ot=2.5 wd_st=0.5` (weekday normal / special), `hd_ot hd_st` (holiday), `ph_ot ph_st` (public holiday). `none` = no OT. Empty = OT not checked |
| expect_error | the system must refuse and its message must contain this text |
| known_gap | the case is a rule the system does not follow yet. It is listed as GAP, not failed. When the system is fixed the case fails with "gap seems fixed": delete the text |

Holiday OT: the runner creates the OT Holidays Plan line that the system requires (add `no_plan` to the request to leave it out).
Times are rounded in 15-minute steps by the system, so cases around :14/:15/:29/:30 are the interesting ones.

## How to run
See `scripts/run_case_sheets.py` (one line per case: PASS / FAIL / ERROR / GAP, then a total). Run it on a test copy only.
The environment is the Odoo data of that copy: public holidays, the AH leave type of Jul. 2026 and the policy
(late 5 min, absence 30 min, early out 0) must exist there.

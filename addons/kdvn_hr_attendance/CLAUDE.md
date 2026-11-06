# kdvn_hr_attendance (Odoo 19)
Port of ~/odoo12/addons/kderp_hr_attendance (reference only, 12.0.1.0.11). Read that module's CLAUDE.md and attendance_rules.md (rule ids in test names). Plan and stages: docs/porting_from_odoo12.md (Step 4).
**Payroll depends on the results: computation code is copied and only the Odoo API is adapted. Do not "improve" it. Any change in behaviour is listed below as a deviation and needs Thanh's approval.**
Mechanical conversion helper used while porting: /tmp/port12.py is not kept; the conversions are `@api.multi` removed, `self._context/_cr/_uid` -> `self.env.*`, `super(Class, self)` -> `super()`, `groups_id` -> `all_group_ids` (Odoo 12 groups_id included implied groups), `_company_default_get()` -> `self.env.company`, `tree` -> `list`, `attrs` -> expressions.

## State (7 Nov 2026: A1-A3 ported; time off (stage B) in progress; see docs/porting_from_odoo12.md Step 4)
Company policy (`res.company` fields, `at_policy()`), groups (core groups only get implied ids), `hr.attendance.rule`, public holidays (own models, OCA hr_holidays_public does not exist for 19), `hr.mixin` helpers (AT month/year, day start, early offset, Saturdays, time converters, request cutoff), `hr.attendance` rule methods (`_at_rules`, memo, `_is_holiday`, `is_no_sat_working`). `hr.attendance.at_date` is a plain field for now (stage A2 makes it the real one).
Not yet ported from hr.mixin: workflow buttons / state machine, refuse, GM approval, `groups()` roles, `get_full_url` (still the Odoo 12 `/web?#` form, must become `/odoo/...`), emails (stage C); `do_not_have_data_yet`, `may_be_forget`, `update_view_users_by_model` need raw status and `view_user_ids` (stage A2).
Optional libs not in the Odoo 19 image: `lunarcalendar` (lazy import in `to_lunar`), `pyodbc` (stage E).

## Deviations from Odoo 12 (each one only where Odoo 12 crashed, returned a wrong "None", or Odoo 19 changed the API)
- D1 `hr.holidays.public.is_public_holiday` returns 0 (not None) when the year has no holiday lines. Odoo 12: None, so `== 0` checks treated every day as a holiday. Production always has the year entered.
- D2 `is_no_sat_working` returns False when no calendar rule exists (Odoo 12: ValueError from min of nothing).
- D3 `hr.mixin._get_early_offset` looks for `early_in` requests only when `hr.attendance.request` exists (stage C).
- D4 `hr.attendance.rule._search_is_active` understands the operator forms Odoo 19 produces (`in`, `not in`, `!=`).
- Groups: Odoo 12 also renamed core groups ("Manual" -> removed in 19, "HR Admin" label) and made `director` imply the manual group; not copied. Record rules on `hr.attendance` come with stage A2 (they use `view_user_ids`).

## Tests
`docker exec odoo19 odoo -c <conf with the worktree addons path> -d kdvn_test -u kdvn_hr_attendance --test-tags /kdvn_hr_attendance --stop-after-init --http-port=8079 --gevent-port=8082` (32 tests, stage A1).

- D5 `_at_rules_compute` starts from the company policy: Odoo 12 took day_start / working_start / late_in... only from the first applicable rule, so a database without any rule raised KeyError (production always has company rules; with a rule present the numbers are the same).
- Odoo 19 core attendance overtime engine (`hr.attendance.overtime.line`) is switched off for our records; `check_in` is not required (absent days have none).
- Test prerequisite: the company resource calendar must be in timezone Asia/Ho_Chi_Minh (tests/common_at.py sets it); `get_at_time` reads calendar hours in the calendar's timezone.
- Views: Odoo 12 views were converted by `tools/port_view.py` (+ `tools/primary_attendance_views.py`: the four hr.attendance views are standalone now). Dropped because they need a rewrite: kanban views (`kanban-box`/`t-raw`), Odoo 12 JS widgets and assets (timepicker, boolean_toggle variants, bus listener, systray...). Menus: `views/hr_attendance_menu_structure.xml` + `views/hr_attendance_menus.xml`; core Odoo 19 entries we do not use are limited to administrators.
- All scheduled actions ship INACTIVE.

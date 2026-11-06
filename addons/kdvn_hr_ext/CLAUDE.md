# kdvn_hr_ext (Odoo 19)
Port of ~/odoo12/addons/kderp_hr_ext (reference only). Depends on kdvn_hr. Same model names (`hr.employee.department.history`, `hr.manager.history`, `hr.employee.project.history`) and field names.
- Department `manager_id` is computed (stored, read-only) from `hr.manager.history` (newest line effective today or earlier). kdvn_hr's "new manager" is turned into a history line by `_change_to_effective_manager`.
- Employee `department_id`/`parent_id`/`admin_dept_id`/`admin_manager_id` are set from `hr.employee.department.history` by `compute_current_dept` (any history create/write/unlink calls `_refresh_organisation`). Employees without history lines are NOT touched (Odoo 12 blanked them).
- Chains of manager users and GM: `_compute_parent_users` (one read of the whole tree, loop-safe). The GM group `kderp_hr_attendance.group_hr_attendance_gm` and the hook `hr.attendance._compute_view_users` belong to the attendance port: both are optional here (no group = nobody is GM; no hook = nothing to refresh). Connect when kdvn_hr_attendance exists.
- Constraint: working staff must not have a stop date, leavers must have one; exempt = no code or code `S9...`. Imports must set `working` and `stop_working_date` together.
- Cron `cron_sync_current_dept` ships INACTIVE (noupdate): applies lines that became effective today.
- Not ported: queue_job batching (compute is synchronous), the d3 org-chart screen (JS of the Odoo 12 client) and its menu, kanban tweak, overrides of core actions (default "working" filter, subordinate hierarchy). `get_org_data` / `_org_repair_tree` (the data side) are ported and tested; a screen can be built later (Odoo 19 has hr_org_chart).
- Tests: `-u kdvn_hr_ext --test-tags /kdvn_hr_ext` on kdvn_test (19 tests).

# kdvn_hr (Odoo 19)
Port of ~/odoo12/addons/kderp_hr (reference only). Same model names (`kderp.employee.location.code`, `kderp.hr.employee.location`, `hr.department.type`) and fields (`code`, `working`, `current_location_id`, `working_area_id`, dept `code`, `manager_2nd_id`, `new_manager`, `new_man_effective_date`, `type_id`).
- Not ported on purpose: `kderp.base.model` / `kderp.code.suggest` (Odoo 12 web client, ir.sequence code suggestion), `migrate_oe7_staff_image`, translated employee name (name is related to resource in Odoo 19), `res.users` name with code.
- Display name of an employee is `CODE - Name`; search uses name, code, work email (`_rec_names_search`).
- Unique SQL constraints on employee code and department code (many existing Odoo 19 rows have no code; the form requires one).
- Department "new manager": `_change_to_effective_manager` also clears the pending change (Odoo 12 left it); `_cron_change_to_effective_manager` exists but no cron is shipped yet.
- Groups use `res.groups.privilege` (Odoo 19). Menus are under Employees > Configuration > Employee, `noupdate`.
- Tests: `-u kdvn_hr --test-tags /kdvn_hr` on kdvn_test (8 tests).

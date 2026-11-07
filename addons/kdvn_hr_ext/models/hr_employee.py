import datetime
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

GM_GROUP = 'kdvn_hr_attendance.group_hr_attendance_gm'   # defined by kdvn_hr_attendance; absent = nobody is a GM yet


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    working = fields.Boolean(tracking=True)
    stop_working_date = fields.Date()
    official_working_date = fields.Date()
    admin_dept_id = fields.Many2one('hr.department', string='Administrative section', readonly=True)
    admin_manager_id = fields.Many2one('hr.employee', string='Admin. Manager', readonly=True)
    parent_user_ids = fields.Many2many('res.users', relation='hr_employee_res_users_functional_rel', compute='_compute_parent_users', store=True, readonly=True)
    admin_manager_user_ids = fields.Many2many('res.users', relation='hr_employee_res_users_admin_rel', compute='_compute_parent_users', store=True, readonly=True)
    gm_id = fields.Many2one('hr.employee', compute='_compute_parent_users', store=True, readonly=True)
    admin_gm_id = fields.Many2one('hr.employee', compute='_compute_parent_users', store=True, readonly=True)
    parent_users_dsp = fields.Char('Parent users', compute='_compute_parent_users', store=True, readonly=True)
    admin_manager_users_dsp = fields.Char('Administrative users', compute='_compute_parent_users', store=True, readonly=True)
    department_history_ids = fields.One2many('hr.employee.department.history', 'employee_id')
    project_history_ids = fields.One2many('hr.employee.project.history', 'employee_id')

    # ------------------------------------------------------------------ constraints / onchange
    @api.constrains('admin_manager_id')
    def _check_admin_manager(self):
        for employee in self:
            if employee.admin_manager_id and employee.admin_manager_id == employee:
                raise ValidationError(self.env._('An employee cannot be his/her manager %s', employee.admin_manager_id.name))

    @api.constrains('working', 'stop_working_date')
    def _check_working_dates(self):
        """A leaver needs a stop date, a working person must not have one. Staff without a code and S9xxx staff are exempt."""
        if self.env.context.get('kdvn_skip_working_check'):
            return   # legacy import: Odoo 12 data already has leavers without a stop date; copy it as it is
        for employee in self:
            if not employee.code or employee.code[:2] == 'S9':
                continue
            if not employee.working and not employee.stop_working_date:
                raise ValidationError(self.env._('Please input Stop Working Date!'))
            if employee.working and employee.stop_working_date:
                raise ValidationError(self.env._('Do not input Stop Working Date!'))

    @api.onchange('code')
    def _onchange_staff_code(self):
        for employee in self:
            if employee.code and employee.code[:2] != 'S9':
                employee.working = True

    @api.onchange('working')
    def _onchange_working(self):
        for employee in self:
            if isinstance(employee.id, int):
                employee.stop_working_date = False if employee.working else datetime.date.today()

    # ------------------------------------------------------------------ current department from history
    def compute_current_dept(self, force_update=False):
        """Current functional / administrative section and their managers, from the history lines that are effective.
        An employee never becomes his/her own manager: a section manager reports to the parent section's manager.
        Employees without any history line are left alone."""
        today = fields.Date.context_today(self)
        for employee in self:
            if not employee.department_history_ids:
                continue
            lines = employee.department_history_ids
            func = lines.filtered(lambda r: r.effective_date and r.effective_date <= today).sorted('effective_date', reverse=True)[:1].department_id
            admin = lines.filtered(lambda r: r.admin_effv_date and r.admin_effv_date <= today).sorted('admin_effv_date', reverse=True)[:1].admin_dept_id
            parent = admin_manager = self.browse()
            if func:
                parent = func.parent_id.manager_id if employee == func.manager_id else func.manager_id
            if admin:
                admin_manager = admin.parent_id.manager_id if employee == admin.manager_id else admin.manager_id
            if employee.department_id != func or force_update:
                employee.department_id = func
                employee.parent_id = parent
            if employee.admin_dept_id != admin or force_update:
                employee.admin_dept_id = admin
                employee.admin_manager_id = admin_manager

    def compute_dept_by_date(self, ref_date):
        """Administrative section around ref_date (the first one if ref_date is before all history); empty if no history."""
        self.ensure_one()
        History = self.env['hr.employee.department.history']
        line = History.search([('employee_id', '=', self.id), ('admin_effv_date', '<=', ref_date)], order='admin_effv_date desc', limit=1)
        line = line or History.search([('employee_id', '=', self.id)], order='admin_effv_date asc', limit=1)
        return line.admin_dept_id

    def sync_dept_data(self):
        """One-off: give every employee that has a department but no history one history line (from the staff's start)."""
        default_date = datetime.date(2020, 12, 21)
        for employee in self:
            if not employee.department_history_ids and employee.department_id:
                start = employee.create_date.date() if employee.create_date else default_date
                self.env['hr.employee.department.history'].create({
                    'employee_id': employee.id,
                    'department_id': employee.department_id.id,
                    'effective_date': start,
                    'admin_dept_id': employee.department_id.id,
                    'admin_effv_date': start,
                })

    def _refresh_organisation(self, from_date=None):
        """After a history change: sections, managers, manager chains, and (when attendance is installed) who may see attendance."""
        if self.env.context.get('kdvn_defer_org_refresh'):
            return   # bulk load (legacy import): the caller refreshes once at the end
        employees = self.exists()
        employees.compute_current_dept(force_update=True)
        employees._compute_parent_users()
        employees._refresh_attendance_view_users(from_date)

    def _refresh_attendance_view_users(self, from_date=None):
        """Hook of the attendance module (hr.attendance._compute_view_users); nothing to do until it is ported."""
        Attendance = self.env.get('hr.attendance')
        if Attendance is not None and hasattr(Attendance, '_compute_view_users'):
            for employee in self:
                kwargs = {'employee_id': employee}
                if from_date:
                    kwargs['from_date'] = from_date
                Attendance._compute_view_users(**kwargs)

    @api.model
    def _cron_sync_organisation(self):
        """Daily: employees whose history has a line effective today (or that still have no manager) are refreshed."""
        today = fields.Date.context_today(self)
        self.env['hr.department']._cron_refresh_manager()
        todo = self.browse()
        for employee in self.search([('active', '=', True), ('job_title', '!=', 'General Director'), ('department_history_ids', '!=', False)]):
            lines = employee.department_history_ids
            if today in lines.mapped('effective_date') or today in lines.mapped('admin_effv_date') or not (employee.parent_id or employee.admin_manager_id):
                todo |= employee
        for employee in todo:
            try:
                with self.env.cr.savepoint():
                    employee._refresh_organisation()
            except Exception:
                _logger.exception('Cannot refresh the organisation of %s', employee.display_name)

    # ------------------------------------------------------------------ chains of manager users
    @api.depends('user_id')
    def _compute_parent_users(self):
        """Users of the managers above an employee (functional and administrative chains, nearest first), and the GM.
        GM = first manager in the chain who has the GM group, or whose own manager has it.
        The whole company tree is read once, so a batch of employees costs one query."""
        todo = self.filtered(lambda e: isinstance(e.id, int))
        for employee in self - todo:
            employee.update(self._empty_chain_values())
        if not todo:
            return
        tree = {}
        for row in self.env['hr.employee'].with_context(active_test=False).sudo().search_read([], ['parent_id', 'admin_manager_id', 'user_id']):
            tree[row['id']] = {
                'parent': row['parent_id'][0] if row['parent_id'] else None,
                'admin': row['admin_manager_id'][0] if row['admin_manager_id'] else None,
                'user': row['user_id'][0] if row['user_id'] else None,
            }
        user_ids = {t['user'] for t in tree.values() if t['user']}
        users = self.env['res.users'].sudo().browse(user_ids).exists()
        gm_users = set()
        if self.env.ref(GM_GROUP, raise_if_not_found=False):
            gm_users = {u.id for u in users if u._has_group(GM_GROUP)}
        names = {u.id: u.name for u in users}
        for employee in todo:
            employee.update(self._chain_values(tree, employee.id, gm_users, names))

    @staticmethod
    def _walk(tree, start_id, key, gm_users):
        """Walk up from start_id by key ('parent' or 'admin'); returns (user ids, gm employee id). Loops end the walk."""
        users, gm_id, seen = [], False, set()
        current = tree.get(start_id, {}).get(key)
        while current and current not in seen:
            seen.add(current)
            node = tree.get(current, {})
            user = node.get('user')
            if user:
                users.append(user)
                if not gm_id:
                    if user in gm_users:
                        gm_id = current
                    else:
                        above = node.get(key)
                        if above and above not in seen and tree.get(above, {}).get('user') in gm_users:
                            gm_id = above
            current = node.get(key)
        return users, gm_id

    def _chain_values(self, tree, employee_id, gm_users, names):
        parent_users, gm_id = self._walk(tree, employee_id, 'parent', gm_users)
        admin_users, admin_gm_id = self._walk(tree, employee_id, 'admin', gm_users)
        return {
            'parent_user_ids': [(6, 0, parent_users)],
            'parent_users_dsp': ' >> '.join(names[u] for u in parent_users if u in names),
            'gm_id': gm_id,
            'admin_manager_user_ids': [(6, 0, admin_users)],
            'admin_manager_users_dsp': ' >> '.join(names[u] for u in admin_users if u in names),
            'admin_gm_id': admin_gm_id,
        }

    @staticmethod
    def _empty_chain_values():
        return {'parent_user_ids': [(5, 0, 0)], 'parent_users_dsp': '', 'gm_id': False,
                'admin_manager_user_ids': [(5, 0, 0)], 'admin_manager_users_dsp': '', 'admin_gm_id': False}

    # ------------------------------------------------------------------ organisation chart data
    @api.model
    def get_org_data(self, branch='functional'):
        """Rows of the company organisation chart. branch: 'functional' (parent_id / department_id) or 'admin'.
        A chart needs exactly one root and no loop, but HR data is not always clean, so the tree is repaired
        (_org_repair_tree) and every repaired person gets an 'issue' text for HR to fix at the source."""
        admin = branch == 'admin'
        mgr_field = 'admin_manager_id' if admin else 'parent_id'
        dept_field = 'admin_dept_id' if admin else 'department_id'
        employees = self.search(['&', ('code', 'not in', ['S0000', 'S4000']), '|', '&', (dept_field, '!=', False), ('working', '=', True),
                                 '&', ('working', '=', False), ('stop_working_date', '=', False)])
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        action = self.env.ref('hr.open_view_employee_list_my', raise_if_not_found=False)
        top_dept = self.env['ir.config_parameter'].sudo().get_param('kderp_hr.org_top_section', 'B.O.D')
        rows, parent_of, top_members = [], {}, []
        for employee in employees:
            if not employee.code:
                continue
            parent_of[employee.code] = employee[mgr_field].code or ''
            if employee[dept_field].name == top_dept:
                top_members.append(employee.code)
            rows.append({
                'name': employee.name,
                'image': '/web/image/hr.employee/%s/avatar_128?unique=%s' % (employee.id, ''.join(c for c in str(employee.write_date) if c.isdigit())),
                'office': employee[dept_field].name,
                'positionName': employee.job_title,
                'id': employee.code,
                'parentId': '',
                'full_url': '%s/odoo/%s/%s' % (base_url, 'action-%s' % action.id if action else 'hr', employee.id),
                'deptName': employee[dept_field].name,
                'issue': '',
            })
        fixed, issues = self._org_repair_tree(parent_of, top_members)
        for row in rows:
            row['parentId'] = fixed[row['id']]
            row['issue'] = issues.get(row['id'], '')
        return rows

    @api.model
    def _org_repair_tree(self, parent_of, top_members):
        """parent_of: {code: parent code or ''}; top_members: codes of the top section (B.O.D).
        Returns ({code: parent code or '' for the single root}, {code: issue text}).
        A manager outside the chart, the person themselves or a loop is dropped; the root is the manager the top
        section reports to (else a top-section member, else the biggest tree); every other root hangs under it."""
        codes = set(parent_of)
        if not codes:
            return {}, {}
        parent, issues = {}, {}
        for code, manager in parent_of.items():
            if manager and manager == code:
                issues[code] = 'Is his/her own manager'
                manager = ''
            elif manager and manager not in codes:
                issues[code] = 'Manager %s is not in the chart (resigned or has no section)' % manager
                manager = ''
            parent[code] = manager
        for start in sorted(codes):
            seen, current = [], start
            while current and current not in seen:
                seen.append(current)
                current = parent[current]
            if current:
                issues[seen[-1]] = 'Manager loop (%s)' % ' > '.join(seen[seen.index(current):] + [current])
                parent[seen[-1]] = ''
        roots = sorted(c for c in codes if not parent[c])
        size = {c: 0 for c in codes}
        for code in codes:
            current = parent[code]
            while current:
                size[current] += 1
                current = parent[current]
        candidates = [parent[m] for m in top_members if parent.get(m)] or [m for m in top_members if m in roots]
        if candidates:
            root = max(set(candidates), key=lambda c: (candidates.count(c), size[c], c))
        else:
            root = max(roots, key=lambda c: (size[c], c))
        while parent[root]:
            root = parent[root]
        for code in roots:
            if code != root:
                parent[code] = root
                issues.setdefault(code, 'No manager: shown under %s' % root)
        return parent, issues

import logging
import datetime
# from attr import fields_dict
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.http import request
from odoo.tools.float_utils import float_round
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class Employee(models.Model):
    _inherit = 'hr.employee'

    # Main office = the area of the administrative section (HR used to type it). Stored so lists/filters/exports keep working.
    work_location = fields.Char(compute='_compute_work_location', store=True, readonly=True)

    @api.depends('admin_dept_id.area_id.name')
    def _compute_work_location(self):
        for e in self:
            e.work_location = e.admin_dept_id.area_id.name or False

    # Odoo 12 hr_holidays defined leaves_count; Odoo 19 dropped it. Defined here again; its compute still reads the Odoo 12 leave report (stage B must rewrite it).
    leaves_count = fields.Float('Number of Time Off', compute='_compute_leaves_count')
    leaves_count_explain = fields.Char(compute='_compute_leaves_count_explain')
    # ah_leaves_count = fields.Float('Number of AH', compute='_compute_leaves_count')
    # admin_dept_id = fields.Many2one('hr.department', string='Administrative section', default=lambda self: self.department_id)

    # === Leaves balances ===
    leaves_bal = fields.Float(default=0, string="Leaves Balance", help="Current year leaves balance")
    leaves_carry_forward_bal = fields.Float(default=0, string="Last Year Leaves", help="Last year leaves carrying forward to this year")
    ot_compensation_leave_bal = fields.Float(default=0, string="OT Compensation Leaves")
    special_leaves_0 = fields.Float(default=0, string="Special Leave Y.1")
    special_leaves_1 = fields.Float(default=0, string="Special Leave Y.2")
    special_leaves_2 = fields.Float(default=0, string="Special Leave Y.3")
    need_action = fields.Boolean('Need HR Action', compute='_compute_need_hr_action', search='_search_need_hr_action', readonly=True)
    need_action_explain = fields.Text('Need Action Explain', compute='_compute_need_hr_action', readonly=True)

    # Modify fields
    attendance_state = fields.Selection(default=False)
    joining_date = fields.Date(string="Start Working Date")

    ot_apply = fields.Boolean(compute='compute_ot_apply', store=True, readonly=True)

    # Remote staff code for sync back attendance data for salary purpose
    remote_code = fields.Char(help='Staff code at remote working site')

    # override
    def _compute_leaves_count(self):
        # override to opt AH leaves out of the calculation
        # override to add AH leaves count to ah_leaves_count => move to hr_attendace.py model
        # import odoo_repl; odoo_repl.set_trace()
        all_leaves = self.env['hr.leave.report'].read_group([
            ('employee_id', 'in', self.ids),
            ('holiday_status_id.allocation_type', '!=', 'no'),
            ('holiday_status_id.active', '=', 'True'),
            ('holiday_status_id.is_ah', '=', False),
            ('holiday_status_id.is_special', '=', False),
            ('state', '=', 'validate')
        ], fields=['number_of_days', 'employee_id'], groupby=['employee_id'])
        mapping = dict([(leave['employee_id'][0], leave['number_of_days']) for leave in all_leaves])

        for employee in self:
            employee.leaves_count = float_round(mapping.get(employee.id, 0), precision_digits=2)

    @api.depends('leaves_count')
    def _compute_leaves_count_explain(self):
        for e in self:
            pass

    def create_users(self):
        """
            - Helper method to create/update user and his/her rights to attendance app
        """
        employee = self.filtered(lambda e: e.working or (('Top Manager' in e.category_ids.name) if e.category_ids.name else False))
        sample_user = self.env['res.users'].sudo().search([('login', '=', 'a-kdvn-user')])
        if not sample_user:
            raise UserError(_('There is NO template user {}, please create one! Contact IT for further instruction.'.format('a-kdvn-user')))
        if not employee:
            raise UserError(_('There are NO Employee either working or Top Management (Managers that NO need to check in/out)'))
        for e in employee:
            u = e.user_id.sudo()
            email = e.work_email
            if not email:
                raise UserError(_('No email for this employee, please update in the employee section!'))
            if not u:
                u = self.env['res.users'].sudo().create({
                    'name': e.name,
                    'login': e.work_email.split('@')[0],
                    'location_user_id': sample_user.location_user_id.id,
                    'tz': sample_user.tz,
                    'odoobot_state': sample_user.odoobot_state,
                    'action_id': sample_user.action_id.id if sample_user.action_id else False,
                    'notification_type': 'inbox'
                })
            # else:
            #     # disable user of not working employee (not include: Top manager - S9; user admin; ...)
            #     if not e.working and u and u.active and e.code[:2] != 'S9' and u.login not in ['admin']:
            #         u.active = False
            #         _logger.warning(_('===== Archive not working user {}'.format(u.login)))
            #         return

            required_keys = ['name', 'login', 'location_user_id', 'tz', 'odoobot_state', 'action_id']
            for key in required_keys:
                if not u[key] and sample_user[key]:
                    u[key] = sample_user[key]

            # link user to its employee and partner
            partner = u.partner_id.sudo()
            # NOTE: email is changed by change in parent_id => need to update parent_id info first
            partner.parent_id = 1
            partner.write({
                'company_type': 'person',
                'email': email
            })
            e.user_id = u.id

            # create user rights/groups
            manual_at = self.sudo().env.ref('hr_attendance.group_hr_attendance')
            kdvn_staff = self.env.ref('kdvn_hr_attendance.group_hr_attendance_menu_staff')
            at_officer = self.sudo().env.ref('hr_attendance.group_hr_attendance_user')
            at_manager = self.sudo().env.ref('hr_attendance.group_hr_attendance_manager')
            at_section_manager = self.sudo().env.ref('kdvn_hr_attendance.group_hr_attendance_section_manager')
            admin_director = self.sudo().env.ref('kdvn_hr_attendance.group_hr_attendance_director')
            gm = self.env.ref('kdvn_hr_attendance.group_hr_attendance_gm')

            # reset just created user groups similar to sample_user
            groups_id = sample_user.all_group_ids.mapped('id')
            if e.working:
                groups_id.append(kdvn_staff.id)

            man_of_dept = self.env['hr.department'].search([('manager_id', '=', e.id)])
            if man_of_dept:
                groups_id.append(at_section_manager.id)
                for dept in man_of_dept:
                    if dept.name == 'HR Section':
                        groups_id.append(at_manager.id)

            u.write({'groups_id': [(6, 0, groups_id)]})

    def disable_user(self):
        self.ensure_one()
        user = self.env['res.users'].search([('login', '=', self.work_email.split('@')[0] if self.work_email else False)])
        if not self.working and user and user.active and self.code[:2] != 'S9' and user.login not in ['admin']:
            user.sudo().toggle_active()
            if not user.active:
                _logger.warning(_('===== Archived [not working user {} {}]'.format(user.login, user._name)))
            else:
                _logger.warning(_('===== Archiving [not working user {} {}] NOT successfully!'.format(user.login, user._name)))

    def update_other_related_info(self):
        """
            - Update related information for a working employee
            - If working == True
            - Create user
            - Basic leave allocations (AH, Annual Leave)
        """
        for e in self:
            if e.working:
                # Create linked user
                e.create_users()
                # Basic leave allocations
            else:
                # Disable linked user
                e.disable_user()
    
    def action_send_invite_email(self):
        """
            - Send invite email to user linked to that of employees
        """
        for e in self:
            if e.user_id:
                e.user_id.sudo().with_context(create_user=1).action_reset_password()
            else:
                raise UserError(_('There is NO user linked to the employee: {}'.format(e.name)))
    
    def _compute_last_attendance_id(self):
        for e in self:
            today = fields.Date.context_today(self)
            e.last_attendance_id = self.env['hr.attendance'].search([('employee_id', '=', e.id), ('at_date', '=', today)], limit=1)

    def _compute_attendance_state(self):
        for e in self:
            att = e.last_attendance_id.sudo()
            att_state = False
            if att:
                if att.compute_in and not att.compute_out:
                    att_state = 'checked_in'
                elif att.compute_in and att.compute_out:
                    att_state = 'checked_out'
            e.attendance_state = att_state

    def _compute_start_working_date(self):
        """
            - Helper method returning computing start_working_date of an employee
            - Used for: determine to create at record
            - Used for: ...
        """
        self.ensure_one()
        result = False
        if self.joining_date:
            result = self.joining_date
        elif self.department_history_ids:
            result = self.department_history_ids[0].admin_effv_date or self.department_history_ids[0].effective_date
        else:
            result = self.create_date.date()
        return result

    def _compute_need_hr_action(self):
        for e in self:
            need_action = False
            need_action_explain_list = []
            is_staff = e.code and e.code[:2] != 'S9'
            if is_staff:
                # Check joining_date or Start Working Date
                if not e.joining_date:
                    need_action = True
                    need_action_explain_list.append('Do NOT have Start Working Date')

                # Check Official Working Date
                apply_date = datetime.date(2022, 8, 21)
                if not e.official_working_date:
                    if e.joining_date and e.joining_date >= apply_date:
                        need_action = True
                        need_action_explain_list.append('Do NOT have Officical Working Date')

                # Check leave allocation
                leave_allocations = self.env['hr.leave.allocation'].sudo().search([('employee_id', '=', e.id)]).filtered(lambda a: a.holiday_status_id.valid)
                if not leave_allocations:
                    need_action = True
                    need_action_explain_list.append('Do NOT have any leave allocation')
                else:
                    if not leave_allocations.filtered(lambda a: not a.holiday_status_id.is_ah):
                        need_action = True
                        need_action_explain_list.append('Do NOT have other leave allocation (except AH)')
                    # Check current AH allocation
                    # Check resource calendar
                    if not leave_allocations.filtered(lambda a: a.holiday_status_id.is_ah) and not({'House Maid', 'Driver', 'Outsource'} & set(e.category_ids.mapped('name'))):
                        at_rules = self.env['hr.attendance']._at_rules(employee_id=e.id, at_date=fields.Date.context_today(e))
                        rc_id = at_rules.get('resource_calendar_id', [None, None])[0]
                        rc = self.env['resource.calendar'].browse(rc_id) if rc_id else self.env['resource.calendar']
                        if rc:
                            if rc.attendance_ids.filtered(lambda a: a.dayofweek == '5'):
                                need_action = True
                                need_action_explain_list.append('Do NOT have AH leave allocation')
                        else:
                            need_action = True
                            need_action_explain_list.append('Do NOT have Working Hours Calendar')


            e.update({'need_action': need_action, 'need_action_explain': '; '.join(need_action_explain_list)})
    
    def _search_need_hr_action(self, operator, value):
        if value in [True, False]:
            if operator == '!=':
                value = not value
            ids = self.search([]).filtered(lambda e: e.need_action == value).mapped('id')
            return [('id', 'in', ids)]
        return []

    def employee_annual_leave(self, year=None):
        self.ensure_one()
        return self.env['hr.leave.allocation'].employee_annual_leave(employee_id=self.id, year=year)

    def all_childs(self):
        """
            Recursive function returing all childs of an employee
        """
        self.ensure_one()
        res = self.env['hr.employee']
        if not self.child_ids:
            return res
        else:
            res |= self.child_ids
            for e in self.child_ids:
                res |= e.all_childs()
            return res

    @api.model
    def check_user_function(self):
        uid = request.session.uid
        user = self.env['res.users'].sudo().search([('id', '=', uid)], limit=1)
        if user and user.has_group('kdvn_hr_attendance.group_hr_attendance_gm'):
            return 'GM'
        if user and user.has_group('kdvn_hr_attendance.group_hr_attendance_section_manager'):
            return 'SM'
        return 'STAFF'
    
    def get_ot_holidays_data(self):
        """
            Get data for generate OT Holidays register form:
            - A3 landscape form
            - Holidays list
        """
        pass

    @api.depends('category_ids')
    def compute_ot_apply(self):
        for e in self:
            # Currently any employee having tag will be NOT apply OT: G8, Driver, House Maid, Outsourcing
            ot_apply = not bool(e.category_ids.mapped('name'))
            e.ot_apply = ot_apply
            # Update section/area ot staff number
            e.admin_dept_id._compute_ot_staff()


    # ===== CONSTRAINTS =====
    # @api.constrains('working')
    # @api.multi
    # def _validate_working(self):
    #     for e in self:
    #         if not e.working:
    #             managed_dept_ids = self.env['hr.department'].search(['|', ('parent_id', '=', e.id), ('admin_manager_id', '=', e.id)])
    #             if len(managed_dept_ids) > 0:
    #                 raise ValidationError(_('Employee still managed sections! REF.: {} managing').format(e.code, managed_dept_ids.mapped('name')))

    # ===== CRUD =====
    @api.model_create_multi
    def create(self, vals_list):
        """Odoo 19 passes a list of dicts; the Odoo 12 body below handles one dict at a time."""
        records = self.browse()
        for vals in vals_list:
            records |= self._legacy_create(vals)
        return records

    def _legacy_create(self, values):
        # update ot staff count
        employee_ids = super().create(values)
        for d in employee_ids.mapped('admin_dept_id'):
            d._compute_ot_staff()
        
        return employee_ids

    def write(self, values):
        result = super().write(values)
        if 'working' in values and values['working'] == False:
            managed_dept_ids = self.env['hr.department'].search([('manager_id', '=', self.id)])
            if len(managed_dept_ids) > 0 and self.code[:2] != 'S9':  # Only apply for Vietnamese managers (who still need to check in/out)
                raise ValidationError(_('Please update data, employee {} still managing {} sections!').format(self.code, managed_dept_ids.mapped('name')))
            self.disable_user()
        if 'admin_dept_id' in values and self.admin_dept_id:
            self.admin_dept_id._compute_ot_staff()
        return result
    
    def unlink(self):
        section_ids = self.mapped('admin_dept_id')
        _super = super().unlink()
        for d in self.env['hr.department'].browse(section_ids):
            d._compute_ot_staff()
        return _super


class Deparment(models.Model):
    _inherit = 'hr.department'

    section_ot_staff = fields.Integer(help="The section staff number having ot apply", compute='_compute_ot_staff', store=True)
    area_ot_staff = fields.Integer(help="The area staff number having ot apply", compute='_compute_ot_staff', store=True)
    
    # Override the method originally from hr_holidays module
    def _compute_leave_count(self):
        Requests = self.env['hr.leave.cover']
        Allocations = self.env['hr.leave.allocation']
        today_date = datetime.datetime.utcnow().date()
        today_start = fields.Datetime.to_string(today_date)  # get the midnight of the current utc day
        today_end = fields.Datetime.to_string(today_date + relativedelta(hours=23, minutes=59, seconds=59))

        leave_data = Requests.read_group(
            [('department_id', 'in', self.ids),
             ('state', 'in', ['waiting_fman', 'waiting_fhr'])],
            ['department_id'], ['department_id'])
        allocation_data = Allocations.read_group(
            [('department_id', 'in', self.ids),
             ('state', '=', 'confirm')],
            ['department_id'], ['department_id'])
        absence_data = Requests.read_group(
            [('department_id', 'in', self.ids), ('state', 'not in', ['draft', 'refuse']),
             ('date_from', '<=', today_end), ('date_to', '>=', today_start)],
            ['department_id'], ['department_id'])

        res_leave = dict((data['department_id'][0], data['department_id_count']) for data in leave_data)
        res_allocation = dict((data['department_id'][0], data['department_id_count']) for data in allocation_data)
        res_absence = dict((data['department_id'][0], data['department_id_count']) for data in absence_data)

        for department in self:
            department.leave_to_approve_count = res_leave.get(department.id, 0)
            department.allocation_to_approve_count = res_allocation.get(department.id, 0)
            department.absence_of_today = res_absence.get(department.id, 0)
    
    def _compute_ot_staff(self):
        # return False
        for d in self:
            d.section_ot_staff = len(d.admin_member_ids.filtered('ot_apply'))
            d.area_ot_staff = len(d.area_id.child_ids.mapped('child_ids.admin_member_ids').filtered('ot_apply'))
            # print('=====', d.area_id.child_ids.mapped('child_ids.member_ids'))

from odoo import api, fields, models, tools, exceptions, _


class KderpLeaveReport(models.Model):
    _inherit = ['hr.leave.report']

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'hr_leave_report')
        # leave_types = tuple(self.env['hr.leave.type'].search([('category', 'in', ('annual_leave', 'summer_vacation'))]).mapped('id'))
        leave_types = tuple(self.env['hr.leave.type'].search([]).mapped('id'))

        self.env.cr.execute("""
            CREATE or REPLACE view hr_leave_report as (
                SELECT row_number() over(ORDER BY leaves.employee_id) as id,
                leaves.employee_id as employee_id, leaves.name as name,
                leaves.number_of_days as number_of_days, leaves.type as type,
                leaves.category_id as category_id, leaves.department_id as department_id,
                leaves.holiday_status_id as holiday_status_id, leaves.state as state,
                leaves.holiday_type as holiday_type, leaves.date_from as date_from,
                leaves.date_to as date_to, leaves.payslip_status as payslip_status
                from (select
                    allocation.employee_id as employee_id,
                    allocation.name as name,
                    allocation.number_of_days as number_of_days,
                    allocation.category_id as category_id,
                    allocation.department_id as department_id,
                    allocation.holiday_status_id as holiday_status_id,
                    allocation.state as state,
                    allocation.holiday_type,
                    null as date_from,
                    null as date_to,
                    FALSE as payslip_status,
                    'allocation' as type
                from hr_leave_allocation as allocation
                union all select
                    request.employee_id as employee_id,
                    request.name as name,
                    (request.number_of_days * -1) as number_of_days,
                    request.category_id as category_id,
                    request.department_id as department_id,
                    request.holiday_status_id as holiday_status_id,
                    request.state as state,
                    request.holiday_type,
                    request.date_from as date_from,
                    request.date_to as date_to,
                    request.payslip_status as payslip_status,
                    'request' as type
                from hr_leave as request) leaves
                where leaves.holiday_status_id in {}
            );
        """.format(leave_types))


class KderpLeaveAllocationReport(models.Model):
    _name = 'hr.leave.allocation.report'
    _description = 'Leave Allocation Summary'
    _auto = False
    _order= 'employee_id'

    employee_id = fields.Many2one('hr.employee', readonly=True)
    name = fields.Char('Description', readonly=True)
    holiday_status_id = fields.Many2one('hr.leave.type', string='Leave Type', readonly=True)
    number_of_days = fields.Float(readonly=True)
    validity_start = fields.Date(readonly=True)
    validity_stop = fields.Date(readonly=True)
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'hr_leave_allocation_report')
        self.env.cr.execute("""
            CREATE OR REPLACE view hr_leave_allocation_report as (
                SELECT la.id, e.id employee_id, la.name, lt.id holiday_status_id, number_of_days, lt.validity_start, lt.validity_stop
                FROM hr_leave_allocation la
                JOIN hr_leave_type lt ON lt.id = la.holiday_status_id
                JOIN hr_employee e ON e.id = la.employee_id
                WHERE la.holiday_type = 'employee'
                --ORDER BY e.id
            )
        """)


class KderpLeaveAllocationUpdateTracking(models.Model):
    _name = 'hr.leave.allocation.ot.days.tracking'
    _description = 'Leave Allocation Tracking (OT days)'
    _auto = False
    _order = 'employee_id, write_date desc'

    employee_id = fields.Many2one('hr.employee', readonly=True)
    field = fields.Char(readonly=True)
    field_desc = fields.Char(readonly=True)
    allocation_id = fields.Many2one('hr.leave.allocation', readonly=True)
    leave_type_id = fields.Many2one('hr.leave.type', readonly=True)
    old_value_float = fields.Float(readonly=True)
    new_value_float = fields.Float(readonly=True)
    write_uid = fields.Many2one('res.users', readonly=True)
    write_date = fields.Datetime(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'hr_leave_allocation_ot_days_tracking')
        self.env.cr.execute("""
            CREATE OR REPLACE view hr_leave_allocation_ot_days_tracking as (
                SELECT mtv.id, field, field_desc, mm.res_id allocation_id, la.employee_id employee_id, lt.id leave_type_id, old_value_float, new_value_float, mtv.write_uid, mtv.write_date
                FROM mail_tracking_value mtv
                    JOIN mail_message mm ON mtv.mail_message_id = mm.id
                        JOIN mail_message_subtype st ON mm.subtype_id = st.id
                    JOIN hr_leave_allocation la ON mm.res_id = la.id
                        JOIN hr_leave_type lt ON la.holiday_status_id = lt.id
                WHERE res_model = 'hr.leave.allocation' AND st.name = 'Allocation number of days change' AND field = 'number_of_days' AND lt.name = 'Annual Leave' AND la.name = 'OT Compensation'
                ORDER BY lt.name, la.name
            )
        """)
from odoo import api, fields, models, tools, exceptions, _


# Odoo 12 replaced the SQL of core hr.leave.report (all leave types, payslip status). Odoo 19's core report is kept as it is
# (it has leave_id, number_of_hours, leave_type...): the Odoo 12 override is NOT ported.


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
                SELECT mtv.id, f.name AS field, f.field_description->>'en_US' AS field_desc, mm.res_id allocation_id, la.employee_id employee_id, lt.id leave_type_id,
                       old_value_float, new_value_float, mtv.write_uid, mtv.write_date
                FROM mail_tracking_value mtv
                    JOIN ir_model_fields f ON f.id = mtv.field_id
                    JOIN mail_message mm ON mtv.mail_message_id = mm.id
                        JOIN mail_message_subtype st ON mm.subtype_id = st.id
                    JOIN hr_leave_allocation la ON mm.res_id = la.id
                        JOIN hr_leave_type lt ON la.holiday_status_id = lt.id
                WHERE mm.model = 'hr.leave.allocation' AND st.name->>'en_US' = 'Allocation number of days change' AND f.name = 'number_of_days'
                    AND lt.name->>'en_US' = 'Annual Leave' AND la.name = 'OT Compensation'
            )
        """)
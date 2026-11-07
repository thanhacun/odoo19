from odoo import fields, models


class HrEmployeePublic(models.Model):
    """Attendance data of the staff that every user may read (Odoo 12 behaviour). The leave balances stay HR only (groups on hr.employee)."""
    _inherit = 'hr.employee.public'

    joining_date = fields.Date(readonly=True)
    ot_apply = fields.Boolean(readonly=True)
    remote_code = fields.Char(readonly=True)
    work_location = fields.Char(readonly=True)

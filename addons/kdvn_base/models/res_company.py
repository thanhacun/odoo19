from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    report_date_format = fields.Char('Format Date (Report)', default='dd-MMM-yyyy', help='Default format date in report (babel pattern)')

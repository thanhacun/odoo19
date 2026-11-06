from odoo import fields, models


class KdvnLegacyImportWizard(models.TransientModel):
    _name = 'kdvn.legacy.import.wizard'
    _description = 'Import from the Odoo 12 snapshot'

    employee_codes = fields.Char(help='Staff codes separated by space or comma. Empty = everybody. Managers of these staff are added automatically.')
    working_only = fields.Boolean(default=True, help='Skip staff who have left.')
    password = fields.Char(help='Set this password on every imported user (dev databases only). Empty = no password.')
    date_from = fields.Date(help='Attendance and requests from this day (empty = all history).')
    date_to = fields.Date()
    dry_run = fields.Boolean(default=True, help='Do everything, then roll back, and show what would happen.')
    result = fields.Text(readonly=True)

    def action_run(self):
        self.ensure_one()
        codes = [c for c in (self.employee_codes or '').replace(',', ' ').split() if c]
        outcome = self.env['kdvn.legacy.import'].run(employee_codes=codes, working_only=self.working_only,
                                                     password=self.password or None, dry_run=self.dry_run,
                                                     date_from=self.date_from and str(self.date_from), date_to=self.date_to and str(self.date_to))
        self.result = outcome['log']
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

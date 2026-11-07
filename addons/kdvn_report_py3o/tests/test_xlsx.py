from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestXlsx(TransactionCase):

    def test_xlsx_is_offered_and_not_native(self):
        report = self.env['ir.actions.report'].create({
            'name': 'zz xlsx', 'model': 'res.partner', 'report_name': 'kdvn_report_py3o.zz_xlsx',
            'report_type': 'py3o', 'py3o_filetype': 'xlsx'})
        self.assertIn('xlsx', dict(self.env['ir.actions.report']._get_py3o_filetypes()))
        self.assertFalse(report.is_py3o_native_format)

    def test_known_formats_still_work(self):
        report = self.env['ir.actions.report'].create({
            'name': 'zz ods', 'model': 'res.partner', 'report_name': 'kdvn_report_py3o.zz_ods',
            'report_type': 'py3o', 'py3o_filetype': 'ods'})
        self.assertTrue(report.is_py3o_native_format)

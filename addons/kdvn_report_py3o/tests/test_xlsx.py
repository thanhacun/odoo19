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

    def test_ids_come_from_the_context_when_the_url_has_none(self):
        """A report with `data` is requested as ?options=..&context=.. (no ids in the URL): the controller passes None."""
        partner = self.env['res.partner'].create({'name': 'Ctx partner'})
        report = self.env['ir.actions.report'].create({
            'name': 'zz ctx', 'model': 'res.partner', 'report_name': 'kdvn_report_py3o.zz_ctx', 'report_type': 'py3o',
            'py3o_filetype': 'odt', 'print_report_name': "'P-%s' % object.name"})
        data = {'context': {'active_ids': [partner.id]}, 'formatted_data': [{}]}
        self.assertEqual(report.gen_report_download_filename(None, data), 'P-Ctx partner')
        self.assertEqual(self.env['ir.actions.report']._py3o_ids_from_context(None, data), [partner.id])
        self.assertEqual(self.env['ir.actions.report']._py3o_ids_from_context([5], data), [5])

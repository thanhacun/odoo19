from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestSafetyTool(TransactionCase):

    def setUp(self):
        super(TestSafetyTool, self).setUp()
        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.grp_admin = self.env.ref('kdvn_procurement_procedures.group_safety_tool_admin')
        self.grp_mgr = self.env.ref('kdvn_procurement_procedures.group_safety_tool_manager')
        base_group = self.env.ref('base.group_user')

        def make_user(login, groups):
            return Users.create({'name': 'T ' + login, 'login': 'st_test_' + login, 'email': login + '@example.invalid',
                                 'group_ids': [(6, 0, [base_group.id] + [g.id for g in groups])]})
        self.u_sm = make_user('sm', [])
        self.u_safety = make_user('safety', [self.grp_mgr])
        self.u_admin = make_user('admin', [self.grp_admin])
        self.u_app = make_user('app', [])
        Emp = self.env['hr.employee']
        self.e_sm = Emp.create({'name': 'T SM', 'code': 'TST-SM', 'working': True, 'user_id': self.u_sm.id})
        self.e_app = Emp.create({'name': 'T Applicant', 'code': 'TST-APP', 'working': True, 'user_id': self.u_app.id, 'parent_id': self.e_sm.id})
        self.job = self.env['kderp.job.lookup'].create({
            'job_no': 'HG00-26-9001', 'job_name': 'Test job', 'external_id': 990001, 'is_general_expense': True})
        Item = self.env['safety.tool.item']
        self.shoe = Item.create({'name': 'T Shoe', 'item_type': 'shoe', 'size_ids': [
            (0, 0, {'name': '26.0'}), (0, 0, {'name': '27.0'})]})
        self.helmet = Item.create({'name': 'T Helmet', 'item_type': 'helmet', 'reorder_level': 2})
        self.size26 = self.shoe.size_ids.filtered(lambda s: s.name == '26.0')

    def _move_in(self, item, qty, size=None):
        return self.env['safety.tool.move'].create({
            'item_id': item.id, 'size_id': size and size.id, 'qty_in': qty, 'source': 'opening'})

    def _stock(self, item):
        item.invalidate_recordset()
        return item.stock_qty

    def _request(self, lines, **vals):
        data = {'reason': 'test', 'job_id': self.job.id, 'employee_id': self.e_app.id,
                'line_ids': [(0, 0, l) for l in lines]}
        data.update(vals)
        return self.env['safety.tool.request'].with_user(self.u_app).create(data)   # the applicant is the creator

    # ---- ledger ----
    def test_01_stock_and_constraints(self):
        self._move_in(self.helmet, 5)
        self._move_in(self.shoe, 3, self.size26)
        stock = self.env['safety.tool.move'].stock_map()
        self.assertEqual(stock[(self.helmet.id, False)], 5)
        self.assertEqual(stock[(self.shoe.id, self.size26.id)], 3)
        self.assertEqual(self._stock(self.helmet), 5)
        self.assertEqual(self.shoe.stock_qty, 3)
        with self.assertRaises(ValidationError):   # size missing for an item with sizes
            self._move_in(self.shoe, 1)
        with self.assertRaises(ValidationError):   # IN and OUT together
            self.env['safety.tool.move'].create({'item_id': self.helmet.id, 'qty_in': 1, 'qty_out': 1})
        self.assertIn(self.helmet.id, self.env['safety.tool.item'].search([('low_stock', '=', False)]).ids)
        self.env['safety.tool.move'].create({'item_id': self.helmet.id, 'qty_out': 4})
        self.helmet.invalidate_recordset()
        self.assertTrue(self.helmet.low_stock)

    def test_02_line_rules(self):
        with self.assertRaises(ValidationError):   # shoe without size
            self._request([{'item_id': self.shoe.id, 'qty': 1}])
        with self.assertRaises(ValidationError):   # qty 0
            self._request([{'item_id': self.helmet.id, 'qty': 0}])

    # ---- special rules (shipped off) ----
    def test_03_special_rules(self):
        req = self._request([{'item_id': self.shoe.id, 'size_id': self.size26.id, 'qty': 3}])
        self.assertEqual(req._get_special_case_reasons(), [])          # all off = no limit
        rule = self.env['kderp.e.approval.special.rule'].get_rule('safety.tool.request', 'shoe_limit')
        self.assertTrue(rule)
        self.assertEqual(rule.action, 'off')
        rule.write({'action': 'special', 'value': 2})
        self.assertEqual(len(req._get_special_case_reasons()), 1)
        rule.write({'value': 3})
        self.assertEqual(req._get_special_case_reasons(), [])
        rep = self._request([{'item_id': self.helmet.id, 'qty': 1}], request_type='replace')
        photo = self.env['kderp.e.approval.special.rule'].get_rule('safety.tool.request', 'replace_no_photo')
        photo.write({'action': 'block'})
        self.assertEqual(rep._get_special_case_reasons()[0][0], 'block')

    # ---- full flow ----
    def test_04_flow_in_stock(self):
        self._move_in(self.helmet, 5)
        req = self._request([{'item_id': self.helmet.id, 'qty': 2}])
        self.assertTrue(req.name.startswith('SFT-'))
        req.with_user(self.u_app).action_submit()
        self.assertEqual(req.state, 'submitted')
        self.assertEqual(req.review_ids.sorted('sequence').mapped('definition_id.frontend_name'),
                         ['SM Approval', 'Safety Manager'])   # no GM found: step skipped
        req.with_user(self.u_sm).validate_tier()
        req.with_user(self.u_safety).validate_tier()
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.fulfilment_state, 'to_issue')
        with self.assertRaises(UserError):                      # applicant cannot hand over
            req.with_user(self.u_app).action_issue()
        req.with_user(self.u_admin).action_issue()
        self.assertEqual(req.fulfilment_state, 'issued')
        self.assertEqual(self._stock(self.helmet), 3)
        with self.assertRaises(UserError):                      # reset blocked after handover
            req.sudo().action_reset_to_draft()
        req.with_user(self.u_app).action_not_received()
        self.assertEqual(req.fulfilment_state, 'not_received')
        req.with_user(self.u_app).action_confirm_received()
        self.assertEqual(req.fulfilment_state, 'received')
        self.assertEqual(self._stock(self.helmet), 3)              # receipt never changes stock
        req.with_user(self.u_admin).action_reverse_issue()
        self.assertEqual(self._stock(self.helmet), 5)
        self.assertEqual(req.fulfilment_state, 'to_issue')

    def test_05_short_of_stock(self):
        self._move_in(self.helmet, 1)
        req = self._request([{'item_id': self.helmet.id, 'qty': 4}])
        self.assertTrue(req.stock_warning)
        req.with_user(self.u_app).action_submit()
        req.with_user(self.u_sm).validate_tier()
        req.with_user(self.u_safety).validate_tier()
        self.assertEqual(req.fulfilment_state, 'to_purchase')
        with self.assertRaises(UserError):                      # short and no reason
            req.with_user(self.u_admin).action_issue()
        req.with_user(self.u_admin).action_mark_ordered()
        self.assertEqual(req.fulfilment_state, 'ordered')
        self._move_in(self.helmet, 5)
        req.with_user(self.u_admin).action_check_stock()
        self.assertEqual(req.fulfilment_state, 'to_issue')
        req.with_user(self.u_admin).action_issue()
        self.assertEqual(self._stock(self.helmet), 2)

    def test_06_replace_needs_trouble_report(self):
        req = self._request([{'item_id': self.helmet.id, 'qty': 1}], request_type='replace')
        with self.assertRaises(UserError):
            req.with_user(self.u_app).action_submit()
        req.write({'trouble_date': '2026-08-28', 'trouble_place': 'Site', 'damaged_item_id': self.helmet.id})
        req.with_user(self.u_app).action_submit()
        self.assertEqual(req.state, 'submitted')

    def test_07_lines_locked_after_submit(self):
        req = self._request([{'item_id': self.helmet.id, 'qty': 1}])
        req.with_user(self.u_app).action_submit()
        with self.assertRaises(UserError):
            req.line_ids.write({'qty': 9})

    # ---- Excel import (small generated sheet) ----
    @staticmethod
    def _xlsx(rows):
        """rows: {row number: {column: value}} -> bytes of a minimal xlsx (numbers as numbers, text inline)."""
        import io
        import zipfile
        from xml.sax.saxutils import escape
        body = []
        for r in sorted(rows):
            cells = []
            for col, val in sorted(rows[r].items()):
                if isinstance(val, (int, float)):
                    cells.append('<c r="%s%d"><v>%s</v></c>' % (col, r, val))
                else:
                    cells.append('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (col, r, escape(val)))
            body.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
        sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData>%s</sheetData></worksheet>' % ''.join(body))
        wb = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
              '<sheet name="Safety tool control sheet" sheetId="1" r:id="rId1"/></sheets></workbook>')
        rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('xl/workbook.xml', wb)
            z.writestr('xl/_rels/workbook.xml.rels', rels)
            z.writestr('xl/worksheets/sheet1.xml', sheet)
        return out.getvalue()

    def _control_sheet(self):
        d = 46000          # serial dates (2025-12-..)
        return self._xlsx({
            2: {'O': d + 200}, 3: {'O': 'No.7'},
            4: {'B': 'No.', 'C': 'Item', 'E': 'Date', 'F': 'Project Name', 'G': 'PIC', 'I': "Q'ty", 'L': 'Remraks'},
            5: {'I': 'IN', 'J': 'OUT', 'K': 'Remain'},
            7: {'B': 1, 'C': 'Imp Vest', 'E': d, 'K': 10, 'L': 'Periodical check'},
            8: {'C': 'Size L', 'E': d + 10, 'F': 'Proj X', 'G': 'TST-APP', 'J': 2, 'K': 8},
            9: {'E': d + 20, 'F': 'Supplier', 'I': 5, 'K': 13, 'L': 'Invoice 1'},
            11: {'B': 2, 'C': 'Imp Vest', 'E': d, 'K': 4, 'L': 'Periodical check'},
            12: {'C': 'Size M', 'E': d + 11, 'F': 'Proj X', 'G': 'S0000', 'J': 1, 'K': 3},
            14: {'B': 3, 'C': 'Imp Empty', 'E': d, 'K': 0, 'L': 'Periodical check'},
        })

    def test_08_excel_import(self):
        import base64
        Wizard = self.env['safety.tool.import.wizard'].with_user(self.u_admin)
        data = base64.b64encode(self._control_sheet())
        w = Wizard.create({'file': data, 'filename': 't.xlsx'})
        w.action_read()
        self.assertEqual(len(w.line_ids), 3)
        self.assertEqual(w.line_ids.filtered(lambda l: l.excel_name == 'Imp Empty').action, 'skip')
        self.assertEqual(w.report_no, 'No.7')
        w.action_import()
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Vest')])
        self.assertEqual(len(item), 1)
        self.assertEqual(sorted(item.size_ids.mapped('name')), ['L', 'M'])
        size_l = item.size_ids.filtered(lambda s: s.name == 'L')
        size_m = item.size_ids.filtered(lambda s: s.name == 'M')
        stock = self.env['safety.tool.move'].stock_map([item.id])
        self.assertEqual(stock[(item.id, size_l.id)], 13)     # 10 opening - 2 out + 5 in
        self.assertEqual(stock[(item.id, size_m.id)], 3)      # 4 opening - 1 out (staff unknown: move without request)
        req = self.env['safety.tool.request'].search([('is_imported', '=', True), ('employee_id', '=', self.e_app.id)])
        self.assertEqual(len(req), 1)
        self.assertEqual(req.state, 'approved')
        self.assertTrue(req.name.startswith('SFT-IMP-'))
        self.assertEqual(req.create_uid.id, 1)                # not the importer's own request (My Requests / dashboard)
        self.assertEqual(req.import_project_text, 'Proj X')
        self.assertEqual(req.line_ids.qty, 2)
        # the applicant sees the imported history, nothing is asked of the reviewers
        self.assertTrue(self.env['safety.tool.request'].with_user(self.u_app).search([('id', '=', req.id)]))
        # same file again: nothing new, nothing doubled
        w2 = Wizard.create({'file': data, 'filename': 't.xlsx'})
        w2.action_read()
        self.assertEqual(sum(w2.line_ids.mapped('n_new')), 0)
        before = self.env['safety.tool.move'].search_count([])
        w2.action_import()
        self.assertEqual(self.env['safety.tool.move'].search_count([]), before)
        # a corrected Excel quantity becomes a stock-take adjustment
        sheet = self._xlsx({2: {'O': 46200}, 3: {'O': 'No.8'},
                            4: {'B': 'No.', 'C': 'Item', 'E': 'Date', 'F': 'Project Name', 'G': 'PIC', 'I': "Q'ty", 'L': 'Remraks'},
                            5: {'I': 'IN', 'J': 'OUT', 'K': 'Remain'},
                            7: {'B': 1, 'C': 'Imp Vest', 'E': 46000, 'K': 10, 'L': 'Periodical check'},
                            8: {'C': 'Size L', 'E': 46010, 'F': 'Proj X', 'G': 'TST-APP', 'J': 2, 'K': 8},
                            9: {'E': 46020, 'F': 'Supplier', 'I': 5, 'K': 13, 'L': 'Invoice 1'},
                            10: {'E': 46150, 'F': 'Proj Y', 'G': 'TST-APP', 'J': 3, 'K': 10}})
        w3 = Wizard.create({'file': base64.b64encode(sheet), 'filename': 't2.xlsx'})
        w3.action_read()
        self.assertEqual(sum(w3.line_ids.mapped('n_new')), 1)     # only the new OUT row
        w3.action_import()
        self.assertEqual(self.env['safety.tool.move'].stock_map([item.id])[(item.id, size_l.id)], 10)
        # undo the first import
        w.batch_id.action_undo()
        self.assertFalse(w.batch_id.move_ids)
        self.assertFalse(w.batch_id.request_ids)
        # only an admin may import
        with self.assertRaises(UserError):
            self.env['safety.tool.import.wizard'].with_user(self.u_app).create({'file': data}).action_read()

    # ---- printed form data and Excel report ----
    def test_09_print_data(self):
        self._move_in(self.helmet, 5)
        req = self._request([{'item_id': self.helmet.id, 'qty': 2}], request_type='replace', office_code='T',
                            trouble_date='2026-08-28', trouble_place='Site', damaged_item_id=self.helmet.id,
                            cost_amount=1000000)
        data = req.prepare_safety_tool_report()
        self.assertEqual(data['lines'], [{'no': '1', 'item': 'T Helmet', 'size': '-', 'qty': '2', 'uom': 'pcs'}])
        self.assertTrue(data['is_replace'])
        self.assertEqual(data['approval_title'], '5. Approval')
        self.assertEqual((data['cost'], data['vat'], data['total']), ('VND 1.000.000', 'VND 100.000', 'VND 1.100.000'))
        self.assertEqual(data['trouble_place'], 'Site')
        self.assertEqual(data['stamp'], u'\u2713 APPROVED')
        # an imported request must not claim an approval that never happened
        req.sudo().write({'is_imported': True})
        data = req.prepare_safety_tool_report()
        self.assertEqual(data['stamp'], 'IMPORTED HISTORY')
        self.assertIn('no approval steps', data['approval_note'])
        self.assertEqual(self._request([{'item_id': self.helmet.id, 'qty': 1}]).prepare_safety_tool_report()['approval_title'],
                         '4. Approval')

    def test_10_excel_report(self):
        import io
        from odoo.addons.kdvn_procurement_procedures.models import safety_tool_xlsx as xl
        self._move_in(self.helmet, 5)
        self.env['safety.tool.move'].create({'item_id': self.helmet.id, 'qty_out': 2, 'employee_id': self.e_app.id,
                                             'job_id': self.job.id, 'source': 'manual'})
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create({
            'date_from': '2000-01-01', 'date_to': '2100-01-01', 'item_ids': [(6, 0, [self.helmet.id])]})
        wiz.action_generate()
        self.assertTrue(wiz.file)
        import base64
        rows = xl.read_sheet_rows(io.BytesIO(base64.b64decode(wiz.file)), 'control')
        flat = [v for r in rows.values() for v in r.values()]
        self.assertIn('T Helmet', flat)
        remains = [r['K'] for r in rows.values() if 'K' in r and (r.get('I') or r.get('J'))]   # Remain is column K in the original layout
        self.assertIn('3', [str(x).rstrip('0').rstrip('.') for x in remains])      # 5 in - 2 out
        with self.assertRaises(UserError):
            self.env['safety.tool.report.wizard'].with_user(self.u_app).create({}).action_generate()

    def test_11_plain_user_can_open_the_form(self):
        """A normal applicant (and a reviewer) has no access to the ledger: the form must not need it."""
        Request = self.env['safety.tool.request']
        for user in (self.u_app, self.u_sm, self.u_safety):
            R = Request.with_user(user)
            view = R.get_view(view_type='form')                                       # Odoo 19: fields_view_get is gone
            view_fields = view['models'][Request._name]
            self.assertNotIn('name="move_ids"', view['arch'], 'the form of %s reads the ledger' % user.login)
            R.default_get(list(view_fields))
        req = self._request([{'item_id': self.helmet.id, 'qty': 1}])
        import re
        view = Request.with_user(self.u_app).get_view(view_type='form')
        shown = set(re.findall(r'name="(\w+)"', view['arch'])) & set(view['models'][Request._name])
        self.assertTrue(req.with_user(self.u_app).read(list(shown)))
        # the store keeper does see the tab
        self.assertIn('name="move_ids"', Request.with_user(self.u_admin).get_view(view_type='form')['arch'])

    def test_12_notifications(self):
        """Handover / approval / not received / reminder reach the right people by Talk and email."""
        from unittest import mock
        Model = type(self.env['safety.tool.request'])
        talks, emails = [], []
        with mock.patch.object(Model, '_notify_channels', lambda s, user, cfg, event, email=None: (True, True)), \
                mock.patch.object(Model, '_notify_send_talk', lambda s, user, message, cfg: talks.append((user.login, message))), \
                mock.patch.object(Model, '_notify_send_email', lambda s, to, subject, body, attachment_ids=None, auto_delete=False: emails.append((to, subject))):
            self._move_in(self.helmet, 1)
            req = self._request([{'item_id': self.helmet.id, 'qty': 3}])
            req.with_user(self.u_app).action_submit()
            req.with_user(self.u_sm).validate_tier()
            req.with_user(self.u_safety).validate_tier()
            # approved but short: the store staff are told (Talk and email), the applicant is not
            self.assertTrue(any(l == self.u_admin.login and 'short of stock' in m.lower() for l, m in talks))
            self.assertFalse(any(l == self.u_app.login and 'short of stock' in m.lower() for l, m in talks))
            self.assertTrue(any(subject.startswith('Approved: short of stock') for to, subject in emails))
            del talks[:], emails[:]
            self._move_in(self.helmet, 5)
            req.with_user(self.u_admin).action_check_stock()
            req.with_user(self.u_admin).action_issue()
            self.assertEqual([l for l, m in talks], [self.u_app.login])        # only the applicant
            self.assertIn('handed over', talks[0][1])
            self.assertIn(req.name, talks[0][1])
            self.assertIn('model=safety.tool.request', talks[0][1])
            self.assertEqual(len(emails), 1)
            del talks[:], emails[:]
            req.with_user(self.u_app).action_not_received()
            self.assertIn(self.u_admin.login, [l for l, m in talks])       # the store staff (dev may have more members)
            self.assertNotIn(self.u_app.login, [l for l, m in talks])
            self.assertIn('not received', talks[0][1].lower())
            del talks[:], emails[:]
            # reminder after 3 days, once
            req.with_user(self.u_admin).action_reverse_issue()
            req.with_user(self.u_admin).action_issue()
            del talks[:], emails[:]
            req.sudo().write({'issued_date': '2000-01-01'})
            self.env['safety.tool.request'].cron_remind_receipt()
            self.assertEqual([l for l, m in talks], [self.u_app.login])
            self.assertIn('confirm', talks[0][1].lower())
            del talks[:]
            self.env['safety.tool.request'].cron_remind_receipt()
            self.assertEqual(talks, [])

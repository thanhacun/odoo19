"""Safety tool: accounting report, material codes, receipt no. and receipt printout, remote lookup by payment no., import of the
accounting (ACC) sheets, control sheet layout and pictures (port of the Odoo 12 changes of 5-10 Nov 2026)."""
import base64
import datetime
import io
import os
import zipfile
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase

from odoo.addons.kdvn_procurement_procedures.models import safety_tool_xlsx as xl

EPOCH = datetime.date(1899, 12, 30)
PAYMENT_ID, EXPENSE_ID, INVOICE_ID = 11, 7, 21


def serial(d):
    return (d - EPOCH).days


def png(width=40, height=30):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (width, height), (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


class Common(TransactionCase):

    def setUp(self):
        super().setUp()
        Users = self.env['res.users'].with_context(no_reset_password=True)
        base_group = self.env.ref('base.group_user')

        def make_user(login, groups):
            return Users.create({'name': 'A ' + login, 'login': 'st_acc_' + login, 'email': login + '@example.invalid',
                                 'group_ids': [(6, 0, [base_group.id] + [g.id for g in groups])]})
        self.u_sm = make_user('sm', [])
        self.u_safety = make_user('safety', [self.env.ref('kdvn_procurement_procedures.group_safety_tool_manager')])
        self.u_admin = make_user('admin', [self.env.ref('kdvn_procurement_procedures.group_safety_tool_admin')])
        self.u_app = make_user('app', [])
        Emp = self.env['hr.employee']
        self.e_sm = Emp.create({'name': 'A SM', 'code': 'TST-ASM', 'working': True, 'user_id': self.u_sm.id})
        self.e_admin = Emp.create({'name': 'A Store keeper', 'code': 'TST-AAD', 'working': True, 'user_id': self.u_admin.id})
        self.e_app = Emp.create({'name': 'A Applicant', 'code': 'TST-APP', 'working': True, 'user_id': self.u_app.id,
                                 'parent_id': self.e_sm.id})
        # work_location is computed from the administrative department's area: set the stored value directly
        self.env.flush_all()
        self.env.cr.execute("UPDATE hr_employee SET work_location = 'Tlip' WHERE id = %s", [self.e_app.id])
        self.e_app.invalidate_recordset()
        self.job = self.env['kderp.job.lookup'].create({
            'job_no': 'HG00-26-9101', 'job_name': 'Acc job', 'external_id': 990101, 'is_general_expense': True})
        Item = self.env['safety.tool.item']
        self.vest = Item.create({'name': 'Acc Vest', 'item_type': 'other', 'code': 'ST9901'})
        self.boot = Item.create({'name': 'Acc Boot', 'item_type': 'shoe', 'code': 'ST9902', 'size_ids': [
            (0, 0, {'name': '26.0', 'code': 'ST9902'}), (0, 0, {'name': '27.0', 'code': 'ST9902-1'})]})
        self.Move = self.env['safety.tool.move']

    def _in(self, item, qty, date, size=None, source='purchase', **vals):
        data = {'item_id': item.id, 'size_id': size and size.id, 'qty_in': qty, 'date': date, 'source': source}
        data.update(vals)
        return self.Move.create(data)

    def _out(self, item, qty, date, emp=None, **vals):
        data = {'item_id': item.id, 'qty_out': qty, 'date': date, 'source': 'manual', 'employee_id': emp and emp.id}
        data.update(vals)
        return self.Move.create(data)

    def _second_issued_request(self, lines):
        """A second handed-over request in the same transaction. (The full flow cannot run twice in one test: the record rule of the
        reviewers reads user.review_ids, which stays cached.) Approved by the system, handed over by the store keeper."""
        req = self.env['safety.tool.request'].sudo().with_context(safety_tool_system=True).create({
            'reason': 'acc test 2', 'job_id': self.job.id, 'employee_id': self.e_app.id, 'state': 'approved',
            'fulfilment_state': 'to_issue', 'line_ids': [(0, 0, l) for l in lines]})
        req.with_user(self.u_admin).action_issue()
        return req

    def _issued_request(self, lines):
        """An approved request handed over by the store keeper (full flow)."""
        req = self.env['safety.tool.request'].with_user(self.u_app).create({
            'reason': 'acc test', 'job_id': self.job.id, 'employee_id': self.e_app.id,
            'line_ids': [(0, 0, l) for l in lines]})
        req.with_user(self.u_app).action_submit()
        req.with_user(self.u_sm).validate_tier()
        req.with_user(self.u_safety).validate_tier()
        self.assertEqual(req.state, 'approved')
        req.with_user(self.u_admin).action_issue()
        return req


class TestMaterialCodes(Common):

    def test_code_of_and_label(self):
        Size = self.env['safety.tool.size']
        s26 = self.boot.size_ids.filtered(lambda s: s.name == '27.0')
        self.assertEqual(Size.code_of(self.boot, s26), 'ST9902-1')                 # the size's own code
        self.assertEqual(Size.code_of(self.vest), 'ST9901')                         # no size: the item's code
        plain = self.env['safety.tool.size'].create({'item_id': self.boot.id, 'name': '28.0'})
        self.assertEqual(Size.code_of(self.boot, plain), 'ST9902')                  # a size without code: the item's code
        self.assertEqual(self.env['safety.tool.item']._fields['code'].string, 'Code Mat.')
        self.assertEqual(Size._fields['code'].string, 'Code Mat.')

    def test_migration_numbers_become_codes(self):
        """post-migration 19.0.0.2.0: item numbers (1, 34-1) become ST0001, ST0034-1; codes already in the new form stay."""
        import importlib.util
        import os
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.0.2.0', 'post-material_codes.py')
        spec = importlib.util.spec_from_file_location('post_material_codes', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        Item = self.env['safety.tool.item']
        a = Item.create({'name': 'Mig A', 'code': '7'})
        b = Item.create({'name': 'Mig B', 'code': '34-1'})
        c = Item.create({'name': 'Mig C', 'code': 'ST0044'})
        d = Item.create({'name': 'Mig D'})
        self.env.flush_all()
        module.migrate(self.env.cr, '19.0.0.1.4')
        module.migrate(self.env.cr, '19.0.0.1.4')                                   # safe to run twice
        (a | b | c | d).invalidate_recordset()
        self.assertEqual((a.code, b.code, c.code, d.code), ('ST0007', 'ST0034-1', 'ST0044', False))


class TestReceipt(Common):

    def test_receipt_number_and_work_area(self):
        self._in(self.vest, 20, '2026-01-01', source='opening')
        # numbers typed or imported from the paper forms: the next number continues after the highest of the year
        old = self.env['safety.tool.request'].sudo().with_context(safety_tool_system=True).create({
            'reason': 'old', 'employee_id': self.e_app.id, 'receipt_no': 'SM-26-0163', 'state': 'approved',
            'fulfilment_state': 'received', 'is_imported': True,
            'line_ids': [(0, 0, {'item_id': self.vest.id, 'qty': 1})]})
        self.assertTrue(old)
        Request = self.env['safety.tool.request']
        self.assertEqual(Request._next_receipt_no(datetime.date(2026, 5, 1)), 'SM-26-0164')
        self.assertEqual(Request._next_receipt_no(datetime.date(2031, 5, 1)), 'SM-31-0001')
        req = self._issued_request([{'item_id': self.vest.id, 'qty': 2}])
        self.assertRegex(req.receipt_no, r'^SM-\d{2}-\d{4}$')
        number = req.receipt_no
        move = req.sudo().move_ids
        self.assertEqual(move.work_area, 'Tlip')                                    # the working area of the staff at handover
        self.assertEqual(move.receipt_no, number)
        # reverse and hand over again: the number stays
        req.with_user(self.u_admin).action_reverse_issue()
        req.with_user(self.u_admin).action_issue()
        self.assertEqual(req.receipt_no, number)
        # the next handover gets the next number
        req2 = self._second_issued_request([{'item_id': self.vest.id, 'qty': 1}])
        self.assertEqual(int(req2.receipt_no[-4:]), int(number[-4:]) + 1)
        # the number is searchable and on the list / form / search views
        self.assertIn(req, Request.search([('receipt_no', '=', number)]))
        for view_type in ('list', 'form', 'search'):
            arch = Request.with_user(self.u_admin).get_view(view_type=view_type)['arch']
            self.assertIn('name="receipt_no"', arch, view_type)

    def test_receipt_data_and_print(self):
        self._in(self.vest, 20, '2026-01-01', source='opening')
        self._in(self.boot, 5, '2026-01-01', size=self.boot.size_ids[0], source='opening')
        req = self._issued_request([{'item_id': self.vest.id, 'qty': 2},
                                    {'item_id': self.boot.id, 'size_id': self.boot.size_ids[0].id, 'qty': 1}])
        data = req.with_user(self.u_admin).prepare_safety_tool_receipt()
        self.assertEqual(data['receipt_no'], req.receipt_no)
        self.assertEqual(data['reference_no'], req.name)
        self.assertEqual(data['staff_no'], 'TST-APP')
        self.assertEqual(data['applicant'], 'A Applicant')
        self.assertEqual(data['delivered_by'], self.u_admin.name)
        self.assertIn('WAITING', data['stamp'])
        rows = {r['no']: r for r in data['lines']}
        self.assertEqual(rows['9901']['request'], '2')                              # item number: ST9901 -> 9901
        self.assertEqual(rows['9901']['receive'], '2')
        self.assertEqual(rows['9902']['remark'], '26.0 x 1')                        # the size goes to the remark
        self.assertTrue(data['signature_strip_png'])                                # the two signature cards are drawn
        # confirmed by the applicant: the stamp changes
        req.with_user(self.u_app).action_confirm_received()
        data = req.with_user(self.u_admin).prepare_safety_tool_receipt()
        self.assertIn('RECEIVED', data['stamp'])
        self.assertNotIn('WAITING', data['stamp'])
        # the template renders (as odt: the PDF conversion needs LibreOffice in a prefork server)
        xmlid = 'kdvn_procurement_procedures.safety_tool_receipt_report_py3o'
        self.env.ref(xmlid).py3o_filetype = 'odt'
        out, ext = self.env['ir.actions.report']._render(xmlid, req.ids, data={'formatted_data': [data]})
        self.assertEqual((ext, out[:2]), ('odt', b'PK'))
        # the button shows only after the handover
        arch = self.env['safety.tool.request'].with_user(self.u_admin).get_view(view_type='form')['arch']
        self.assertIn('prepare_safety_tool_receipt', arch)

    def test_applicant_prints_own_receipt(self):
        """A plain user (hr.employee is private in Odoo 19) can print the receipt of his own request."""
        self._in(self.vest, 20, '2026-01-01', source='opening')
        req = self._issued_request([{'item_id': self.vest.id, 'qty': 2}])
        data = req.with_user(self.u_app).prepare_safety_tool_receipt()
        self.assertEqual(data['applicant'], 'A Applicant')
        self.assertEqual(data['staff_no'], 'TST-APP')


class FakeRemote:
    """Replaces kderp.remote.client.execute: a payment EN26-0001 (cost user TST-AAD, the store keeper), one VAT invoice, and a
    payment EN26-0002 whose cost user is somebody else. Records every call."""

    def __init__(self):
        self.calls = []

    def as_method(self):
        return lambda client, *args, **kwargs: self(client, *args, **kwargs)

    def __call__(self, client, model, method, args=None, kwargs=None, **kw):
        self.calls.append((model, method, args, kwargs))
        domain = (args or [[]])[0] if method == 'search_read' else None
        if model == 'kderp.supplier.payment.expense' and method == 'search_read':
            code = [t[2] for t in domain if t[0] == 'code'][0]
            rows = {
                'EN26-0001': {'id': PAYMENT_ID, 'code': 'EN26-0001', 'partner_id': [5, 'ACME Safety Co'], 'total': 1100000.0,
                              'tax_amount': 100000.0, 'expense_id': [EXPENSE_ID, 'EX26-0007 - gloves'], 'kderp_vat_invoice_ids': [INVOICE_ID]},
                'EN26-0002': {'id': 12, 'code': 'EN26-0002', 'partner_id': [6, 'Other'], 'total': 500.0, 'tax_amount': 0.0,
                              'expense_id': [8, 'EX26-0008 - other'], 'kderp_vat_invoice_ids': []},
            }
            return [rows[code]] if code in rows else []
        if model == 'kderp.supplier.payment.expense' and method == 'read':
            return [{'id': PAYMENT_ID, 'code': 'EN26-0001', 'expense_id': [EXPENSE_ID, 'EX26-0007 - gloves']},
                    {'id': 12, 'code': 'EN26-0002', 'expense_id': [8, 'EX26-0008 - other']}]
        if model == 'kderp.other.expense.line':
            return [{'expense_id': [EXPENSE_ID, 'EX26-0007'], 'employee_id': [3, 'TST-AAD - A Store keeper']},
                    {'expense_id': [8, 'EX26-0008'], 'employee_id': [4, 'T9999 - Somebody else']}]
        if model == 'kderp.supplier.vat.invoice' and method == 'search_read':
            names = [t[2] for t in domain if t[0] == 'name']
            return [{'id': INVOICE_ID, 'kderp_supplier_payment_expense_ids': [PAYMENT_ID, 12]}] if names == ['INV-77'] else []
        if model == 'kderp.supplier.vat.invoice' and method == 'read':
            return [{'id': INVOICE_ID, 'name': 'INV-77', 'date': '2026-10-01'}]
        raise AssertionError('unexpected remote call %s.%s' % (model, method))


class TestRemoteLookup(Common):

    def setUp(self):
        super().setUp()
        self.remote = FakeRemote()
        patcher = mock.patch.object(type(self.env['kderp.remote.client']), 'execute', self.remote.as_method())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.AdminMove = self.Move.with_user(self.u_admin)

    def test_payment_data(self):
        data = self.AdminMove._remote_payment_data('EN26-0001')
        self.assertEqual(data['supplier_name'], 'ACME Safety Co')
        self.assertEqual(data['remote_amount'], 1000000.0)                           # total without VAT
        self.assertEqual(data['expense_no'], 'EX26-0007')
        self.assertEqual((data['invoice_no'], data['invoice_date']), ('INV-77', '2026-10-01'))

    def test_only_payments_of_the_store(self):
        """Same message for an unknown payment and for one whose cost user is not a Safety Tool Admin."""
        messages = set()
        for number in ('EN26-0002', 'EN26-9999'):
            with self.assertRaises(UserError) as error:
                self.AdminMove._remote_payment_data(number)
            messages.add(str(error.exception).replace(number, 'EN'))
        self.assertEqual(len(messages), 1)                                          # nothing tells the two cases apart
        self.assertIn('Safety Tool Admin', messages.pop())
        # the E-Approval administrator and the superuser have no limit
        self.assertIsNone(self.Move._remote_allowed_codes())
        self.assertEqual(self.AdminMove._remote_allowed_codes(), {'TST-AAD'})

    def test_find_payment_through_invoice(self):
        """Payment no. from the VAT invoice (number + date); several payments on the invoice: only the allowed one counts."""
        self.assertEqual(self.AdminMove._remote_find_payment('INV-77, INV-78', datetime.date(2026, 10, 1)), 'EN26-0001')
        self.assertFalse(self.AdminMove._remote_find_payment('INV-00', datetime.date(2026, 10, 1)))

    def test_action_fetch_remote(self):
        move = self._in(self.vest, 10, '2026-10-05')
        move.write({'payment_no': 'EN26-0001'})
        move.with_user(self.u_admin).action_fetch_remote()
        self.assertEqual((move.supplier_name, move.invoice_no, move.invoice_date, move.expense_no),
                         ('ACME Safety Co', 'INV-77', datetime.date(2026, 10, 1), 'EX26-0007'))
        self.assertEqual(move.remote_amount, 1000000.0)
        self.assertEqual(move.unit_cost, 100000.0)                                   # amount / quantity
        self.assertTrue(move.remote_synced_on)
        # no payment no. but invoice no. + date: the payment is found through the invoice
        move2 = self._in(self.vest, 4, '2026-10-06', invoice_no='INV-77', invoice_date='2026-10-01')
        move2.with_user(self.u_admin).action_fetch_remote()
        self.assertEqual(move2.payment_no, 'EN26-0001')
        self.assertEqual(move2.unit_cost, 250000.0)
        # an existing unit cost is not overwritten
        move3 = self._in(self.vest, 4, '2026-10-06', payment_no='EN26-0001', unit_cost=5.0)
        move3.with_user(self.u_admin).action_fetch_remote()
        self.assertEqual(move3.unit_cost, 5.0)

    def test_typing_the_payment_no_fills_the_form_without_saving(self):
        count = self.Move.search_count([])
        with Form(self.Move.with_user(self.u_admin)) as form:
            form.item_id = self.vest
            form.qty_in = 10
            form.payment_no = 'EN26-0001'
            self.assertEqual(form.supplier_name, 'ACME Safety Co')
            self.assertEqual(form.invoice_no, 'INV-77')
            self.assertEqual(form.expense_no, 'EX26-0007')
            self.assertEqual(form.unit_cost, 100000.0)
            self.assertEqual(self.Move.search_count([]), count)                      # nothing saved before Save
        self.assertEqual(self.Move.search_count([]), count + 1)
        saved = self.Move.search([('payment_no', '=', 'EN26-0001')])
        self.assertEqual(saved.supplier_name, 'ACME Safety Co')
        # an unknown number gives a warning in the form, not an error
        with Form(self.Move.with_user(self.u_admin)) as form:
            form.item_id = self.vest
            form.qty_in = 1
            form.payment_no = 'EN26-9999'
            self.assertFalse(form.supplier_name)

    def test_refresh_button_only_for_saved_moves(self):
        arch = self.AdminMove.get_view(view_type='form')['arch']
        self.assertIn('action_fetch_remote', arch)
        self.assertIn('not id or', arch)


class TestAccountingReport(Common):

    def _data(self):
        """Opening 10, lot 1 (5 x 100000, INV-1), lot 2 (5 x 120000, INV-2); OUT 7 in April and 6 in July (FIFO over the lots)."""
        self.opening = self._in(self.vest, 10, '2026-01-01', source='opening')
        self.lot1 = self._in(self.vest, 5, '2026-03-01', payment_no='EN26-0100', invoice_no='INV-1', invoice_date='2026-02-20',
                             unit_cost=100000.0, supplier_name='ACME')
        self.lot2 = self._in(self.vest, 5, '2026-06-01', payment_no='EN26-0200', invoice_no='INV-2', invoice_date='2026-05-20',
                             unit_cost=120000.0, supplier_name='ACME')
        self.out1 = self._out(self.vest, 7, '2026-04-01', self.e_app, work_area='Tlip')
        self.out2 = self._out(self.vest, 6, '2026-07-01', self.e_app, work_area='Tlip')

    def _wizard(self, **vals):
        data = {'date_from': '2026-01-01', 'date_to': '2026-12-31', 'item_ids': [(6, 0, [self.vest.id])],
                'accounting': True, 'refresh_remote': False}
        data.update(vals)
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create(data)
        wiz.action_generate()
        return wiz, base64.b64decode(wiz.file)

    def test_fifo_lots(self):
        self._data()
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create({'date_to': '2026-12-31'})
        lots = {code: lot_list for code, name, lot_list in wiz._fifo_lots(datetime.date(2026, 12, 31))}
        lots = lots['ST9901']
        self.assertEqual([l['move'] for l in lots], [self.opening, self.lot1, self.lot2])      # oldest lot first
        used = [[(o, q) for o, q in l['outs']] for l in lots]
        self.assertEqual(used[0], [(self.out1, 7), (self.out2, 3)])                           # 7 + 3 out of the opening stock
        self.assertEqual(used[1], [(self.out2, 3)])                                           # the rest of OUT 2 from lot 1
        self.assertEqual(used[2], [])
        # a handover that was reversed is left out (net quantity)
        self.assertEqual(sum(q for l in lots for o, q in l['outs']), 13)

    def test_fifo_reversed_handover_and_orphans(self):
        self._in(self.vest, 5, '2026-01-01', source='opening')
        req = self._issued_request([{'item_id': self.vest.id, 'qty': 3}])
        req.with_user(self.u_admin).action_reverse_issue()                  # IN again (source reverse), the OUT is cancelled out
        orphan = self._out(self.vest, 9, '2026-09-01', self.e_app)           # more than ever bought: an orphan row
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create({'date_to': '2026-12-31'})
        lots = dict((c, l) for c, n, l in wiz._fifo_lots(datetime.date(2026, 12, 31)))['ST9901']
        self.assertEqual(sum(q for l in lots for o, q in l['outs'] if o.request_id), 0)       # reversed: not counted
        orphans = [l for l in lots if not l['move']]
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]['outs'], [(orphan, 4)])                                   # 9 - 5 in stock

    def test_accounting_sheets(self):
        self._data()
        wiz, data = self._wizard()
        self.assertEqual(wiz.filename, 'Safety_Tool_control_sheet_2026-12-31_ACC.xlsx')
        names = zipfile.ZipFile(io.BytesIO(data)).read('xl/workbook.xml').decode()
        for sheet in ('Safety tool control  sheet', 'Detail check - report to Acc. D', 'Code.Mat'):
            self.assertIn(sheet, names)
        self.assertIn('definedName name="Code.Mat"', names)                        # the VLOOKUP range of the original
        rows = xl.read_sheet_rows(io.BytesIO(data), 'detail', strict=True)
        # header rows of the supplier invoices (yellow) carry payment no., supplier, invoice no.
        heads = {r: c for r, c in rows.items() if (c.get('A') or '').startswith('EN')}
        self.assertEqual(sorted(c['A'] for c in heads.values()), ['EN26-0100', 'EN26-0200'])
        first = min(heads)
        self.assertEqual((heads[first]['C'], heads[first]['D']), ('ACME', 'INV-1'))
        self.assertEqual(float(heads[first]['L']), 500000.0)                       # total In = 5 x 100000
        # one lot row per code under its invoice, the OUT rows below it (staff code, date, quantity, working area)
        lot_row = rows[first + 1]
        self.assertEqual((lot_row['B'], float(lot_row['H']), float(lot_row['K'])), ('ST9901', 5.0, 100000.0))
        self.assertEqual(float(lot_row['J']), 3.0)                                 # of lot 1 only 3 pieces were taken (FIFO)
        out_row = rows[first + 2]
        self.assertEqual((out_row['F'], out_row['G'], float(out_row['J']), out_row['N']), ('TST-APP', 'A Applicant', 3.0, 'Tlip'))
        self.assertEqual(float(out_row['M']), 300000.0)                            # quantity x unit cost of the lot
        # Code.Mat: totals per code
        mat = xl.read_sheet_rows(io.BytesIO(data), 'code.mat', strict=True)
        row = next(c for r, c in mat.items() if c.get('A') == 'ST9901')
        self.assertEqual(row['B'], 'Acc Vest')
        self.assertEqual((float(row['D']), float(row['E']), float(row['F'])), (20.0, 13.0, 7.0))      # in, out, remain
        self.assertEqual((float(row['G']), float(row['H'])), (1100000.0, 300000.0 + 0.0))  # amount in / used (the opening has no cost)

    def test_only_store_staff_print_and_no_accounting_sheets_by_default(self):
        self._data()
        wiz, data = self._wizard(accounting=False)
        self.assertEqual(wiz.filename, 'Safety_Tool_control_sheet_2026-12-31.xlsx')
        names = zipfile.ZipFile(io.BytesIO(data)).read('xl/workbook.xml').decode()
        self.assertNotIn('Detail check', names)
        with self.assertRaises(UserError):
            self.env['safety.tool.report.wizard'].with_user(self.u_app).create({'accounting': True}).action_generate()

    def test_accounting_report_refreshes_from_remote(self):
        """With 'refresh from the remote server' the stock-ins that have a payment no. but no invoice are read first."""
        self._in(self.vest, 10, '2026-10-05', payment_no='EN26-0001')
        remote = FakeRemote()
        with mock.patch.object(type(self.env['kderp.remote.client']), 'execute', remote.as_method()):
            self._wizard(refresh_remote=True, date_to='2026-12-31', date_from='2026-01-01')
        self.assertTrue(remote.calls)
        move = self.Move.search([('payment_no', '=', 'EN26-0001')])
        self.assertEqual(move.invoice_no, 'INV-77')
        self.assertEqual(move.unit_cost, 100000.0)

    def test_remote_failure_does_not_stop_the_report(self):
        self._in(self.vest, 10, '2026-10-05', payment_no='EN26-0001')

        def broken(client, *args, **kwargs):
            raise UserError('remote down')
        with mock.patch.object(type(self.env['kderp.remote.client']), 'execute', broken):
            wiz, data = self._wizard(refresh_remote=True)
        self.assertTrue(data)

    def test_code_mat_counts_rows_without_purchase_quantity(self):
        """Code.Mat 'Out' uses the code and staff columns: handovers without staff code, and OUT rows without any lot, are counted."""
        self._in(self.vest, 2, '2026-03-01', unit_cost=10.0, invoice_no='INV-X', invoice_date='2026-02-01', payment_no='EN26-0300')
        self._out(self.vest, 1, '2026-04-01', self.e_app)
        self._out(self.vest, 4, '2026-04-02', None, note='S1234 / Left staff / Some job')       # plain move, no employee
        wiz, data = self._wizard()
        rows = xl.read_sheet_rows(io.BytesIO(data), 'detail', strict=True)
        out_rows = [c for r, c in rows.items() if r >= 4 and c.get('J') and c.get('F')]
        # FIFO: the lot has 2 pieces, so OUT 1 (1) and the first piece of OUT 4 come from it, the other 3 pieces are an orphan row
        self.assertEqual(sorted(float(c['J']) for c in out_rows), [1.0, 1.0, 3.0])
        self.assertIn('S1234', [c['F'] for c in out_rows])
        mat = xl.read_sheet_rows(io.BytesIO(data), 'code.mat', strict=True)
        row = next(c for r, c in mat.items() if c.get('A') == 'ST9901')
        self.assertEqual(float(row['E']), 5.0)                                                  # 1 + 4, also the orphan part
        self.assertEqual(float(row['D']), 2.0)


class TestControlSheet(Common):

    def test_layout_receipt_and_pictures(self):
        self._in(self.vest, 20, '2026-01-01', source='opening')
        self.vest.image = base64.b64encode(png())
        req = self._issued_request([{'item_id': self.vest.id, 'qty': 2}])
        self._in(self.vest, 3, '2026-02-01', invoice_no='INV-5', supplier_name='ACME')
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create({
            'date_from': '2026-01-01', 'date_to': '2100-01-01', 'item_ids': [(6, 0, [self.vest.id])]})
        wiz.action_generate()
        data = base64.b64decode(wiz.file)
        rows = xl.read_sheet_rows(io.BytesIO(data), 'control')
        self.assertEqual(rows[2]['B'], 'Safety Tool Control Sheet')
        header = rows[4]
        self.assertEqual((header['B'], header['C'], header['E'], header['F'], header['G'], header['L'], header['M'], header['N'], header['O']),
                         ('No.', 'Item', 'Date', 'Project Name', 'PIC', 'Remarks', 'Request from Kinden staff',
                          'Already order with supplier', 'Now order with supplier'))
        block = [c for r, c in sorted(rows.items()) if r >= 7]
        self.assertEqual(block[0]['B'], '9901')                                      # item number = number inside ST9901
        self.assertEqual(block[0]['L'], 'Periodical check')                          # opening line
        flat = [v for c in block for v in c.values()]
        self.assertIn('Invoice No. INV-5', flat)                                     # stock-in remark
        short = req.receipt_no.replace('SM-', '').lstrip('0')
        year, number = req.receipt_no[3:5], str(int(req.receipt_no[-4:]))
        self.assertIn('%s-%s' % (year, number), flat)                                # receipt no. of the OUT row, written 26-163
        self.assertTrue(short)
        # the picture of the item sits on the sheet
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertTrue([n for n in archive.namelist() if n.startswith('xl/media/')])

    def test_asked_and_ordered_columns(self):
        """Quantities requested by staff and not handed over yet, and what is already ordered with the supplier."""
        self._in(self.vest, 1, '2026-01-01', source='opening')
        req = self.env['safety.tool.request'].with_user(self.u_app).create({
            'reason': 'short', 'job_id': self.job.id, 'employee_id': self.e_app.id,
            'line_ids': [(0, 0, {'item_id': self.vest.id, 'qty': 4})]})
        req.with_user(self.u_app).action_submit()
        req.with_user(self.u_sm).validate_tier()
        req.with_user(self.u_safety).validate_tier()
        self.assertEqual(req.fulfilment_state, 'to_purchase')
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin)
        outstanding = wiz.create({})._outstanding()
        self.assertEqual(outstanding[(self.vest.id, False)], (4.0, 0.0))
        req.with_user(self.u_admin).action_mark_ordered()
        self.assertEqual(wiz.create({})._outstanding()[(self.vest.id, False)], (4.0, 4.0))


class TestAccountingImport(Common):
    """Import of the original (ACC) file: control sheet + the accounting sheets 'Detail check - report to Acc. D' and 'Code.Mat'."""

    OPEN = datetime.date(2025, 12, 31)
    INV_OLD = datetime.date(2025, 6, 1)
    INV_NEW = datetime.date(2026, 2, 1)

    def _file(self, accounting=True, extra_lot=False):
        import xlsxwriter
        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        ws = book.add_worksheet('Safety tool control  sheet')
        ws.write(1, 14, serial(datetime.date(2026, 9, 30)))
        ws.write(2, 14, 'No.150')
        for col, label in ((1, 'No.'), (2, 'Item'), (4, 'Date'), (5, 'Project Name'), (6, 'PIC'), (8, "Q'ty"), (11, 'Remarks')):
            ws.write(3, col, label)
        for col, label in ((8, 'IN'), (9, 'OUT'), (10, 'Remain')):
            ws.write(4, col, label)
        r = 6
        # block 1 (item number 8 -> ST0008): opening 10, IN 5 (Feb), OUT 2 (Mar, receipt 26-123), a later IN 5 with no lot, plain OUT 1
        ws.write(r, 1, 8)
        ws.write(r, 2, 'Imp Hat')
        ws.write(r, 4, serial(self.OPEN))
        ws.write(r, 10, 10)
        ws.write(r, 11, 'Periodical check')
        rows = [(datetime.date(2026, 2, 10), 'ACME', '', '', 5, None, 15, 'Invoice 1'),
                (datetime.date(2026, 3, 1), 'Proj X', 'TST-APP', 'A Applicant', None, 2, 13, '26-123'),
                (datetime.date(2026, 3, 5), 'Proj X', 'S9999', 'Left staff', None, 1, 12, ''),
                (datetime.date(2026, 9, 15), 'ACME', '', '', 5, None, 17, 'Invoice 3')]
        for date, project, code, name, qty_in, qty_out, remain, remark in rows:
            r += 1
            ws.write(r, 4, serial(date))
            ws.write(r, 5, project)
            ws.write(r, 6, code)
            ws.write(r, 7, name)
            if qty_in:
                ws.write(r, 8, qty_in)
            if qty_out:
                ws.write(r, 9, qty_out)
            ws.write(r, 10, remain)
            ws.write(r, 11, remark)
        if accounting:
            dt = book.add_worksheet('Detail check - report to Acc. D')
            lines = [
                # (row, columns)
                (3, {0: 'EN25-0001', 2: 'OLD SUPPLIER', 3: 'INV-OLD', 4: serial(self.INV_OLD)}),
                (4, {1: 'ST0008', 3: 'INV-OLD', 4: serial(self.INV_OLD), 7: 20, 10: 50000}),
                (5, {1: 'ST0008', 5: 'TST-APP', 6: 'A Applicant', 8: serial(datetime.date(2025, 7, 1)), 9: 3, 13: 'Tlip'}),
                (6, {0: 'EN26-0200', 2: 'ACME', 3: 'INV-NEW', 4: serial(self.INV_NEW)}),
                (7, {1: 'ST0008', 3: 'INV-NEW', 4: serial(self.INV_NEW), 7: 5, 10: 60000}),
                (8, {1: 'ST0008', 5: 'TST-APP', 6: 'A Applicant', 8: serial(datetime.date(2026, 3, 1)), 9: 2, 13: 'Hai phong', 14: '26-123'}),
                (9, {1: 'ST0008', 5: 'S9999', 6: 'Left staff', 8: serial(datetime.date(2026, 3, 5)), 9: 1, 13: 'Tlip'}),
            ]
            if extra_lot:
                lines += [(10, {0: 'EN26-0300', 2: 'CAP SUPPLIER', 3: 'INV-CAP', 4: serial(self.INV_NEW)}),
                          (11, {1: 'ST0077', 3: 'INV-CAP', 4: serial(self.INV_NEW), 7: 4, 10: 7000})]
            for row, cols in lines:
                for col, value in cols.items():
                    dt.write(row, col, value)
            cm = book.add_worksheet('Code.Mat')
            cm.write(7, 0, 'ST0008')
            cm.write(7, 1, 'Imp Hat')
            cm.write(8, 0, 'ST0077')
            cm.write(8, 1, 'Unknown Cap')
        book.close()
        return out.getvalue()

    def _import(self, data, **options):
        wiz = self.env['safety.tool.import.wizard'].with_user(self.u_admin).create(dict({'file': base64.b64encode(data), 'filename': 'acc.xlsx'}, **options))
        wiz.action_read()
        wiz.action_import()
        return wiz

    def _moves(self, item):
        return self.Move.search([('item_id', '=', item.id)], order='date, id')

    def test_parse_accounting_sheets(self):
        acc = xl.parse_accounting_sheets(io.BytesIO(self._file(extra_lot=True)))
        self.assertEqual(acc['codes'], {'ST0008': 'Imp Hat', 'ST0077': 'Unknown Cap'})
        lots = {l['invoice_no']: l for l in acc['lots']}
        self.assertEqual(lots['INV-NEW']['payment_no'], 'EN26-0200')
        self.assertEqual((lots['INV-NEW']['qty'], lots['INV-NEW']['unit_cost'], lots['INV-NEW']['supplier']), (5.0, 60000.0, 'ACME'))
        self.assertEqual(lots['INV-NEW']['invoice_date'], self.INV_NEW)
        self.assertEqual(len(acc['outs']), 3)
        out = [o for o in acc['outs'] if o['remark'] == '26-123'][0]
        self.assertEqual((out['staff'], out['qty'], out['area'], out['date']), ('TST-APP', 2.0, 'Hai phong', datetime.date(2026, 3, 1)))
        # a file without the accounting sheets
        none = xl.parse_accounting_sheets(io.BytesIO(self._file(accounting=False)))
        self.assertEqual((none['lots'], none['outs'], none['codes']), ([], [], {}))

    def test_import_fills_the_stock_ins_and_outs(self):
        wiz = self._import(self._file())
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Hat')])
        self.assertEqual(item.code, 'ST0008')                                          # the block number became the material code
        moves = self._moves(item)
        by_qty = {(m.qty_in, m.date): m for m in moves.filtered(lambda m: m.qty_in and not m.accounting_only and m.source == 'purchase')}
        feb = by_qty[(5.0, datetime.date(2026, 2, 10))]
        self.assertEqual((feb.invoice_no, feb.invoice_date, feb.unit_cost, feb.payment_no, feb.supplier_name),
                         ('INV-NEW', self.INV_NEW, 60000.0, 'EN26-0200', 'ACME'))
        sep = by_qty[(5.0, datetime.date(2026, 9, 15))]                                # far from the invoice date: not matched
        self.assertFalse(sep.invoice_no)
        self.assertFalse(sep.payment_no)
        out = moves.filtered(lambda m: m.qty_out == 2)
        self.assertEqual(out.work_area, 'Hai phong')                                   # the Excel knows the area per row
        self.assertEqual(out.request_id.receipt_no, 'SM-26-0123')                       # receipt no. from the remark (26-123)
        plain = moves.filtered(lambda m: m.qty_out == 1 and not m.accounting_only)
        self.assertFalse(plain.request_id)                                              # staff code unknown: a plain move
        self.assertEqual(plain.work_area, 'Tlip')                                       # matched through the code in its note
        self.assertIn('Accounting sheets', wiz.batch_id.note)

    def test_history_is_not_stock(self):
        wiz = self._import(self._file())
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Hat')])
        history = self._moves(item).filtered('accounting_only')
        self.assertEqual(sorted((m.qty_in, m.qty_out) for m in history), [(0.0, 3.0), (20.0, 0.0)])
        old_lot = history.filtered('qty_in')
        self.assertEqual((old_lot.invoice_no, old_lot.unit_cost, old_lot.payment_no, old_lot.supplier_name),
                         ('INV-OLD', 50000.0, 'EN25-0001', 'OLD SUPPLIER'))
        # stock = opening 10 + 5 - 2 - 1 + 5; the history changes nothing
        self.assertEqual(self.Move.stock_map([item.id])[(item.id, False)], 17.0)
        self.assertEqual(item.stock_qty, 17.0)
        # a second run rebuilds the history, nothing is doubled
        wiz2 = self.env['safety.tool.import.wizard'].with_user(self.u_admin).create({'file': base64.b64encode(self._file()), 'filename': 'acc.xlsx'})
        wiz2.action_read()
        wiz2.action_import()
        self.assertEqual(len(self._moves(item).filtered('accounting_only')), 2)
        self.assertEqual(self.Move.stock_map([item.id])[(item.id, False)], 17.0)
        # the ledger has a filter and a grey style for it
        arch = self.Move.get_view(view_type='search')['arch']
        self.assertIn('filter_acc_only', arch)

    def test_option_without_history(self):
        self._import(self._file(), create_history=False)
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Hat')])
        self.assertFalse(self._moves(item).filtered('accounting_only'))

    def test_option_without_accounting_sheets(self):
        self._import(self._file(), read_accounting=False)
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Hat')])
        moves = self._moves(item)
        self.assertFalse(moves.filtered('accounting_only'))
        self.assertFalse(any(moves.mapped('invoice_no')))
        self.assertEqual(sum(moves.mapped('unit_cost')), 0.0)
        self.assertEqual(item.code, 'ST0008')                                           # a new item takes the block number as its code

    def test_option_create_items_for_unknown_codes(self):
        self._import(self._file(extra_lot=True))
        self.assertFalse(self.env['safety.tool.item'].search([('code', '=', 'ST0077')]))   # off by default: only reported
        wiz = self._import(self._file(extra_lot=True), create_items=True)
        cap = self.env['safety.tool.item'].search([('code', '=', 'ST0077')])
        self.assertEqual(cap.name, 'Unknown Cap')
        self.assertIn('ST0077', wiz.batch_id.note)
        # it got its lot as accounting history (no opening balance: everything is older than the first real move)
        self.assertTrue(self._moves(cap).filtered(lambda m: m.accounting_only and m.qty_in == 4))

    def test_clean_refill_replaces_a_wrong_payment_no(self):
        """An Excel-filled stock-in with a wrong payment no. (typed by hand, no remote read) is corrected by the next import."""
        self._import(self._file())
        item = self.env['safety.tool.item'].search([('name', '=', 'Imp Hat')])
        feb = self._moves(item).filtered(lambda m: m.qty_in == 5 and m.date == datetime.date(2026, 2, 10))
        feb.write({'payment_no': 'EN26-WRONG'})
        self._import(self._file())
        self.assertEqual(feb.payment_no, 'EN26-0200')
        # a move read from the remote server keeps its data
        feb.write({'remote_synced_on': '2026-10-01 00:00:00', 'payment_no': 'EN26-KEEP'})
        self._import(self._file())
        self.assertEqual(feb.payment_no, 'EN26-KEEP')

    def test_import_dates_of_new_rows_are_dates(self):
        """New OUT rows with a receipt number once failed with 'str has no attribute year' (block rows are stored as JSON)."""
        self._import(self._file())
        out = self.env['safety.tool.request'].search([('is_imported', '=', True), ('receipt_no', '=', 'SM-26-0123')])
        self.assertEqual(out.date_input, datetime.date(2026, 3, 1))
        self.assertEqual(out.issued_date, datetime.date(2026, 3, 1))

    def test_pictures_of_the_file_become_item_photos(self):
        """The import takes the picture anchored on a block, resizes it (600x600 at most) and gives it to the item that has no photo."""
        import xlsxwriter
        from PIL import Image
        noise = Image.frombytes('RGB', (900, 700), os.urandom(900 * 700 * 3))
        raw = io.BytesIO()
        noise.save(raw, 'PNG')
        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        ws = book.add_worksheet('Safety tool control  sheet')
        for col, label in ((1, 'No.'), (2, 'Item'), (4, 'Date'), (5, 'Project Name'), (6, 'PIC'), (8, "Q'ty"), (11, 'Remarks')):
            ws.write(3, col, label)
        for col, label in ((8, 'IN'), (9, 'OUT'), (10, 'Remain')):
            ws.write(4, col, label)
        ws.write(6, 1, 9)
        ws.write(6, 2, 'Pic Helmet')
        ws.write(6, 4, serial(self.OPEN))
        ws.write(6, 10, 4)
        ws.write(6, 11, 'Periodical check')
        ws.insert_image(6, 3, 'helmet.png', {'image_data': io.BytesIO(raw.getvalue())})
        book.close()
        self._import(out.getvalue())
        item = self.env['safety.tool.item'].search([('name', '=', 'Pic Helmet')])
        self.assertTrue(item.image)
        size = Image.open(io.BytesIO(base64.b64decode(item.image))).size
        self.assertLessEqual(max(size), 600)
        self.assertGreater(min(size), 100)


class TestRoundTrip(Common):
    """Export the accounting file and import it again (twice): nothing is added, the stock and the accounting history stay the same,
    sized items go back to the right size."""

    def _data(self):
        boot26, boot27 = self.boot.size_ids.sorted('name')
        self.boot26, self.boot27 = boot26, boot27
        # item without sizes: opening, purchases (one without invoice yet), a stock-take adjustment, handovers over two lots, a plain handover
        self._in(self.vest, 10, '2025-12-31', source='opening')
        self._in(self.vest, 5, '2026-03-01', payment_no='EN26-0100', invoice_no='INV-1', invoice_date='2026-02-20',
                 unit_cost=100000.0, supplier_name='ACME')
        self._in(self.vest, 3, '2026-04-10')
        self._in(self.vest, 10, '2026-02-15', payment_no='EN26-0101', invoice_no='INV-1B', invoice_date='2026-02-10', unit_cost=90000.0,
                 supplier_name='ACME')
        self._in(self.vest, 1, '2026-05-01', source='manual', note='Stock-take difference')
        self._out(self.vest, 11, '2026-04-01', self.e_app, work_area='Tlip')
        self._out(self.vest, 2, '2026-06-01', None, note='S1234 / Left staff / Old job')
        self._out(self.vest, 10, '2026-07-01', self.e_app, work_area='Tlip')       # taken from two lots (FIFO): two rows in the accounting report
        # accounting history before the opening balance: an older lot and a handover taken from it
        hist = self.Move.with_context(safety_tool_system=True)
        hist.create({'item_id': self.vest.id, 'accounting_only': True, 'qty_in': 20, 'date': '2025-06-01', 'source': 'purchase',
                     'invoice_no': 'INV-OLD', 'invoice_date': '2025-06-01', 'unit_cost': 50000.0, 'payment_no': 'EN25-0001',
                     'supplier_name': 'OLD SUPPLIER'})
        hist.create({'item_id': self.vest.id, 'accounting_only': True, 'qty_out': 3, 'date': '2025-07-01', 'source': 'manual',
                     'employee_id': self.e_app.id, 'note': 'TST-APP A Applicant', 'work_area': 'Tlip'})
        # item with sizes: opening on the first day of the report (listed as an IN row), purchase, handover through a request
        self._in(self.boot, 5, '2026-01-01', size=boot26, source='opening')
        self._in(self.boot, 4, '2026-01-01', size=boot27, source='opening')
        self._in(self.boot, 6, '2026-02-01', size=boot26, payment_no='EN26-0300', invoice_no='INV-B', invoice_date='2026-01-25',
                 unit_cost=800000.0, supplier_name='SHOES')
        self.Move.create({'item_id': self.boot.id, 'size_id': boot27.id, 'qty_out': 2, 'date': '2026-03-05', 'source': 'manual',
                          'employee_id': self.e_app.id, 'work_area': 'Tlip'})

    def _snapshot(self):
        Move = self.Move.sudo()
        items = self.vest | self.boot
        moves = Move.search([('item_id', 'in', items.ids)])
        stock = Move.stock_map(items.ids)
        rows = sorted((m.item_id.name, m.size_id.name or '', m.date, m.qty_in, m.qty_out, m.accounting_only, m.source, m.invoice_no or '',
                       m.unit_cost, m.payment_no or '', m.supplier_name or '', m.work_area or '') for m in moves)
        return {'count': len(moves), 'stock': stock, 'rows': rows,
                'requests': self.env['safety.tool.request'].sudo().search_count([]),
                'items': self.env['safety.tool.item'].sudo().with_context(active_test=False).search_count([]),
                'sizes': self.env['safety.tool.size'].sudo().search_count([])}

    def _export(self):
        wiz = self.env['safety.tool.report.wizard'].with_user(self.u_admin).create({
            'date_from': '2026-01-01', 'date_to': '2026-12-31', 'accounting': True, 'refresh_remote': False})
        wiz.action_generate()
        return base64.b64decode(wiz.file)

    def _import(self, data):
        wiz = self.env['safety.tool.import.wizard'].with_user(self.u_admin).create({'file': base64.b64encode(data), 'filename': 'rt.xlsx'})
        wiz.action_read()
        self.assertFalse(wiz.line_ids.filtered(lambda l: l.action == 'create'), 'a block was not recognised: %s' % wiz.line_ids.mapped('excel_name'))
        wiz.action_import()
        return wiz

    def test_reimport_of_the_export_changes_nothing(self):
        self._data()
        before = self._snapshot()
        data = self._export()
        wiz1 = self._import(data)
        self.assertEqual(self._snapshot(), before, wiz1.batch_id.note)
        wiz2 = self._import(data)
        self.assertEqual(self._snapshot(), before, wiz2.batch_id.note)
        # the handover of 10 is listed under two lots (4 + 6) and still found as one OUT move
        rows = xl.read_sheet_rows(io.BytesIO(data), 'detail', strict=True)
        parts = sorted(float(c['J']) for r, c in rows.items() if r >= 4 and c.get('F') == 'TST-APP' and c.get('I') and c.get('J') and c.get('B') == 'ST9901'
                       and c['J'].replace('.', '').isdigit() and abs(float(c['J']) - 10) > 0.001 and float(c['J']) in (4.0, 6.0))
        self.assertEqual(parts, [4.0, 6.0])
        for wiz in (wiz1, wiz2):                                         # nothing is reported as missing either
            self.assertIn('not found in Odoo 0', wiz.batch_id.note)
            self.assertIn('not found 0', wiz.batch_id.note)

    def test_sized_blocks_go_back_to_their_size(self):
        self._data()
        data = self._export()
        wiz = self.env['safety.tool.import.wizard'].with_user(self.u_admin).create({'file': base64.b64encode(data), 'filename': 'rt.xlsx'})
        wiz.action_read()
        sized = wiz.line_ids.filtered(lambda l: l.item_id == self.boot)
        self.assertEqual(sorted(sized.mapped('size_id.name')), ['26.0', '27.0'])
        self.assertEqual(set(wiz.line_ids.mapped('action')), {'map'})

    def test_block_found_by_its_number_when_the_name_differs(self):
        """A block whose name is not the item's (long names are wrapped) is mapped by the Code Mat. of its number."""
        self._data()
        self.vest.name = 'Acc Vest renamed in Odoo'
        data = self._export()
        self.vest.name = 'Acc Vest'
        wiz = self.env['safety.tool.import.wizard'].with_user(self.u_admin).create({'file': base64.b64encode(data), 'filename': 'rt.xlsx'})
        wiz.action_read()
        self.assertEqual(wiz.line_ids.filtered(lambda l: l.excel_name.startswith('Acc Vest')).item_id, self.vest)

    def test_import_into_an_empty_ledger_rebuilds_the_same_state(self):
        """Export, wipe the ledger, import: same stock per item and size, the lots keep their invoice data, history is back, no extra history."""
        self._data()
        before = self._snapshot()
        data = self._export()
        self.Move.sudo().with_context(safety_tool_system=True).search([('item_id', 'in', (self.vest | self.boot).ids)]).unlink()
        self._import(data)
        after = self._snapshot()
        self.assertEqual(after['stock'], before['stock'])
        history = lambda snap: [r for r in snap['rows'] if r[5]]
        self.assertEqual(len(history(after)), len(history(before)))
        lots = lambda snap: sorted((r[0], r[1], r[3], r[7], r[8], r[9]) for r in snap['rows'] if r[3] and r[7] and not r[5])   # lots with invoice data
        self.assertEqual(lots(after), lots(before))                       # invoice, unit cost and payment no. came back
        # and a second import changes nothing
        self._import(data)
        self.assertEqual(self._snapshot(), after)

    def test_size_code_is_in_the_item_form(self):
        arch = self.env['safety.tool.item'].with_user(self.u_admin).get_view(view_type='form')['arch']
        self.assertIn('placeholder="same as the item"', arch)

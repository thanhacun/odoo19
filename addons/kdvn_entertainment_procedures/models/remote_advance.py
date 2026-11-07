"""Create the advance request of an approved entertainment fee on the remote server (direct JSON-RPC).

Flow: the applicant opens a dialog that suggests who should continue the process on the remote (see
remote_candidates.py: the job's site admins, then the people who usually enter advances for this job / applicant),
sees a preview and creates the advance. The remote record is a draft `kderp.advance.payment` whose "Input User" is
the chosen person, so she can see it (remote rule `user_input.user_id = me`) and continue the process.
Everything is read first; nothing is written unless the 'advance' live switch of kdvn_remote_integration is ON (dry run otherwise).
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup

from odoo.addons.kdvn_remote_integration.models.remote_client import RemoteNotLive

_logger = logging.getLogger(__name__)


class EntertainmentRequest(models.Model):
    _inherit = 'entertainment.request'

    # Allowed to be written once the request is approved/locked
    _allow_to_write_field_list = ['remote_advance_id', 'remote_advance_code', 'remote_advance_admin']

    remote_advance_id = fields.Integer('Remote advance ID', readonly=True, copy=False)
    remote_advance_code = fields.Char('Advance request No. (remote)', readonly=True, copy=False, tracking=True)
    remote_advance_admin = fields.Char('Advance handled by (input user)', readonly=True, copy=False)

    can_create_remote_advance = fields.Boolean(compute='_compute_can_create_remote_advance')

    @api.depends('state', 'remote_advance_code', 'employee_id')
    def _compute_can_create_remote_advance(self):
        user = self.env.user
        for rec in self:
            rec.can_create_remote_advance = bool(
                rec.state == 'approved' and not rec.remote_advance_code and (
                    rec.employee_id.user_id == user or self.env.uid == 1
                    or any(user.has_group(g) for g in rec._admin_groups)))

    # ------------------------------------------------------------------ guards
    def _check_can_create_remote_advance(self):
        self.ensure_one()
        user = self.env.user
        if self.state != 'approved':
            raise UserError(_("The advance request can only be created from an approved request."))
        if self.remote_advance_code:
            raise UserError(_("The advance request %s was already created on the remote server.") % self.remote_advance_code)
        is_applicant = self.employee_id.user_id == user
        is_admin = self.env.uid == 1 or any(user.has_group(g) for g in self._admin_groups)
        if not (is_applicant or is_admin):
            raise UserError(_("Only the applicant can create the advance request."))
        if not self.job_id or not self.job_id.external_id:
            raise UserError(_("The request has no job from the remote server."))
        if not (self.employee_id.code or '').strip():
            raise UserError(_("The applicant has no staff code, so the remote employee cannot be found."))

    def action_open_advance_wizard(self):
        self.ensure_one()
        self._check_can_create_remote_advance()
        wiz = self.env['entertainment.advance.wizard'].create({'request_id': self.id})
        wiz._load_candidates()
        return {
            'name': _('Create advance request on the remote server'),
            'type': 'ir.actions.act_window',
            'res_model': 'entertainment.advance.wizard',
            'res_id': wiz.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------ remote reads
    @api.model
    def _remote(self, model, method, args=None, kwargs=None):
        # The Writer logs in for everything here: the creates, and the reads that need its wide visibility (advance history).
        # A write only runs when the "advance" live switch is on (RemoteNotLive otherwise).
        return self.env['kderp.remote.client'].execute(model, method, args, kwargs, account='writer', task='advance')

    def _remote_applicant(self):
        """The applicant's employee on the remote server (found by staff code; must be exactly one)."""
        self.ensure_one()
        emp_code = (self.employee_id.code or '').strip()
        emps = self._remote('hr.employee', 'search_read', [[('code', '=', emp_code)]],
                            {'fields': ['name', 'bank_name', 'bank_account_number', 'bank_account_name', 'user_id'], 'limit': 2})
        if len(emps) != 1:
            raise UserError(_("Staff code %s matches %s employees on the remote server (expected 1).") % (emp_code, len(emps)))
        return emps[0]

    def _remote_note_prefix(self):
        # Fixed text (not translated): the duplicate lookup searches for it on the remote
        return 'Entertainment fee %s - ' % self.name

    def _remote_advance_note(self):
        return '%s%s (%s)' % (self._remote_note_prefix(), self.place or '', self.date_entertainment)

    def _remote_find_existing_advance(self):
        """An advance whose notes already carry this request number (a retry after a lost answer)."""
        self.ensure_one()
        recs = self._remote('kderp.advance.payment', 'search_read',
                            [[('name', 'ilike', self._remote_note_prefix()), ('active', 'in', [True, False])]],
                            {'fields': ['code'], 'limit': 1})
        return recs and recs[0] or False

    def _remote_prepare_advance(self, admin):
        """All reads + the values to send. `admin` is one dict of `_remote_input_candidates`. Nothing is written."""
        self.ensure_one()
        if not admin or not admin.get('ok'):
            raise UserError(_("Choose a person who can process the advance request."))
        emp_code = self.employee_id.code.strip()
        emp = self._remote_applicant()
        cur = self._remote('res.currency', 'search_read', [[('name', '=', 'VND')]], {'fields': ['id'], 'limit': 1})
        if not cur:
            raise UserError(_("Currency VND was not found on the remote server."))
        adv_date = fields.Date.to_string(fields.Date.context_today(self))   # JSON needs a string
        note = self._remote_advance_note()
        vals = {
            'date': adv_date,
            'user_id': emp['id'],
            'user_input': admin['employee_id'],
            'currency_id': cur[0]['id'],
            'account_analytic_id': self.job_id.external_id,
            'location_id': admin['location_id'],
            'advance_buying': 'others',
            'type_cash': 'payment',
            'name': note,
            'bank_name': emp.get('bank_name') or False,
            'bank_account_number': emp.get('bank_account_number') or False,
            'bank_account_name': emp.get('bank_account_name') or False,
            'advance_line': [(0, 0, {'name': note[:256], 'amount': self.estimated_amount})],
        }
        vals['code'] = self._remote_next_code(emp_code, admin['location_code'], adv_date)
        return {'vals': vals, 'applicant_remote': emp['name'], 'existing': self._remote_find_existing_advance()}

    def _remote_next_code(self, emp_code, location_code, adv_date):
        """Next free number (highest existing + 1, reserves nothing). Read again right before every create."""
        ctx = {'ir_sequence_date': str(adv_date), 'staffcode': emp_code[-4:], 'custom_location': location_code,
               'filter_by_sequence_code': 'advance'}
        seq = self._remote('ir.sequence', 'search_read', [[('code', '=', 'advance')]], {'fields': ['code_next'], 'context': ctx})
        if len(seq) != 1 or not seq[0].get('code_next'):
            raise UserError(_("The advance number sequence was not found on the remote server."))
        return seq[0]['code_next']

    # ------------------------------------------------------------------ remote write
    def _remote_create_advance(self, admin):
        """Creates the draft advance on the remote. Raises RemoteNotLive in dry-run mode (nothing written)."""
        self.ensure_one()
        self._check_can_create_remote_advance()
        prep = self._remote_prepare_advance(admin)
        if prep['existing']:
            # Adopt instead of creating a second one
            self._remote_store_result(prep['existing']['id'], prep['existing']['code'], admin, adopted=True)
            return prep['existing']['code'], True
        vals = prep['vals']
        new_id = False
        for attempt in (1, 2):
            try:
                new_id = self._remote('kderp.advance.payment', 'create', [vals])
                break
            except UserError as e:
                if isinstance(e, RemoteNotLive):
                    raise
                if attempt == 2 or 'unique' not in str(e).lower():
                    raise
                # Somebody took the number in between: read the next free one again, once
                vals['code'] = self._remote_next_code(self.employee_id.code.strip(), admin['location_code'], vals['date'])
        code = self._remote('kderp.advance.payment', 'read', [[new_id], ['code']])[0]['code']
        self._remote_store_result(new_id, code, admin)
        if code != vals['code']:
            # The remote replaced our number (taken in between): it may carry the integration user's location letter
            self.message_post(body=_("Note: the remote server changed the advance number from %(a)s to %(b)s. Please check the location letter.") % {
                'a': vals['code'], 'b': code})
        return code, False

    def _remote_store_result(self, remote_id, code, admin, adopted=False):
        self.ensure_one()
        who = '%s (%s)' % (admin['name'], admin['login'])
        self.write({'remote_advance_id': remote_id, 'remote_advance_code': code, 'remote_advance_admin': who})
        body = Markup(_("Advance request <b>%(code)s</b> %(how)s on the remote server. Input user to continue: <b>%(who)s</b>%(team)s.")) % {
            'code': code, 'who': who,
            'how': _("found (already created)") if adopted else _("created"),
            'team': (' - ' + admin['team']) if admin.get('team') else ''}
        if admin.get('why') and not adopted:
            body += Markup('<br/>') + _("Chosen because: %s.") % admin['why']
        self.message_post(body=body)

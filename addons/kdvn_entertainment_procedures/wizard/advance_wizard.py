from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html_escape

from odoo.addons.kdvn_remote_integration.models.remote_client import RemoteNotLive


class EntertainmentAdvanceWizardLine(models.TransientModel):
    _name = 'entertainment.advance.wizard.line'
    _description = 'Input user candidate (suggested from the remote server)'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('entertainment.advance.wizard', ondelete='cascade')
    sequence = fields.Integer()
    remote_user_id = fields.Integer()
    employee_id = fields.Integer()
    location_id = fields.Integer('Location ID')
    location_code = fields.Char()
    name = fields.Char('Person')
    login = fields.Char()
    location_name = fields.Char('Office')
    team = fields.Char('Input team')
    roles = fields.Char('Remote role')
    why = fields.Char('Why suggested')
    is_admin = fields.Boolean('Job site admin')
    suggested = fields.Boolean('Suggested')
    mark = fields.Char(' ')
    ok = fields.Boolean('Can process')
    reason = fields.Char('Why not')

    def _as_admin(self):
        self.ensure_one()
        return {'remote_user_id': self.remote_user_id, 'employee_id': self.employee_id, 'location_id': self.location_id,
                'location_code': self.location_code, 'name': self.name, 'login': self.login,
                'location_name': self.location_name, 'team': self.team, 'roles': self.roles, 'why': self.why,
                'ok': self.ok, 'reason': self.reason}


class EntertainmentAdvanceWizard(models.TransientModel):
    _name = 'entertainment.advance.wizard'
    _description = 'Create the advance request on the remote server'

    request_id = fields.Many2one('entertainment.request', required=True, ondelete='cascade')
    line_ids = fields.One2many('entertainment.advance.wizard.line', 'wizard_id', string='Who can continue the process')
    admin_line_id = fields.Many2one('entertainment.advance.wizard.line', string='Input user (continues the process)',
                                    domain="[('wizard_id', '=', id), ('ok', '=', True)]")
    live = fields.Boolean(compute='_compute_live', string='Live')
    hint = fields.Html(readonly=True)
    how = fields.Html('How these people were suggested', readonly=True)
    preview = fields.Html(readonly=True)

    @api.depends('request_id')
    def _compute_live(self):
        live = self.env['kderp.remote.client'].is_live('advance')
        for w in self:
            w.live = live

    def _load_candidates(self):
        self.ensure_one()
        meta = {}
        cands = self.request_id._remote_input_candidates(meta)
        job = self.request_id.job_id
        self.line_ids.unlink()
        lines = self.env['entertainment.advance.wizard.line']
        for i, c in enumerate(cands):
            lines |= lines.create({
                'wizard_id': self.id, 'sequence': i, 'remote_user_id': c['remote_user_id'], 'employee_id': c['employee_id'],
                'location_id': c['location_id'], 'location_code': c['location_code'], 'name': c['name'], 'login': c['login'],
                'location_name': c['location_name'], 'team': c['team'], 'roles': c['roles'], 'why': c['why'], 'is_admin': c['is_admin'],
                'suggested': c['suggested'], 'mark': u'\u2605' if c['suggested'] else '', 'ok': c['ok'], 'reason': c['reason']})
        self.how = self._build_how(meta, cands)
        ok = lines.filtered('ok')
        has_admin = any(c['is_admin'] for c in cands)
        if not has_admin and ok:
            self.hint = '<div class="alert alert-info"><b>%s</b><br/>%s</div>' % (
                html_escape(_("Job %s has no site admin on the remote server.") % job.job_no),
                html_escape(_("The people below are suggested from the advance requests entered before (this job, this applicant). "
                              "Please also ask the job's project manager or section manager to add a site admin "
                              "(remote server: Job > Site Admin tab), so the next request can use it.")))
        if ok:
            self.admin_line_id = lines.filtered('suggested')[:1] or ok[:1]
            self._build_preview()
        elif not cands:
            self.hint = '<div class="alert alert-danger"><b>%s</b><br/>%s</div>' % (
                html_escape(_("Nobody could be suggested for job %s.") % job.job_no),
                html_escape(_("The job has no site admin on the remote server and no earlier advance request of this job, applicant or office "
                              "could be read. Please inform the job's project manager or section manager so that a site admin is added "
                              "(remote server: Job > Site Admin tab). Then open this dialog again.")))
        else:
            self.hint = '<div class="alert alert-danger"><b>%s</b><br/>%s</div>' % (
                html_escape(_("None of the people found for job %s can process an advance request.") % job.job_no),
                html_escape(_("See the reason in the list below. The person needs an active user with an employee record, an office with a code "
                              "letter, the 'User Input' right and a place in a site admin or input team group on the remote server. "
                              "Ask for it to be corrected there, then open this dialog again.")))

    @api.model
    def _build_how(self, meta, cands):
        """TEMPORARY note for the discussion: how the list above was made, with the numbers read for THIS request."""
        def n_adv(t):
            return _("%(adv)d advance request(s) entered by %(people)d person(s)") % {'adv': t[1], 'people': t[0]}
        e = html_escape
        steps = [
            _("<b>Job site admins</b> (remote: Job &gt; Site Admin tab): %s.") % (
                _("%d found, all are listed") % meta['n_admins'] if meta['n_admins'] else _("none")),
            _("<b>Earlier advance requests on this job %(job)s</b>: %(n)s.") % {
                'job': e(meta['job_no']), 'n': n_adv(meta['job']) if meta['job'][1] else _("none")},
            _("<b>This applicant (%(name)s), last %(days)d days</b>: %(n)s.") % {
                'name': e(meta['applicant']), 'days': meta['days'], 'n': n_adv(meta['applicant_hist']) if meta['applicant_hist'][1] else _("none")},
        ]
        if meta['pm_state'] == 'read':
            steps.append(_("<b>Job project manager (%(name)s), last %(days)d days</b> (read because fewer than 3 people were found so far): %(n)s.") % {
                'name': e(meta['pm_name']), 'days': meta['days'], 'n': n_adv(meta['pm']) if meta['pm'][1] else _("none")})
        elif meta['pm_state'] == 'no_pm':
            steps.append(_("<b>Job project manager</b>: the job has none on the remote server."))
        else:
            steps.append(_("<b>Job project manager</b>: not read (enough people were already found)."))
        if meta['office_state'] == 'read':
            steps.append(_("<b>Applicant's office (%(name)s), last %(days)d days</b> (read because fewer than 3 people were found so far): %(n)s.") % {
                'name': e(meta['office'][2]), 'days': meta['days'], 'n': n_adv(meta['office'][:2]) if meta['office'][1] else _("none")})
        elif meta['office_state'] == 'no_office':
            steps.append(_("<b>Applicant's office</b>: the applicant has no user or office on the remote server."))
        else:
            steps.append(_("<b>Applicant's office</b>: not read (enough people were already found)."))
        rules = [
            _("Order of the list: job site admins first, then the people of this job's history, then the applicant's, then the project manager's "
              "and the office's (only when needed). Inside one step the most frequent comes first; a person found by several steps appears once "
              "with all the reasons."),
            _("The first person who can process it is preselected (&#9733;). Up to 6 rows; the job's site admins are never cut."),
            _("Who can process it: an active user with an employee record, an office with a code letter (so not 'Global') and the 'User Input' right "
              "on advance requests. No group is required: site admins, input teams, 'Manage a Location' people and Advance Cash Admin/Submit people all "
              "qualify. The others stay in the list, greyed, with the reason (%d here).") % meta.get('n_ineligible', 0),
            _("Back-test on the 2025-2026 advance requests of the remote server: for jobs without a site admin the first suggestion was the real input "
              "user in about 8 cases out of 10, and the real one was among the first 3 in about 95% (small sample: 39 entertainment cases)."),
        ]
        return ('<div class="alert alert-warning"><b>%s</b><ol>%s</ol><ul class="small">%s</ul></div>' % (
            e(_("How these people were suggested (temporary note, for discussion)")),
            ''.join('<li>%s</li>' % x for x in steps), ''.join('<li>%s</li>' % x for x in rules)))

    @api.onchange('admin_line_id')
    def _onchange_admin_line_id(self):
        self._build_preview()

    def _build_preview(self):
        self.ensure_one()
        if not self.admin_line_id:
            self.preview = False
            return
        prep = self.request_id._remote_prepare_advance(self.admin_line_id._as_admin())
        v = prep['vals']
        rows = [
            (_("Advance No."), v['code']), (_("Applicant (remote)"), prep['applicant_remote']),
            (_("Input user (continues the process)"), ' - '.join(x for x in (self.admin_line_id.name, self.admin_line_id.team,
                                                                                self.admin_line_id.location_name) if x)),
            (_("Why this person"), self.admin_line_id.why or _("chosen by hand")),
            (_("Job"), self.request_id.job_id.display_name), (_("Amount (VND)"), '{:,.0f}'.format(self.request_id.estimated_amount)),
            (_("Notes"), v['name']),
            (_("Bank"), ' / '.join(x for x in (v['bank_name'], v['bank_account_number'], v['bank_account_name']) if x) or _("(none on the remote employee)")),
        ]
        html = '<table class="table table-condensed">%s</table>' % ''.join(
            '<tr><td><b>%s</b></td><td>%s</td></tr>' % (html_escape(k), html_escape(str(val))) for k, val in rows)
        if prep['existing']:
            html = '<p class="text-warning">%s</p>' % html_escape(
                _("An advance request %s already carries this request number: it will be linked, not created again.") % prep['existing']['code']) + html
        if not self.live:
            html = '<p class="text-muted">%s</p>' % html_escape(_("Dry run: nothing is written to the remote server.")) + html
        self.preview = html

    def action_create(self):
        self.ensure_one()
        if not self.admin_line_id:
            raise UserError(_("Choose the input user first."))
        try:
            code, adopted = self.request_id._remote_create_advance(self.admin_line_id._as_admin())
        except RemoteNotLive:
            return self.env['kderp.notification.wizard'].show_notification_wizard(
                message=_("Dry run: the advance request was NOT created on the remote server (writing is switched off in Settings > Remote Server Connection). "
                          "The preview shows what would be sent."),
                title=_("Dry run"), show_cancel=False)
        msg = _("Advance request %s is on the remote server.") % code if not adopted else _("Advance request %s already existed and is now linked.") % code
        return self.env['kderp.notification.wizard'].show_notification_wizard(
            message=msg + "\n" + _("Input user to continue: %s.") % self.admin_line_id.name, title=_("Advance request"), show_cancel=False)

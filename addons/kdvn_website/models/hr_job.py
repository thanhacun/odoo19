from odoo import _, api, fields, models


class HrJob(models.Model):
    """Open Positions page (/jobs): the facts shown on the cards and the job page."""
    _inherit = 'hr.job'

    kdvn_salary = fields.Char(
        'Salary (website)', translate=True,
        help='Shown on the job page, e.g. "15 ~ 20tr VND". Empty: "Negotiable".')
    kdvn_job_level = fields.Char('Job Level', translate=True, help='Shown on the job page, e.g. "Senior, Middle".')
    kdvn_work_mode = fields.Selection(
        [('on_site', 'On-site'), ('hybrid', 'Hybrid'), ('remote', 'Remote')],
        'Work Mode', default='on_site')
    kdvn_apply_deadline = fields.Date(
        'Apply Before', help='Last day to apply. Shown as "You have N days to apply" until then.')
    # Same field as Odoo's, with our default text (Job Description / Requirements / Desirable / Benefits)
    website_description = fields.Html(default=lambda self: self._kdvn_default_website_description())

    @api.model
    def _kdvn_default_website_description(self):
        return self.env['ir.qweb']._render('kdvn_website.job_default_description', raise_if_not_found=False)

    def _kdvn_days_left(self):
        """Days left to apply (0 = last day), or None without a deadline or after it."""
        self.ensure_one()
        if not self.kdvn_apply_deadline:
            return None
        days = (self.kdvn_apply_deadline - fields.Date.context_today(self)).days
        return days if days >= 0 else None

    def _kdvn_deadline_label(self):
        """'You have 5 days to apply', or '' when there is no (open) deadline."""
        days = self._kdvn_days_left()
        if days is None:
            return ''
        if days == 0:
            return _('Last day to apply')
        if days == 1:
            return _('You have 1 day to apply')
        return _('You have %s days to apply', days)

    def _kdvn_posted_label(self):
        """'Today', '5 days ago', '1 week ago' ... from the last update."""
        self.ensure_one()
        days = max((fields.Date.context_today(self) - fields.Date.to_date(self.write_date)).days, 0)
        if days == 0:
            return _('Today')
        if days == 1:
            return _('Yesterday')
        if days < 7:
            return _('%s days ago', days)
        weeks = days // 7
        if days < 30:
            return _('1 week ago') if weeks == 1 else _('%s weeks ago', weeks)
        months = days // 30
        if days < 365:
            return _('1 month ago') if months == 1 else _('%s months ago', months)
        years = days // 365
        return _('1 year ago') if years == 1 else _('%s years ago', years)

    def _kdvn_work_mode_label(self):
        self.ensure_one()
        selection = self._fields['kdvn_work_mode']._description_selection(self.env)
        return dict(selection).get(self.kdvn_work_mode, '')

    def _kdvn_location(self):
        """'Hanoi, Vietnam' from the job's office, 'Remote' without one."""
        self.ensure_one()
        return self.address_id.sudo()._kdvn_job_location() or _('Remote')

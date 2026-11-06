from odoo import _, api, fields, models

from .remote_client import PARAM, TASKS


class ResConfigSettings(models.TransientModel):
    """Settings > Remote Server Connection (app block "Remote Server" in the Settings sidebar)."""
    _inherit = 'res.config.settings'

    kderp_remote_url = fields.Char('Remote server URL', help="Base URL of the KDERP (Odoo 12) server, e.g. http://host:8169")
    kderp_remote_db = fields.Char('Remote database')
    kderp_remote_reader_login = fields.Char('Reader login')
    kderp_remote_reader_password = fields.Char('Reader password', help="Leave empty to keep the saved password. It is never shown again.")
    kderp_remote_reader_password_saved = fields.Boolean()
    kderp_remote_writer_login = fields.Char('Writer login')
    kderp_remote_writer_password = fields.Char('Writer password', help="Leave empty to keep the saved password. It is never shown again.")
    kderp_remote_writer_password_saved = fields.Boolean()
    kderp_remote_live_advance = fields.Boolean('Advance requests: write for real (production only)')
    kderp_remote_live_staff_location = fields.Boolean('Staff locations: write for real (production only)')

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        res.update(
            kderp_remote_url=icp.get_param(PARAM + 'url', default=''),
            kderp_remote_db=icp.get_param(PARAM + 'db', default=''),
            kderp_remote_reader_login=icp.get_param(PARAM + 'reader_login', default=''),
            kderp_remote_reader_password='',                  # a password is never sent to the browser
            kderp_remote_reader_password_saved=bool(icp.get_param(PARAM + 'reader_password')),
            kderp_remote_writer_login=icp.get_param(PARAM + 'writer_login', default=''),
            kderp_remote_writer_password='',
            kderp_remote_writer_password_saved=bool(icp.get_param(PARAM + 'writer_password')),
            kderp_remote_live_advance=icp.get_param(PARAM + 'live.advance') == 'True',
            kderp_remote_live_staff_location=icp.get_param(PARAM + 'live.staff_location') == 'True',
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param(PARAM + 'url', (self.kderp_remote_url or '').strip())
        icp.set_param(PARAM + 'db', (self.kderp_remote_db or '').strip())
        icp.set_param(PARAM + 'reader_login', (self.kderp_remote_reader_login or '').strip())
        icp.set_param(PARAM + 'writer_login', (self.kderp_remote_writer_login or '').strip())
        if self.kderp_remote_reader_password:               # empty = keep the saved one
            icp.set_param(PARAM + 'reader_password', self.kderp_remote_reader_password)
        if self.kderp_remote_writer_password:
            icp.set_param(PARAM + 'writer_password', self.kderp_remote_writer_password)
        icp.set_param(PARAM + 'live.advance', 'True' if self.kderp_remote_live_advance else 'False')
        icp.set_param(PARAM + 'live.staff_location', 'True' if self.kderp_remote_live_staff_location else 'False')

    def action_kderp_remote_test_connection(self):
        """Read-only. Tests what is typed on the page (empty fields fall back to the saved values); nothing is saved."""
        self.ensure_one()
        info = self.env['kderp.remote.client'].test_connection(override={
            'url': self.kderp_remote_url, 'db': self.kderp_remote_db,
            'reader_login': self.kderp_remote_reader_login, 'reader_password': self.kderp_remote_reader_password,
            'writer_login': self.kderp_remote_writer_login, 'writer_password': self.kderp_remote_writer_password})
        lines = [_("Connected to the remote server (version %s).", info['version']), '']
        for account, title in (('writer', _('Writer')), ('reader', _('Reader'))):
            f = info['accounts'].get(account)
            if f is None:
                lines.append(_("%s: not set up.", title))
            elif f.get('same_as_writer'):
                lines.append(_("%s: not set up, reads use the Writer.", title))
            else:
                rights = f['rights']
                lines.append(_("%(title)s: %(login)s (uid %(uid)s), location %(loc)s",
                               title=title, login=f['login'], uid=f['uid'], loc=f['location'] or '-'))
                lines.append('    ' + ', '.join('%s %s' % (m, r) for m, r in sorted(rights.items()))
                             + '   (r read, c create, w write, u delete)')
                if account == 'writer':
                    if 'c' not in rights['kderp.advance.payment']:
                        lines.append(_("    WARNING: cannot create advance requests (add the login to the Advance Cash / Admin group)."))
                    if 'c' not in rights['kderp.hr.employee.location']:
                        lines.append(_("    WARNING: cannot create staff location lines (needs the KDERP HR 'User Input' group)."))
                else:
                    wide = [m for m, r in sorted(rights.items()) if set(r) & set('cwu')]
                    if wide:
                        lines.append(_("    Note: this login could change data on the remote (%s). Odoo never writes with it, "
                                       "but you may want to tighten it there.", ', '.join(wide)))
        lines.append('')
        lines.append(_("Real writes: %s", ', '.join(
            '%s %s' % (label, _('LIVE') if info['live'][task] else _('dry run')) for task, label in TASKS)))
        wizard = self.env['kderp.remote.test.result'].create({'message': '\n'.join(lines)})
        return {
            'type': 'ir.actions.act_window', 'name': _("Remote server connection"),
            'res_model': 'kderp.remote.test.result', 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
        }


class KderpRemoteTestResult(models.TransientModel):
    _name = 'kderp.remote.test.result'
    _description = 'Result of the remote server connection test'

    message = fields.Text(readonly=True)

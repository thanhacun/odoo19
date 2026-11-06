# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def normalize_location_name(name):
    """'TLIP 1' and 'tlip1' give the same key (used only to suggest a remote location, HR confirms)."""
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


class KderpStaffLocationRemote(models.Model):
    """Names of the locations that exist on the remote server (read from it each time the wizard
    reaches the mapping step), so HR can pick one from a list. Never created or edited by hand."""
    _name = 'kderp.staff.location.remote'
    _description = 'Location name on the remote server'
    _order = 'name'

    name = fields.Char(required=True, readonly=True)
    active = fields.Boolean(default=True, readonly=True, help='Off when the remote no longer has this location.')
    _name_unique = models.Constraint('unique(name)', 'Remote location names are unique.')

    @api.model
    def refresh_from_remote(self):
        """Read the remote's location names (kderp.employee.location.code) and update this list. Returns the count."""
        rows = self.env['kderp.remote.client'].execute('kderp.employee.location.code', 'search_read', [[]], {'fields': ['name']})
        names = sorted({(r.get('name') or '').strip() for r in rows if (r.get('name') or '').strip()})
        if not names:
            raise UserError(_("The remote server returned no staff locations."))
        names = [str(n).strip() for n in names if n and str(n).strip()]
        Remote = self.sudo().with_context(active_test=False)
        existing = {r.name: r for r in Remote.search([])}
        for n in names:
            if n in existing:
                if not existing[n].active:
                    existing[n].active = True
            else:
                Remote.create({'name': n})
        for n, rec in existing.items():
            if n not in names and rec.active:
                rec.active = False       # kept (a mapping may point to it), but no longer offered
        return len(names)


class KderpStaffLocationMap(models.Model):
    """Which remote location a local location (Location History name) is sent as. Chosen by HR in the sync wizard
    and kept for the next month. A local location without a line here is not sent."""
    _name = 'kderp.staff.location.map'
    _description = 'Local location -> remote location'
    _order = 'location_id'

    location_id = fields.Many2one('kderp.employee.location.code', 'Our location', required=True, ondelete='cascade')
    remote_id = fields.Many2one('kderp.staff.location.remote', 'Remote location', required=True, ondelete='restrict')
    _location_unique = models.Constraint('unique(location_id)', 'This location is already mapped.')

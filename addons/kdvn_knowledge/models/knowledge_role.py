from odoo import api, fields, models

# Groups linked to the default roles when their modules are installed (xml ids; missing ones are skipped).
DEFAULT_ROLE_GROUPS = {
    'manager': [
        'kdvn_hr_attendance.group_hr_attendance_section_manager',
        'kdvn_hr_attendance.group_hr_attendance_gm',
    ],
    'admin': [
        'kdvn_e_approval.group_e_approval_admin',
    ],
}


class KderpKnowledgeRole(models.Model):
    """A reader role used by guide pages: 'roles: [...]' in a page's front matter and
    '::: role ...' blocks inside a page. A user has a role when he is in one of its groups.
    Knowledge managers and reviewers see everything."""
    _name = 'kderp.knowledge.role'
    _description = 'Knowledge reader role'
    _order = 'sequence, id'

    code = fields.Char(required=True, help='Used in guide sources, e.g. applicant, manager, admin.')
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    group_ids = fields.Many2many('res.groups', string='Groups',
                                 help='Users in any of these groups have this role.')

    _code_unique = models.Constraint('unique(code)', 'A role with this code already exists.')

    @api.model
    def _link_default_groups(self):
        """Add the groups of installed modules to the default roles (never removes groups)."""
        for code, xml_ids in DEFAULT_ROLE_GROUPS.items():
            role = self.search([('code', '=', code)], limit=1)
            if not role:
                continue
            groups = self.env['res.groups']
            for xml_id in xml_ids:
                groups |= self.env.ref(xml_id, raise_if_not_found=False) or self.env['res.groups']
            if groups:
                role.write({'group_ids': [(4, g.id) for g in groups]})
        return True

    @api.model
    def user_sees_all(self, user=None):
        user = user or self.env.user
        return user.has_group('document_page.group_document_manager') or \
            user.has_group('kdvn_knowledge.group_knowledge_reviewer')

    @api.model
    def user_role_codes(self, user=None):
        """Role codes of the user (all codes for knowledge managers and reviewers)."""
        user = user or self.env.user
        roles = self.sudo().search([])
        if self.user_sees_all(user):
            return set(roles.mapped('code'))
        return set(roles.filtered(lambda r: r.group_ids & user.group_ids).mapped('code'))

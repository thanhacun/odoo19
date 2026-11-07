import base64
import hashlib
import logging
import re

from lxml import html as lxml_html

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

ROLE_BLOCK_XPATH = '//*[contains(concat(" ", normalize-space(@class), " "), " kderp-role ")]'


def _sha1(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()


class DocumentPageHistory(models.Model):
    _inherit = 'document.page.history'

    kderp_import_hash = fields.Char(
        'Imported version', readonly=True, copy=False,
        help='Set when this change came from the guide source (publish tool): hash of the imported HTML.')


class DocumentPage(models.Model):
    _inherit = 'document.page'

    sequence = fields.Integer(default=10, help='Order of the pages inside their parent (guide index).')
    kderp_key = fields.Char(
        'Guide key', index=True, copy=False,
        help='Fixed address of the page: /kderp/guide/<key>. Used by menus and the publish tool.')
    kderp_role_ids = fields.Many2many(
        'kderp.knowledge.role', 'kderp_knowledge_page_role_rel', 'page_id', 'role_id', string='Reader roles',
        help='Empty: everyone. Otherwise only users with one of these roles see the page.')
    kderp_managed = fields.Boolean(
        'Managed from guide source', readonly=True, copy=False,
        help='Published from documentation/guides in git. Edits made here are kept, but the next '
             'publish proposes the source version again: also change the source.')
    kderp_source_path = fields.Char('Source file', readonly=True, copy=False)
    kderp_source_hash = fields.Char('Source version', readonly=True, copy=False)
    kderp_content_view = fields.Html(
        'Page', compute='_compute_kderp_content_view', sanitize=False,
        help='Approved content with the blocks for other roles removed.')
    kderp_edited_after_import = fields.Boolean(
        'Edited in Odoo after publish', compute='_compute_kderp_edited_after_import')

    kderp_menu_id = fields.Many2one('ir.ui.menu', 'Guide menu', copy=False,
        help='Menu kept open (menu bar, app highlight) when this page and its sub-pages are read. '
         'Sub-pages inherit it from the nearest parent that has one.')

    @api.depends('name')
    def _compute_display_name(self):
        super(DocumentPage, self)._compute_display_name()
        if self.env.context.get('kderp_reader'):
            for page in self:
                page.display_name = page.name

    kderp_breadcrumb = fields.Html('Breadcrumb', compute='_compute_kderp_breadcrumb', sanitize=False)

    _kderp_key_unique = models.Constraint('unique(kderp_key)', 'Another page already uses this guide key.')

    def _kderp_menu(self):
        """Menu of the nearest ancestor (or this page) that has one, else the Knowledge app menu."""
        self.ensure_one()
        page = self
        while page:
            if page.kderp_menu_id:
                return page.kderp_menu_id
            page = page.parent_id
        return self.env.ref('document_knowledge.menu_document_root', raise_if_not_found=False)

    def _compute_kderp_breadcrumb(self):
        for page in self:
            menu = page._kderp_menu()
            parts, parent = [], page.parent_id
            while parent:
                parts.insert(0, '<a href="%s">%s</a>' % (
                    self._kderp_reader_url(parent, menu), html_escape(parent.name or '')))
                parent = parent.parent_id
            page.kderp_breadcrumb = ' / '.join(parts)

    # ------------------------------------------------------------------
    # Every page needs approval (decision 21 Oct 2026); default approvers: Knowledge reviewers
    # ------------------------------------------------------------------
    @api.depends('approval_required', 'parent_id.is_approval_required')
    def _compute_is_approval_required(self):
        for page in self:
            page.is_approval_required = True

    @api.depends('approver_gid', 'parent_id.approver_group_ids')
    def _compute_approver_group_ids(self):
        super(DocumentPage, self)._compute_approver_group_ids()
        reviewers = self.env.ref('kdvn_knowledge.group_knowledge_reviewer', raise_if_not_found=False)
        for page in self:
            if not page.approver_group_ids and reviewers:
                page.approver_group_ids = reviewers

    # ------------------------------------------------------------------
    # Reading: role blocks
    # ------------------------------------------------------------------
    @api.model
    def _kderp_filter_roles(self, html_text, codes):
        """Remove '<div class="kderp-role" data-roles="a b">' blocks whose roles the reader lacks."""
        if not html_text or 'kderp-role' not in html_text:
            return html_text
        try:
            root = lxml_html.fragment_fromstring(html_text, create_parent='div')
        except Exception:
            _logger.warning('Knowledge: could not parse page HTML for role blocks')
            return html_text
        for node in root.xpath(ROLE_BLOCK_XPATH):
            roles = set((node.get('data-roles') or '').split())
            if roles and not (roles & codes):
                node.getparent().remove(node)
        inner = (root.text or '') + ''.join(
            lxml_html.tostring(child, encoding='unicode') for child in root)
        return inner

    @api.depends('content', 'child_ids')
    def _compute_kderp_content_view(self):
        codes = self.env['kderp.knowledge.role'].user_role_codes()
        for page in self:
            if page.type == 'category':
                page.kderp_content_view = page._kderp_reader_index()
            else:
                page.kderp_content_view = page._kderp_filter_roles(page.content, codes)

    # @api.model
    # def _kderp_reader_url(self, page):
    #     menu = self.env.ref('document_knowledge.menu_document_root', raise_if_not_found=False)
    #     action = self.env.ref('kdvn_knowledge.action_guide_reader', raise_if_not_found=False)
    #     url = '/web#id=%s&model=document.page&view_type=form' % page.id
    #     if menu:
    #         url += '&menu_id=%s' % menu.id
    #     return url + ('&action=%s' % action.id if action else '')

    @api.model
    def _kderp_reader_url(self, page, menu=None):
        action = self.env.ref('kdvn_knowledge.action_guide_reader', raise_if_not_found=False)
        menu = menu or page._kderp_menu()
        url = '/web#id=%s&model=document.page&view_type=form' % page.id
        if action:
            url += '&action=%s' % action.id
        if menu:
            url += '&menu_id=%s' % menu.id
        return url

    # def _kderp_reader_index(self):
    #     """Category page: its sub-pages (only those the reader may see), as links to the reader."""
    #     self.ensure_one()

    #     def items(parent):
    #         children = self.search([('parent_id', '=', parent.id)], order='sequence, name')
    #         out = []
    #         for child in children:
    #             sub = items(child) if child.type == 'category' else ''
    #             out.append('<li><a href="%s">%s</a>%s</li>' % (
    #                 self._kderp_reader_url(child), html_escape(child.name or ''), sub))
    #         return '<ul>%s</ul>' % ''.join(out) if out else ''
    #     return items(self) or '<p class="text-muted">%s</p>' % html_escape(_('No pages yet.'))

    def _kderp_reader_index(self):
        """Category page: its sub-pages (only those the reader may see), as links to the reader."""
        self.ensure_one()
        menu = self._kderp_menu()

        def items(parent):
            children = self.search([('parent_id', '=', parent.id)], order='sequence, name')
            out = []
            for child in children:
                sub = items(child) if child.type == 'category' else ''
                out.append('<li><a href="%s">%s</a>%s</li>' % (
                    self._kderp_reader_url(child, menu), html_escape(child.name or ''), sub))
            return '<ul>%s</ul>' % ''.join(out) if out else ''

        return items(self) or '<p class="text-muted">%s</p>' % html_escape(_('No pages yet.'))

    def kderp_action_open_editor(self):
        """Open the page in the Knowledge editor form (propose a change, history, approvals)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'document.page',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('document_page.view_wiki_form').id, 'form')],
            'target': 'current',
        }

    def kderp_action_report_problem(self):
        """Message to the Knowledge reviewers, posted on the page, about a wrong or outdated page."""
        self.ensure_one()
        reviewers = self.env.ref('kdvn_knowledge.group_knowledge_reviewer').sudo().user_ids
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'document.page',
                'default_res_id': self.id,
                'default_composition_mode': 'comment',
                'default_subject': _('Problem on guide page: %s') % (self.name or ''),
                'default_partner_ids': [(6, 0, reviewers.mapped('partner_id').ids)],
            },
        }

    def _compute_kderp_edited_after_import(self):
        for page in self:
            head = page.history_head
            page.kderp_edited_after_import = bool(page.kderp_managed and head and not head.kderp_import_hash)

    @api.model
    def kderp_page_by_key(self, key):
        return self.search([('kderp_key', '=', key)], limit=1)

    # ------------------------------------------------------------------
    # Publishing from the guide source (documentation/guides/tools/publish.py, JSON-RPC)
    # ------------------------------------------------------------------
    @api.model
    def kderp_import_page(self, payload):
        """Create or update one guide page or category from the guide source.

        payload: {key, title, type ('content'|'category'), parent_key, sequence, roles: [codes],
                  html, source_path, source_hash, images: {name: base64}}
        Never overwrites: a changed page gets a new change request waiting for a reviewer.
        payload.replaces: old key(s) of a page that moved; renamed in place when the new key does not exist yet.
        Returns {'id', 'key', 'status': created|updated|unchanged, 'edited_in_odoo': bool, 'renamed_from': old key or ''}.
        """
        if not self.env.user.has_group('document_page.group_document_manager'):
            raise AccessError(_('Only Knowledge managers can publish guides.'))
        return self._kderp_import_page(payload)

    @api.model
    def _kderp_import_page(self, payload):
        """kderp_import_page without the permission check (used by the module guide loader)."""
        key = (payload.get('key') or '').strip()
        if not key:
            raise UserError(_('The guide key is missing.'))
        page_type = payload.get('type') or 'content'
        parent = self.kderp_page_by_key(payload['parent_key']) if payload.get('parent_key') else self.browse()
        if payload.get('parent_key') and not parent:
            raise UserError(_('Parent guide "%s" not found: publish it first.') % payload['parent_key'])
        roles = self.env['kderp.knowledge.role'].search([('code', 'in', payload.get('roles') or [])])
        meta = {
            'name': payload.get('title') or key,
            'parent_id': parent.id or False,
            'sequence': payload.get('sequence') or 10,
            'kderp_role_ids': [(6, 0, roles.ids)],
            'kderp_managed': True,
            'kderp_source_path': payload.get('source_path') or False,
        }
        page = self.with_context(active_test=False).kderp_page_by_key(key)
        renamed_from = ''
        if not page:
            # Moved in the source ("replaces: old/key"): rename the existing record, so its history, links and
            # attachments are kept; the usual update below then adds the new text as a change request.
            old = payload.get('replaces') or []
            for old_key in ([old] if isinstance(old, str) else old):
                old_page = self.with_context(active_test=False).kderp_page_by_key(old_key)
                if old_page and old_page.kderp_managed and old_page.type == page_type:
                    old_page.kderp_key = key
                    page, renamed_from = old_page, old_key
                    break
        History = self.env['document.page.history']

        # if page_type == 'category':
        #     if page:
        #         page.write(meta)
        #         return {'id': page.id, 'key': key, 'status': 'unchanged', 'edited_in_odoo': False}
        #     page = self.create(dict(meta, kderp_key=key, type='category', content='<p><br></p>'))
        #     return {'id': page.id, 'key': key, 'status': 'created', 'edited_in_odoo': False}

        if page_type == 'category':
            menu = self.env.ref(payload['menu_xmlid'], raise_if_not_found=False) \
                if payload.get('menu_xmlid') else False
            if menu:
                meta['kderp_menu_id'] = menu.id
            if page:
                page.write(meta)
                return {'id': page.id, 'key': key, 'status': 'unchanged', 'edited_in_odoo': False,
                        'renamed_from': renamed_from}
            page = self.create(dict(meta, kderp_key=key, type='category', content='<p><br></p>'))
            return {'id': page.id, 'key': key, 'status': 'created', 'edited_in_odoo': False}

        source_hash = payload.get('source_hash') or ''
        source_label = payload.get('source_path') or key
        if not page:
            # Images first (not yet linked), then the page: create() makes the first change request
            # through the OCA content inverse (pending approval), which we mark as imported.
            attachments, content = self._kderp_store_images(self.browse(), payload.get('html') or '',
                                                            payload.get('images') or {})
            page = self.create(dict(meta, kderp_key=key, type='content', content=content,
                                    kderp_source_hash=source_hash))
            attachments.write({'res_id': page.id})
            first = History.search([('page_id', '=', page.id)], order='id desc', limit=1)
            first.write({'name': payload.get('title') or key, 'kderp_import_hash': _sha1(content),
                         'summary': _('Published from the guide source (%s)') % source_label})
            return {'id': page.id, 'key': key, 'status': 'created', 'edited_in_odoo': False}

        page.write(meta)
        if page.kderp_source_hash == source_hash:
            return {'id': page.id, 'key': key, 'status': 'unchanged',
                    'edited_in_odoo': page.kderp_edited_after_import, 'renamed_from': renamed_from}

        _attachments, content = self._kderp_store_images(page, payload.get('html') or '',
                                                         payload.get('images') or {})
        # Older imported change requests still waiting are replaced by this one
        History.search([('page_id', '=', page.id), ('state', 'in', ('draft', 'to approve')),
                        ('kderp_import_hash', '!=', False)]).action_cancel()
        edited = page.kderp_edited_after_import
        summary = _('Published from the guide source (%s)') % source_label
        if edited:
            summary = _('CHECK BEFORE APPROVING: the page was edited in Odoo after the last publish; '
                        'approving this replaces those edits. ') + summary
        history = History.create({
            'page_id': page.id,
            'name': payload.get('title') or key,
            'summary': summary,
            'content': content,
            'kderp_import_hash': _sha1(content),
        })
        history.action_to_approve()
        page.kderp_source_hash = source_hash
        return {'id': page.id, 'key': key, 'status': 'updated', 'edited_in_odoo': edited,
                'renamed_from': renamed_from}

    @api.model
    def _kderp_store_images(self, page, content, images):
        """Store images as attachments of the page (reused when unchanged; not linked yet when the
        page is new) and point <img src="img/x.png"> to them. Returns (attachments, content)."""
        Attachment = self.env['ir.attachment']
        attachments = Attachment.browse()
        urls = {}
        for name, b64 in images.items():
            raw = base64.b64decode(b64)
            checksum = hashlib.sha1(raw).hexdigest()
            fname = name.split('/')[-1]
            att = Attachment.browse()
            if page:
                att = Attachment.search([('res_model', '=', 'document.page'), ('res_id', '=', page.id),
                                         ('name', '=', fname), ('checksum', '=', checksum)], limit=1)
            if not att:
                att = Attachment.create({
                    'name': fname, 'datas': b64,
                    'res_model': 'document.page', 'res_id': page.id or False,
                })
            attachments |= att
            urls[name] = '/web/content/%s/%s' % (att.id, fname)

        def repl(match):
            src = match.group(2)
            return '%s%s%s' % (match.group(1), urls.get(src, src), match.group(3))
        return attachments, re.sub(r'(<img[^>]*\ssrc=")([^"]+)(")', repl, content)

    def kderp_action_open_reader(self):
        """Window action that opens this page in the reader form."""
        self.ensure_one()
        # plain users may not read ir.actions.act_window records (Odoo 19): the reader action is public data
        action = self.env.ref('kdvn_knowledge.action_guide_reader').sudo().read()[0]
        action['res_id'] = self.id
        return action

    @api.model
    def kderp_action_open_guide(self, key):
        """Used by menus (server actions): open the guide page with this key inside the web client."""
        page = self.kderp_page_by_key(key)
        if not page:
            raise UserError(_('No guide page "%s" (yet).') % key)
        return page.kderp_action_open_reader()

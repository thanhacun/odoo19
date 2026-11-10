"""E-approval data of the Odoo 12 procedures (kderp_e_approval): requests, their tier reviews, chatter, followers and attachments.

Steps (added when kdvn_e_approval and a procedure module are installed): ea_requests, ea_reviews, ea_chatter, ea_attachments, ea_check.
Procedures covered: every model in EA_MODELS that exists in Odoo 19 (an Odoo 12 table with no rows is simply skipped).

Rules
- Stored Odoo 12 values are copied as they are (state, approval progress, review status and reviewers): nothing is recomputed, nothing is
  re-requested, nobody is notified (no tracking, no mail, no activities, no n8n / Talk: the importer only creates and updates rows).
- `state` of a request is never written through the ORM: the tier validation engine reacts to it (it would open or validate reviews).
  It is written with SQL together with the author / dates; the other fields go through the ORM with skip_validation_check.
- Tier definitions: Odoo 12 definition -> Odoo 19 definition with the same xml id (module kderp_x renamed kdvn_x), else the same model + name.
  The definitions themselves are shipped by the procedure modules (data/*_tier_definitions.xml) and are not imported.
- Messages, tracking values and attachments never change in Odoo 12: imported once (external id legacy12.<table>_<id>), then skipped.
- Window: a request is reloaded when it was created or changed since date_from, or is not decided yet (draft / submitted); a full run reloads all.
- Attachment files come from the extracted Odoo 12 filestore (parameter kdvn_legacy.filestore, made by tools/legacy_nightly.sh from the HN
  `<db>-daily.filestore.tgz`). A file that is not there is counted ('file missing') and the attachment is skipped; it is picked up the night it arrives.
- Odoo 12 followers are subscribed with the default subtypes of Odoo 19 (their own subtype choice is not copied).
"""
import base64
import logging
import os

from odoo import models

from .legacy_import import TAG_MODULE

_logger = logging.getLogger(__name__)

PARAM_FILESTORE = 'kdvn_legacy.filestore'
DEFAULT_FILESTORE = '/home/odoo/project/temp/legacy_filestore'
# Procedure models of the mixin kderp.e.approval.mixin. Models with a one2many to child rows (safety.tool.request lines) are NOT here yet.
EA_MODELS = ('entertainment.request', 'kderp.project.peak.time', 'staff.transfer')
OPEN_STATES = "state NOT IN ('approved', 'rejected')"
SKIP_FIELDS = {'id', 'create_uid', 'write_uid', 'create_date', 'write_date', 'message_main_attachment_id', 'company_id', 'state', 'attachment_ids'}
# Odoo 12 models that hold their rows in a remote cache keyed by external_id (the Odoo 19 caches were filled by the remote sync, ids differ)
CACHE_MODELS = ('kderp.job.lookup', 'kderp.customer.cache', 'kderp.job.budget.cache')
MAPPED_TABLES = {'hr.employee': 'hr_employee', 'hr.employee.public': 'hr_employee', 'hr.department': 'hr_department', 'res.users': 'res_users'}
TRACKING_COLUMNS = ('old_value_integer', 'old_value_float', 'old_value_char', 'old_value_text', 'old_value_datetime',
                    'new_value_integer', 'new_value_float', 'new_value_char', 'new_value_text', 'new_value_datetime')


def _in(ids):
    """Only integers go into SQL."""
    return '(%s)' % ', '.join(str(int(i)) for i in ids) if ids else '(NULL)'


class KdvnLegacyImportEApproval(models.AbstractModel):
    _inherit = 'kdvn.legacy.import'

    @property
    def _PRUNE_TABLES(self):   # noqa: N802 - the base class has it as a class attribute
        tables = super()._PRUNE_TABLES
        models_ = self._ea_models()
        if not models_:
            return tables
        quoted = ', '.join("'%s'" % m for m in models_)
        extra = [('tier_review', 'tier.review', 'model IN (%s)' % quoted),
                 ('mail_message', 'mail.message', 'model IN (%s)' % quoted),
                 ('ir_attachment', 'ir.attachment', "res_model IN (%s) AND res_field IS NULL AND type = 'binary'" % quoted)]
        extra += [(self.env[m]._table, m, None) for m in models_]
        return tuple(extra) + tuple(tables)   # the children (reviews, messages, files) go before their requests

    def _import_steps(self):
        steps = super()._import_steps()
        if not self._ea_models():
            return steps
        mine = [('ea_requests', self._step_ea_requests), ('ea_reviews', self._step_ea_reviews), ('ea_chatter', self._step_ea_chatter),
                ('ea_attachments', self._step_ea_attachments)]
        names = [name for name, _method in steps]
        at = names.index('prune') if 'prune' in names else len(steps)
        steps = steps[:at] + mine + steps[at:]
        return steps + [('ea_check', self._step_ea_check)]

    def _ea_models(self):
        if 'tier.review' not in self.env or 'kderp.e.approval.mixin' not in self.env:
            return []
        return [m for m in EA_MODELS if m in self.env]

    def _ea_ctx(self):
        """Context of the writes: nothing recomputed, nothing notified, the tier validation engine does not interfere."""
        return self.with_context(kdvn_no_compute=True, skip_validation_check=True, tracking_disable=True, mail_notrack=True, mail_create_nolog=True,
                                 mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True, kdvn_legacy_import=True,
                                 skip_distance=True)   # staff transfer: no map service call, the Odoo 12 distances are copied

    # ------------------------------------------------------------------ mapping helpers
    def _ea_user(self, legacy_id):
        return self._state['tags'].get(('res_users', legacy_id)) if legacy_id else False

    def _ea_partner(self, legacy_partner_id):
        """Odoo 12 partner -> Odoo 19 partner of the same user (staff are the only authors we can match); False when it is nobody we know."""
        cache = self._state.setdefault('ea_partners', None)
        if cache is None:
            cache = self._state['ea_partners'] = {}
            users = {r['id']: r['partner_id'] for r in self._legacy_rows('res_users', ['id', 'partner_id']) if r['partner_id']}
            for legacy_uid, legacy_pid in users.items():
                uid = self._ea_user(legacy_uid)
                if uid:
                    cache[legacy_pid] = self.env['res.users'].browse(uid).partner_id.id
            root = self._legacy_rows('ir_model_data', ['res_id'], "module = 'base' AND name = 'partner_root' AND model = 'res.partner'")
            if root:
                odoobot = self.env.ref('base.partner_root', raise_if_not_found=False)
                if odoobot:
                    cache[root[0]['res_id']] = odoobot.id
        return cache.get(legacy_partner_id) or False

    def _ea_cache_row(self, comodel, legacy_id):
        """kderp.job.lookup / customer.cache / job.budget.cache: by external_id (the Odoo 19 rows come from the remote sync)."""
        if not legacy_id:
            return False
        maps = self._state.setdefault('ea_cache', {})
        if comodel not in maps:
            Model = self.env[comodel]
            legacy = {r['id']: r['external_id'] for r in self._legacy_rows(Model._table, ['id', 'external_id'])}
            here = {r['external_id']: r['id'] for r in Model.with_context(active_test=False).search_read([('external_id', '!=', False)], ['external_id'])}
            maps[comodel] = {lid: here.get(ext) for lid, ext in legacy.items()}
        return maps[comodel].get(legacy_id) or False

    def _ea_map(self, comodel, legacy_id):
        """Odoo 12 id of a record of `comodel` -> Odoo 19 id (False when we cannot tell)."""
        if legacy_id is None:
            return False
        if comodel in MAPPED_TABLES:
            return self._state['tags'].get((MAPPED_TABLES[comodel], legacy_id)) or False
        if comodel == 'res.partner':
            return self._ea_partner(legacy_id)
        if comodel in CACHE_MODELS:
            return self._ea_cache_row(comodel, legacy_id)
        return False

    def _ea_definition(self, legacy_id):
        """Odoo 12 tier definition -> Odoo 19 tier definition (same xml id with kderp_ -> kdvn_, else same model and name)."""
        maps = self._state.get('ea_defs')
        if maps is None:
            maps = self._state['ea_defs'] = {}
            xmlids = {r['res_id']: r for r in self._legacy_rows('ir_model_data', ['module', 'name', 'res_id'], "model = 'tier.definition'")}
            models_ = {r['id']: r['model'] for r in self._legacy_rows('ir_model', ['id', 'model'])}
            Definition = self.env['tier.definition'].with_context(active_test=False)
            for row in self._legacy_rows('tier_definition', ['id', 'name', 'model_id']):
                found = Definition
                xml = xmlids.get(row['id'])
                if xml:
                    module = xml['module'].replace('kderp_', 'kdvn_', 1)
                    found = self.env.ref('%s.%s' % (module, xml['name']), raise_if_not_found=False) or found
                if not found:
                    found = Definition.search([('model', '=', models_.get(row['model_id'])), ('name', '=', row['name'])], limit=1)
                maps[row['id']] = found.id if found else False
        return maps.get(legacy_id) or False

    # ------------------------------------------------------------------ what to load
    def _ea_where(self):
        """Requests to reload: touched since date_from or still open (full run: everything)."""
        date_from = self._state['options'].get('date_from')
        if not date_from:
            return None
        from .legacy_import_attendance import _iso
        d = _iso(date_from)
        return "create_date >= '%s' OR write_date >= '%s' OR %s" % (d, d, OPEN_STATES)

    def _ea_selected(self, model):
        """{legacy id: row} of the requests of this procedure that this run loads."""
        table = self.env[model]._table
        selected = self._state.setdefault('ea_selected', {})
        if model not in selected:
            selected[model] = {r['id']: r for r in self._legacy_rows(table, None, self._ea_where())}
        return selected[model]

    def _ea_stamp(self, table, res_id, row):
        """Odoo 12 author and dates (the ORM stamps the superuser and now)."""
        sets, args = [], []
        for column in ('create_date', 'write_date'):
            if row.get(column):
                sets.append('%s = %%s' % column)
                args.append(row[column])
        for column in ('create_uid', 'write_uid'):
            uid = self._ea_user(row.get(column))
            if uid:
                sets.append('%s = %%s' % column)
                args.append(uid)
        if sets:
            self.env.cr.execute('UPDATE "%s" SET %s WHERE id = %%s' % (table, ', '.join(sets)), args + [res_id])

    # ------------------------------------------------------------------ requests
    def _step_ea_requests(self):
        self = self._ea_ctx()
        for model in self._ea_models():
            Model = self.env[model]
            rows = self._ea_selected(model)
            if not rows:
                continue
            m2m = self._ea_many2many(model, set(rows))
            for lid, row in rows.items():
                self._safe(Model._table, lid, row.get('name') or '', lambda: self._ea_one_request(model, row, m2m.get(lid, {})))

    def _ea_many2many(self, model, ids):
        """{legacy request id: {field name: [Odoo 19 ids]}} for the plain many2many fields (not the attachments: they come later)."""
        out = {}
        for name, field in self.env[model]._fields.items():
            if field.type != 'many2many' or not field.store or field.related or name in SKIP_FIELDS or field.comodel_name == 'ir.attachment':
                continue
            columns = self._legacy_columns(field.relation)
            if not {field.column1, field.column2} <= columns:
                continue
            for rel in self._legacy_rows(field.relation, [field.column1, field.column2], '%s IN %s' % (field.column1, _in(ids))):
                target = self._ea_map(field.comodel_name, rel[field.column2]) if field.comodel_name != model else False
                if target:
                    out.setdefault(rel[field.column1], {}).setdefault(name, []).append(target)
        return out

    def _ea_one_request(self, model, row, m2m):
        Model = self.env[model]
        vals = {}
        for name, field in Model._fields.items():
            if name in SKIP_FIELDS or name not in row or not field.store or field.related or field.type in ('one2many', 'many2many', 'binary', 'image'):
                continue
            value = row[name]
            if field.type == 'many2one':
                value = self._ea_map(field.comodel_name, value)
                if not value and row[name]:
                    self._state['stats'][(Model._table, 'unmapped %s' % name)] += 1
            vals[name] = value
        for name, ids in m2m.items():
            vals[name] = [(6, 0, ids)]
        # staff.transfer: Odoo 12 before 12.0.1.7.0 has ONE staff in the column transfer_employee_id (several staff since then, relation table
        # staff_transfer_employee_rel, read above). Both shapes must load until Odoo 12 is migrated.
        if 'transfer_employee_ids' in Model._fields and not vals.get('transfer_employee_ids') and row.get('transfer_employee_id'):
            staff = self._ea_map('hr.employee', row['transfer_employee_id'])
            if staff:
                vals['transfer_employee_ids'] = [(6, 0, [staff])]
            else:
                self._state['stats'][(Model._table, 'unmapped transfer_employee_id')] += 1
        record = self._upsert(model, Model._table, row['id'], vals)
        self.env.cr.execute('UPDATE "%s" SET state = %%s WHERE id = %%s' % Model._table, (row['state'], record.id))
        self._ea_stamp(Model._table, record.id, row)
        record.invalidate_recordset()
        return record

    # ------------------------------------------------------------------ tier reviews
    def _step_ea_reviews(self):
        self = self._ea_ctx()
        models_ = self._ea_models()
        for model in models_:
            table = self.env[model]._table
            ids = set(self._ea_selected(model))
            if not ids:
                continue
            rows = self._legacy_rows('tier_review', None, "model = '%s' AND res_id IN %s" % (model, _in(ids)))
            reviewers = {}
            for rel in self._legacy_rows('res_users_tier_review_rel', ['tier_review_id', 'res_users_id'],
                                         'tier_review_id IN %s' % _in([r['id'] for r in rows])):
                uid = self._ea_user(rel['res_users_id'])
                if uid:
                    reviewers.setdefault(rel['tier_review_id'], []).append(uid)
            for row in rows:
                self._safe('tier_review', row['id'], '%s %s' % (model, row['res_id']), lambda: self._ea_one_review(model, table, row, reviewers))
            # validation_status (stored on the request) is a plain function of the review statuses: let Odoo compute it now that the reviews are there
            res_ids = [self._state['tags'][(table, lid)] for lid in ids if self._state['tags'].get((table, lid))]
            Model = self.env[model]
            self.env.add_to_compute(Model._fields['validation_status'], Model.browse(res_ids))

    def _ea_one_review(self, model, table, row, reviewers):
        res_id = self._state['tags'].get((table, row['res_id']))
        definition = self._ea_definition(row['definition_id'])
        if not res_id:
            self._state['stats'][('tier_review', 'skipped: request not imported')] += 1
            return
        if not definition:
            raise ValueError('no Odoo 19 tier definition for the Odoo 12 definition %s' % row['definition_id'])
        vals = {'status': row['status'], 'model': model, 'res_id': res_id, 'definition_id': definition, 'sequence': row['sequence'],
                'done_by': self._ea_user(row['done_by']), 'requested_by': self._ea_user(row['requested_by']),
                'reviewed_date': row['reviewed_date'], 'comment': row['comment'] or False}
        review = self._upsert('tier.review', 'tier_review', row['id'], vals)
        # stored computed fields: the Odoo 12 values (todo_by, can_review, reviewers), not what the Odoo 19 rules would resolve today
        cr = self.env.cr
        cr.execute('UPDATE tier_review SET todo_by = %s, can_review = %s WHERE id = %s', (row['todo_by'], bool(row['can_review']), review.id))
        cr.execute('DELETE FROM res_users_tier_review_rel WHERE tier_review_id = %s', (review.id,))
        for uid in set(reviewers.get(row['id'], [])):
            cr.execute('INSERT INTO res_users_tier_review_rel (tier_review_id, res_users_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (review.id, uid))
        self._ea_stamp('tier_review', review.id, row)
        review.invalidate_recordset()

    # ------------------------------------------------------------------ chatter
    def _step_ea_chatter(self):
        self = self._ea_ctx()
        subtypes = {}
        xmlids = {r['res_id']: r for r in self._legacy_rows('ir_model_data', ['module', 'name', 'res_id'], "model = 'mail.message.subtype'")}
        note = self.env.ref('mail.mt_note')
        for sid, xml in xmlids.items():
            subtype = self.env.ref('%s.%s' % (xml['module'], xml['name']), raise_if_not_found=False)
            subtypes[sid] = subtype.id if subtype else note.id
        for model in self._ea_models():
            table = self.env[model]._table
            ids = set(self._ea_selected(model))
            if not ids:
                continue
            messages = self._legacy_rows('mail_message', None, "model = '%s' AND res_id IN %s" % (model, _in(ids)))
            tracking = {}
            for row in self._legacy_rows('mail_tracking_value', None, 'mail_message_id IN %s' % _in([m['id'] for m in messages])):
                tracking.setdefault(row['mail_message_id'], []).append(row)
            for msg in messages:
                if self._state['tags'].get(('mail_message', msg['id'])):
                    continue   # messages never change
                self._safe('mail_message', msg['id'], '%s %s' % (model, msg['res_id']),
                           lambda: self._ea_one_message(model, table, msg, subtypes, note.id, tracking.get(msg['id'], [])))
            followers = {}
            for row in self._legacy_rows('mail_followers', ['res_id', 'partner_id'], "res_model = '%s' AND res_id IN %s" % (model, _in(ids))):
                partner = self._ea_partner(row['partner_id'])
                if partner:
                    followers.setdefault(row['res_id'], set()).add(partner)
            for lid, partners in followers.items():
                res_id = self._state['tags'].get((table, lid))
                if res_id:
                    self.env[model].browse(res_id).message_subscribe(partner_ids=sorted(partners))
                    self._state['stats'][('mail_followers', 'subscribed')] += len(partners)

    def _ea_one_message(self, model, table, msg, subtypes, note_id, tracking_rows):
        res_id = self._state['tags'].get((table, msg['res_id']))
        if not res_id:
            self._state['stats'][('mail_message', 'skipped: request not imported')] += 1
            return
        vals = {'model': model, 'res_id': res_id, 'message_type': msg['message_type'] or 'notification', 'subtype_id': subtypes.get(msg['subtype_id'], note_id),
                'body': msg['body'] or '', 'subject': msg['subject'] or False, 'author_id': self._ea_partner(msg['author_id']),
                'email_from': msg['email_from'] or False, 'date': msg['date'], 'record_name': msg['record_name'] or False}
        message = self._upsert('mail.message', 'mail_message', msg['id'], vals)
        self._ea_stamp('mail_message', message.id, msg)
        for tv in tracking_rows:
            field = self.env['ir.model.fields']._get(model, tv['field'])
            if not field:
                self._state['stats'][('mail_tracking_value', 'field not in Odoo 19')] += 1
                continue
            tvals = {'field_id': field.id, 'mail_message_id': message.id}
            tvals.update({c: tv[c] for c in TRACKING_COLUMNS if tv.get(c) not in (None, False)})
            self._upsert('mail.tracking.value', 'mail_tracking_value', tv['id'], tvals)

    # ------------------------------------------------------------------ attachments
    def _ea_filestore_path(self, store_fname):
        root = self._state.get('ea_filestore_root')
        if root is None:
            base = self.env['ir.config_parameter'].sudo().get_param(PARAM_FILESTORE, DEFAULT_FILESTORE)
            root = False
            if os.path.isdir(base):
                for candidate in [base] + sorted(os.path.join(base, d) for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))):
                    if os.path.isdir(os.path.join(candidate, store_fname.split('/')[0])):
                        root = candidate
                        break
            self._state['ea_filestore_root'] = root
        path = os.path.join(root, store_fname) if root else False
        return path if path and os.path.isfile(path) else False

    def _step_ea_attachments(self):
        self = self._ea_ctx()
        for model in self._ea_models():
            table = self.env[model]._table
            ids = set(self._ea_selected(model))
            if not ids:
                continue
            # the request's own list of supporting attachments (many2many): files uploaded before the first save have res_id 0 in Odoo 12
            field = self.env[model]._fields.get('attachment_ids')
            links = {}   # legacy attachment id -> legacy request id
            if field and field.type == 'many2many' and {field.column1, field.column2} <= self._legacy_columns(field.relation):
                for rel in self._legacy_rows(field.relation, [field.column1, field.column2], '%s IN %s' % (field.column1, _in(ids))):
                    links[rel[field.column2]] = rel[field.column1]
            where = "type = 'binary' AND res_field IS NULL AND ((res_model = '%s' AND res_id IN %s) OR id IN %s)" % (model, _in(ids), _in(links))
            for row in self._legacy_rows('ir_attachment', None, where):
                if self._state['tags'].get(('ir_attachment', row['id'])):
                    continue   # files never change
                owner = row['res_id'] if row['res_model'] == model and row['res_id'] in ids else links.get(row['id'])
                self._safe('ir_attachment', row['id'], '%s %s' % (model, owner), lambda: self._ea_one_attachment(model, table, row, owner))
            wanted = {}
            for att, owner in links.items():
                target = self._state['tags'].get(('ir_attachment', att))
                if target:
                    wanted.setdefault(owner, set()).add(target)
            for lid, targets in wanted.items():
                res_id = self._state['tags'].get((table, lid))
                record = self.env[model].browse(res_id).exists() if res_id else False
                if record and set(record.attachment_ids.ids) != targets:
                    record.write({'attachment_ids': [(6, 0, sorted(targets))]})

    def _ea_one_attachment(self, model, table, row, owner):
        res_id = self._state['tags'].get((table, owner))
        if not res_id:
            self._state['stats'][('ir_attachment', 'skipped: request not imported')] += 1
            return
        data = False
        if row['store_fname']:
            path = self._ea_filestore_path(row['store_fname'])
            if not path:
                self._state['stats'][('ir_attachment', 'file missing')] += 1
                return
            with open(path, 'rb') as handle:
                data = base64.b64encode(handle.read())
        elif row['db_datas']:
            data = base64.b64encode(bytes(row['db_datas']))
        else:
            self._state['stats'][('ir_attachment', 'no content in Odoo 12')] += 1
            return
        vals = {'name': row['name'], 'res_model': model, 'res_id': res_id, 'mimetype': row['mimetype'] or False, 'description': row['description'] or False,
                'type': 'binary', 'datas': data}
        attachment = self.env['ir.attachment'].create(vals)
        self._tag(attachment, 'ir_attachment', row['id'])
        self._state['stats'][('ir_attachment', 'created')] += 1
        self._ea_stamp('ir_attachment', attachment.id, row)

    # ------------------------------------------------------------------ check
    def _step_ea_check(self):
        """Compare what we loaded with Odoo 12 (state of every request and the status of its reviews). A difference is a problem in the log."""
        for model in self._ea_models():
            table = self.env[model]._table
            rows = self._ea_selected(model)
            if not rows:
                continue
            tag_ids = {lid: self._state['tags'].get((table, lid)) for lid in rows}
            legacy_reviews = {}
            for r in self._legacy_rows('tier_review', ['id', 'res_id', 'status', 'definition_id'], "model = '%s' AND res_id IN %s" % (model, _in(rows))):
                legacy_reviews.setdefault(r['res_id'], []).append((r['sequence'] if 'sequence' in r else 0, r['status']))
            self.env.cr.execute('SELECT res_id, status FROM tier_review WHERE model = %s AND res_id = ANY(%s)', (model, [i for i in tag_ids.values() if i]))
            here = {}
            for res_id, status in self.env.cr.fetchall():
                here.setdefault(res_id, []).append(status)
            self.env.cr.execute('SELECT id, state FROM "%s" WHERE id = ANY(%%s)' % table, ([i for i in tag_ids.values() if i],))
            states = dict(self.env.cr.fetchall())
            differs = 0
            for lid, row in rows.items():
                rid = tag_ids[lid]
                if not rid:
                    differs += 1
                    continue
                want = sorted(s for _seq, s in legacy_reviews.get(lid, []))
                if states.get(rid) != row['state'] or sorted(here.get(rid, [])) != want:
                    differs += 1
                    self._state['errors'].append('e-approval check %s %s (%s): Odoo 12 state %s reviews %s, Odoo 19 state %s reviews %s'
                                                 % (table, lid, row.get('name'), row['state'], want, states.get(rid), sorted(here.get(rid, []))))
            self._state['stats'][(table, 'check: requests compared')] += len(rows)
            self._state['stats'][(table, 'check: differ')] += differs

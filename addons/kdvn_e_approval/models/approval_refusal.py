import html
import re
from collections import defaultdict

from odoo import api, fields, models, _


class KderpApprovalRefusal(models.Model):
    """One refusal of an approval request: who refused, when, the comment, and later who reset the request to draft.

    Why: the comment of a refusal lives in the review, and the reviews are deleted when the request goes back to draft
    (base_tier_validation write()). Managers want it to stay as a reminder, so it is copied here when the request is refused
    and completed when it is reset. Written only by the mixin (sudo); only E-Approval admins read the list, everybody who can open
    the request sees the note in its ribbon."""
    _name = 'kderp.approval.refusal'
    _description = 'Refusal of an approval request (kept after the reset to draft)'
    _order = 'refused_date desc, id desc'

    res_model = fields.Char(required=True, index=True, readonly=True)
    res_id = fields.Integer(required=True, index=True, readonly=True)
    record_name = fields.Char('Request', readonly=True)
    procedure = fields.Char('Procedure', readonly=True)
    review_id = fields.Integer('Review id', readonly=True, index=True, help="tier.review that was refused: stops a refusal being logged twice.")
    step = fields.Char('Step', readonly=True)
    refused_by_id = fields.Many2one('res.users', 'Refused by', readonly=True)
    refused_by_name = fields.Char('Refused by (name)', readonly=True, help="The name as written at the time: kept when the user cannot be found.")
    refused_date = fields.Datetime('Refused on', readonly=True)
    comment = fields.Text('Comment', readonly=True)
    state = fields.Selection([('refused', 'Still refused'), ('reset', 'Reset to draft')], default='refused', required=True, readonly=True)
    reset_by_id = fields.Many2one('res.users', 'Reset by', readonly=True)
    reset_date = fields.Datetime('Reset on', readonly=True)
    reset_to = fields.Char('Reset to', readonly=True)

    def action_open_request(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                'view_mode': 'form', 'target': 'current'}

    # ------------------------------------------------------------------ old refusals (before this log existed)
    # OCA base_tier_validation posts "A review was rejected by <name>. (<comment>)" on the request when a reviewer refuses, and
    # our reset action posted "unlocked and reset to Draft" afterwards. Both are still in the chatter: the log is rebuilt from them.
    _REJECT_RE = re.compile(r'^A review was rejected by (?P<who>.+?)\.(?: \((?P<comment>.*)\))?$', re.S)

    @api.model
    def _parse_rejection(self, body):
        """(name, comment) from the chatter text of a refusal, or None when it does not look like one."""
        text = html.unescape(re.sub(r'<[^>]+>', '', body or '')).strip()
        m = self._REJECT_RE.match(text)
        if not m:
            return None
        return m.group('who').strip(), (m.group('comment') or '').strip()

    @api.model
    def backfill_from_chatter(self, dry_run=True, records=None):
        """Rebuild the refusal log from the chatter of the requests. Dry run by default: only counts and describes.

        - one row per "A review was rejected by ..." message; the comment is the text in brackets;
        - reset: the first "unlocked and reset to Draft" message after it (before the next refusal) gives who and when;
        - still refused: the last refusal of a request that is in the refused state now and was not reset;
        - a refusal already in the log (same person, within 3 minutes: the exact one taken from a live review) is not added again,
          and a row made here is recognised next time by its message id (`review_id` = -message id): safe to run twice.
        `records` (optional recordset of requests) limits it to those requests.
        Returns a report dict."""
        Msg = self.env['mail.message'].sudo()
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        models_ = sorted(self.env.registry['kderp.e.approval.mixin']._inherit_children)
        refusals, resets = defaultdict(list), defaultdict(list)
        scope = [('model', '=', records._name), ('res_id', 'in', records.ids)] if records else [('model', 'in', models_)]
        for m in Msg.search(scope + [('body', 'ilike', 'A review was rejected by')], order='id'):
            refusals[(m.model, m.res_id)].append(m)
        for m in Msg.search(scope + [('body', 'ilike', 'unlocked and reset to Draft')], order='id'):
            resets[(m.model, m.res_id)].append(m)
        report = {'dry_run': dry_run, 'messages': 0, 'created': 0, 'already_logged': 0, 'not_a_refusal': 0, 'request_deleted': 0,
                  'still_refused': 0, 'reset': 0, 'lines': []}
        user_cache = {}

        def user_of_partner(partner):                     # OdooBot's user is inactive: Users already searches inactive ones too
            if partner and ('p', partner.id) not in user_cache:
                user_cache[('p', partner.id)] = Users.search([('partner_id', '=', partner.id)], limit=1).id
            return partner and user_cache[('p', partner.id)] or False

        def user_by_name(name):
            if name not in user_cache:
                found = Users.search([('name', '=', name)])
                user_cache[name] = found.id if len(found) == 1 else False
            return user_cache[name]

        for (model, res_id), msgs in sorted(refusals.items()):
            rec = self.env[model].sudo().browse(res_id).exists()
            if not rec:
                report['request_deleted'] += len(msgs)
                continue
            state_field = getattr(rec, '_state_field', 'state')
            reject_state = rec._get_validation_target_states()[1]
            if not dry_run:
                rec._refusal_log()                      # the exact rows of a request that is refused right now (live reviews)
            known = [(r.review_id, (r.refused_by_name or r.refused_by_id.name or '').lower(), r.refused_date)
                     for r in self.sudo().search([('res_model', '=', model), ('res_id', '=', res_id)])]
            if dry_run:                                 # what the live reviews would add
                known += [(r.id, (r.done_by.name or '').lower(), r.reviewed_date) for r in rec.review_ids.filtered(lambda r: r.status == 'rejected')]
            for i, m in enumerate(msgs):
                report['messages'] += 1
                parsed = self._parse_rejection(m.body)
                if not parsed:
                    report['not_a_refusal'] += 1
                    continue
                who, comment = parsed
                # same message id = made here before; same person at nearly the same time = the exact row of a live review (positive id)
                if any(k[0] == -m.id or (k[0] > 0 and k[1] == who.lower() and k[2] and abs((k[2] - m.date).total_seconds()) < 180) for k in known):
                    report['already_logged'] += 1
                    continue
                next_id = msgs[i + 1].id if i + 1 < len(msgs) else None
                reset = next((r for r in resets[(model, res_id)] if r.id > m.id and (next_id is None or r.id < next_id)), None)
                still = i == len(msgs) - 1 and rec[state_field] == reject_state and not reset
                vals = {'res_model': model, 'res_id': res_id, 'record_name': rec.display_name, 'procedure': rec._description or model,
                        'review_id': -m.id, 'step': False, 'refused_by_id': user_by_name(who), 'refused_by_name': who,
                        'refused_date': m.date, 'comment': comment or False, 'state': 'refused' if still else 'reset'}
                if not still:
                    vals.update(reset_to=_('Draft'), reset_date=reset.date if reset else False,
                                reset_by_id=user_of_partner(reset.author_id) if reset else False)
                report['still_refused' if still else 'reset'] += 1
                report['lines'].append('%s | %s | %s | %s | %s' % (
                    rec.display_name, m.date.strftime('%d/%m/%Y'), who, (comment or _('(no comment)')).replace('\n', ' ')[:60],
                    _('still refused') if still else (_('reset by %s on %s') % (reset.author_id.name, reset.date.strftime('%d/%m/%Y')) if reset else _('reset (not recorded who/when)'))))
                if not dry_run:
                    self.sudo().create(vals)
                    known.append((-m.id, who.lower(), m.date))
                report['created'] += 1
        return report

    @api.model
    def action_backfill(self, apply=False):
        """Menu action: preview (apply=False) or import (apply=True) of the old refusals, with a short report."""
        rep = self.backfill_from_chatter(dry_run=not apply)
        head = _("Old refusals read from the chatter: %(n)d message(s).") % {'n': rep['messages']}
        body = [head,
                (_("Added: %(c)d (%(r)d reset to draft, %(s)d still refused).") if apply else
                 _("Would be added: %(c)d (%(r)d reset to draft, %(s)d still refused).")) % {'c': rep['created'], 'r': rep['reset'], 's': rep['still_refused']},
                _("Already in the log: %d. Not a refusal text: %d. Request deleted: %d.") % (rep['already_logged'], rep['not_a_refusal'], rep['request_deleted'])]
        if rep['lines']:
            body += ['', _("Request | refused on | by | comment | what happened")] + rep['lines'][:25]
            if len(rep['lines']) > 25:
                body.append(_('... and %d more') % (len(rep['lines']) - 25))
        if not apply:
            body += ['', _("Nothing was written. To import, use the menu \"Import old refusals (apply)\".")]
        return self.env['kderp.notification.wizard'].show_notification_wizard(
            title=_("Old refusals: import") if apply else _("Old refusals: preview"), message='\n'.join(body), show_cancel=False)

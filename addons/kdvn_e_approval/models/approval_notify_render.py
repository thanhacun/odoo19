"""
Formatting for E-Approval notifications (email HTML and Nextcloud Talk text).

Pure functions: they take plain dicts and strings and return text, with no
database access, so the look can be changed and previewed on its own.
Colours are the same as the workflow ribbon (approval_ribbon.scss).

An "item" (one request waiting for one reviewer) is a dict with:
  ref, title, category, applicant, step_label, step_no, step_total,
  details_html, details_text, emergency (bool), odoo_url, approve_url,
  reject_url, files_attached [names], files_linked [(name, url)],
  special [reasons] (empty unless the request is a special case)
"""
from odoo.tools import html_escape

DONE = '#28a745'
CURRENT = '#7C7BAD'
REJECTED = '#dc3545'
MUTED = '#6c757d'
LINE = '#dee2e6'
TEXT = '#212529'
TEXT_SOFT = '#495057'
BG = '#f4f5f7'
# Kinden Vietnam company colour: $o-community-color in
# kderp_web_theme/static/src/scss/override_primary_variables.scss (emails can't use SCSS)
KDVN = '#01622f'
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif"

BRAND = 'Kinden Vietnam · E-Approval'
FOOTER = "Automatic message from Kinden ERP."
FOOTER_REVIEWER = ("Automatic message from Kinden ERP. The Approve and Reject buttons are "
                   "personal to you, so please don't forward this email.")


def _e(value):
    return html_escape(value or '')


# ---------------------------------------------------------------------------
# Email building blocks
# ---------------------------------------------------------------------------
def email_shell(title, body_html, accent=CURRENT, preheader='', footer=FOOTER):
    """White card on a light grey page, coloured top bar, brand line, title."""
    return (
        '<div style="background:%(bg)s;padding:24px 12px;font-family:%(font)s;color:%(text)s;">'
        '<div style="display:none;max-height:0;overflow:hidden;">%(pre)s</div>'
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid %(line)s;'
        'border-radius:6px;border-collapse:separate;">'
        '<tr><td style="height:4px;background:%(accent)s;border-radius:6px 6px 0 0;'
        'font-size:0;line-height:0;">&nbsp;</td></tr>'
        '<tr><td style="padding:20px 24px 4px;">'
        '<div style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:%(muted)s;">%(brand)s</div>'
        '<div style="margin-top:6px;font-size:19px;line-height:1.35;font-weight:600;color:%(text)s;">%(title)s</div>'
        '</td></tr>'
        '<tr><td style="padding:12px 24px 24px;font-size:14px;line-height:1.5;color:%(text)s;">%(body)s</td></tr>'
        '<tr><td style="padding:12px 24px;border-top:1px solid %(line)s;font-size:11px;'
        'line-height:1.5;color:#adb5bd;">%(footer)s</td></tr>'
        '</table></div>'
    ) % {
        'bg': BG, 'font': FONT, 'text': TEXT, 'line': LINE, 'accent': accent, 'muted': MUTED,
        'brand': _e(BRAND), 'title': _e(title), 'body': body_html,
        'pre': _e(preheader), 'footer': _e(footer),
    }


def email_button(label, url, kind='primary'):
    """Table-based button so it also renders in Outlook."""
    styles = {
        'approve': (DONE, '#ffffff', DONE),
        'reject': ('#ffffff', REJECTED, REJECTED),
        'primary': (CURRENT, '#ffffff', CURRENT),
        'company': (KDVN, '#ffffff', KDVN),
    }
    bg, fg, border = styles.get(kind, styles['primary'])
    return (
        '<td style="padding:0 8px 0 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
        '<td style="background:%s;border:1px solid %s;border-radius:4px;">'
        '<a href="%s" target="_blank" style="display:inline-block;padding:7px 16px;font-size:13px;'
        'font-weight:600;color:%s;text-decoration:none;">%s</a>'
        '</td></tr></table></td>'
    ) % (bg, border, _e(url), fg, _e(label))


def _urgent_pill():
    return ('<span style="display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;'
            'background:%s;color:#ffffff;font-size:10px;font-weight:700;letter-spacing:0.04em;'
            'vertical-align:2px;">URGENT</span>') % REJECTED


def _special_pill():
    return ('<span style="display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;'
            'background:%s;color:#ffffff;font-size:10px;font-weight:700;letter-spacing:0.04em;'
            'vertical-align:2px;">SPECIAL</span>') % CURRENT


def _special_html(item):
    if not item.get('special'):
        return ''
    return ('<div style="margin-top:8px;padding:6px 10px;border-left:3px solid %s;background:#f8f9fa;'
            'font-size:12px;line-height:1.5;color:%s;"><b>Special case:</b> %s</div>'
            % (CURRENT, TEXT_SOFT, '; '.join(_e(r) for r in item['special'])))


def _files_html(item):
    parts = []
    if item.get('files_attached'):
        parts.append('<div style="margin-top:8px;font-size:12px;color:%s;">&#128206; Attached: %s</div>'
                     % (MUTED, _e(', '.join(item['files_attached']))))
    if item.get('files_linked'):
        links = ', '.join('<a href="%s" target="_blank" style="color:%s;">%s</a>'
                          % (_e(url), CURRENT, _e(name)) for name, url in item['files_linked'])
        parts.append('<div style="margin-top:4px;font-size:12px;color:%s;">Too large to attach, download: %s</div>'
                     % (MUTED, links))
    return ''.join(parts)


def request_card(item):
    """One request waiting for the reader, with Approve / Reject / Open."""
    accent = REJECTED if item.get('emergency') else CURRENT
    step = ''
    if item.get('step_label'):
        step = ' · Step %s/%s: %s' % (item.get('step_no') or '?', item.get('step_total') or '?',
                                      _e(item['step_label']))
    return (
        '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
        'style="border:1px solid %(line)s;border-left:3px solid %(accent)s;border-radius:4px;'
        'margin:0 0 12px;border-collapse:separate;">'
        '<tr><td style="padding:12px 14px;">'
        '<div><span style="font-size:15px;font-weight:600;color:%(text)s;">%(ref)s</span>'
        '<span style="font-size:12px;color:%(muted)s;"> · %(title)s</span>%(urgent)s%(special_pill)s</div>'
        '<div style="margin-top:2px;font-size:12px;color:%(muted)s;">%(applicant)s%(step)s</div>'
        '%(special)s'
        '<div style="margin-top:8px;font-size:13px;line-height:1.5;color:%(soft)s;">%(details)s</div>'
        '%(files)s'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr>'
        '%(approve)s%(reject)s'
        '<td style="padding:0;"><a href="%(open)s" target="_blank" style="font-size:13px;color:%(current)s;'
        'text-decoration:none;">Open in Odoo &rsaquo;</a></td>'
        '</tr></table>'
        '</td></tr></table>'
    ) % {
        'line': LINE, 'accent': accent, 'text': TEXT, 'muted': MUTED, 'soft': TEXT_SOFT,
        'current': CURRENT, 'ref': _e(item.get('ref')), 'title': _e(item.get('title')),
        'urgent': _urgent_pill() if item.get('emergency') else '',
        'special_pill': _special_pill() if item.get('special') else '',
        'special': _special_html(item),
        'applicant': _e(item.get('applicant')), 'step': step,
        'details': item.get('details_html') or '', 'files': _files_html(item),
        'approve': email_button('Approve', item['approve_url'], 'approve'),
        'reject': email_button('Reject', item['reject_url'], 'reject'),
        'open': _e(item.get('odoo_url')),
    }


def reviewer_email(reader_name, items, digest=True):
    """Return (subject, html) for requests waiting for one reviewer.
    digest=True: the daily list. digest=False: sent the moment a request arrives."""
    count = len(items)
    urgent = any(i.get('emergency') for i in items)
    if digest:
        subject = 'E-Approval: %s request%s waiting for you' % (count, '' if count == 1 else 's')
        title = '%s request%s waiting for your approval' % (count, '' if count == 1 else 's')
        intro = 'Hello %s, here is your daily list of requests waiting for your decision.' % _e(reader_name)
    else:
        first = items[0]
        subject = '%s: %s · %s' % ('URGENT approval needed' if urgent else 'Approval needed',
                                   first.get('ref'), first.get('title'))
        title = 'A request needs your approval' if count == 1 else '%s requests need your approval' % count
        intro = 'Hello %s, the following request%s just reached your step.' % (
            _e(reader_name), '' if count == 1 else 's')

    body = ['<p style="margin:0 0 16px;color:%s;">%s</p>' % (TEXT_SOFT, intro)]
    if urgent:
        note = ('Requests marked URGENT were flagged as an emergency by the applicant.' if digest else
                'The applicant marked this as an emergency. Please review it as soon as you can.')
        body.append('<div style="margin:0 0 16px;padding:10px 12px;background:#fdf2f2;border-left:3px solid %s;'
                    'border-radius:3px;font-size:13px;color:#a71d2a;"><b>Urgent.</b> %s</div>' % (REJECTED, _e(note)))

    groups = {}
    for item in items:
        groups.setdefault(item.get('category') or 'Other', []).append(item)
    show_headings = len(groups) > 1 or digest
    for category, group in groups.items():
        if show_headings:
            body.append('<div style="margin:18px 0 8px;font-size:11px;font-weight:600;letter-spacing:0.06em;'
                        'text-transform:uppercase;color:%s;">%s · %s</div>' % (MUTED, _e(category), len(group)))
        body.extend(request_card(i) for i in group)

    accent = REJECTED if urgent else CURRENT
    return subject, email_shell(title, ''.join(body), accent=accent, preheader=intro, footer=FOOTER_REVIEWER)


def applicant_email(reader_name, outcome, ref, title, subject_text, odoo_url,
                    amount_text=None, decided_by=None, comment=None):
    """Return (subject, html) telling the applicant the final result.
    outcome: 'approved' or 'rejected'."""
    approved = outcome == 'approved'
    color = DONE if approved else REJECTED
    word = 'approved' if approved else 'rejected'
    subject = '%s: %s · %s' % (word.capitalize(), ref, subject_text or title)
    heading = 'Your request was %s' % word

    rows = [('Request', ref), ('Procedure', title), ('Subject', subject_text)]
    if amount_text:
        rows.append(('Amount', amount_text))
    if decided_by:
        rows.append(('Rejected by' if not approved else 'Last approval', decided_by))
    table = ''.join(
        '<tr><td style="padding:4px 12px 4px 0;font-size:13px;color:%s;white-space:nowrap;vertical-align:top;">%s</td>'
        '<td style="padding:4px 0;font-size:13px;color:%s;">%s</td></tr>' % (MUTED, _e(k), TEXT, _e(v))
        for k, v in rows if v)

    pill = ('<span style="display:inline-block;padding:2px 10px;border-radius:10px;background:%s;color:#ffffff;'
            'font-size:12px;font-weight:600;">%s</span>') % (color, word.capitalize())
    intro = ('Hello %s, all approvers have signed off on your request.' if approved
             else 'Hello %s, your request was not approved.') % _e(reader_name)

    body = [
        '<div style="margin:0 0 12px;">%s</div>' % pill,
        '<p style="margin:0 0 16px;color:%s;">%s</p>' % (TEXT_SOFT, intro),
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">%s</table>' % table,
    ]
    if comment and not approved:
        body.append('<div style="margin:0 0 16px;padding:10px 12px;background:#fdf2f2;border-left:3px solid %s;'
                    'border-radius:3px;font-size:13px;color:%s;"><div style="font-size:11px;font-weight:600;'
                    'color:%s;text-transform:uppercase;letter-spacing:0.04em;">Reason</div>%s</div>'
                    % (REJECTED, TEXT_SOFT, REJECTED, _e(comment)))
    body.append('<table role="presentation" cellpadding="0" cellspacing="0"><tr>%s</tr></table>'
                % email_button('Open request', odoo_url, 'primary'))
    return subject, email_shell(heading, ''.join(body), accent=color, preheader=intro)


# ---------------------------------------------------------------------------
# Nextcloud Talk
# Talk renders Markdown, so links are written as [label](url): the reader sees only the
# label, and Talk doesn't build a link preview card for them (it only previews bare
# URLs). Set TALK_MARKDOWN = False to send plain text with bare URLs instead.
# ---------------------------------------------------------------------------
TALK_MARKDOWN = True


def _one_line(value, limit=None):
    """Text on one line: line breaks become ' · ', Markdown symbols removed."""
    parts = [' '.join(line.split()) for line in (value or '').splitlines()]
    text = ' · '.join(p for p in parts if p)
    text = text.replace('*', '').replace('`', "'").replace('[', '(').replace(']', ')')
    if limit and len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    return text


def _bold(text):
    return '**%s**' % text if TALK_MARKDOWN else text


def _links(pairs):
    """[(label, url)] -> one Markdown line, or one 'label: url' line per link."""
    if TALK_MARKDOWN:
        return [' · '.join('[%s](%s)' % (label, url) for label, url in pairs)]
    return ['%s: %s' % (label, url) for label, url in pairs]


def talk_request(item):
    """A request just reached the reader's step."""
    head = '🚨 ' + _bold('URGENT APPROVAL') if item.get('emergency') else '🔔 ' + _bold('APPROVAL NEEDED')
    who = [_one_line(item.get('title')), _one_line(item.get('applicant'))]
    if item.get('step_label'):
        who.append('Step %s of %s: %s' % (item.get('step_no') or '?', item.get('step_total') or '?',
                                          _one_line(item['step_label'])))
    lines = ['%s · %s' % (head, _one_line(item.get('ref'))), ' · '.join(p for p in who if p)]
    if item.get('special'):
        lines.append('⚠️ %s: %s' % (_bold('Special case'), _one_line('; '.join(item['special']), 200)))
    details = _one_line(item.get('details_text'), 160)
    if details:
        lines.append(details)
    lines += _links([('✅ Approve', item['approve_url']), ('❌ Reject', item['reject_url']),
                     ('🔗 Open', item['odoo_url'])])
    return '\n'.join(lines)


def talk_reminder(items):
    """Daily reminder for people who chose Talk only: one message, Odoo link per request."""
    count = len(items)
    lines = ['⏰ ' + _bold('%s request%s waiting for you' % (count, '' if count == 1 else 's'))]
    for item in items[:10]:
        urgent = '🚨 ' if item.get('emergency') else ''
        special = '⚠️ ' if item.get('special') else ''
        label = '%s%s%s · %s' % (urgent, special, _one_line(item.get('ref')), _one_line(item.get('applicant'), 30))
        if TALK_MARKDOWN:
            lines.append('• [%s](%s)' % (label, item['odoo_url']))
        else:
            lines.append('• %s: %s' % (label, item['odoo_url']))
    if count > 10:
        lines.append('…and %s more in Odoo.' % (count - 10))
    return '\n'.join(lines)


def talk_applicant_step(ref, steps_done, approver, next_label, next_no, total, odoo_url):
    """Some steps of the reader's own request were approved; more to go."""
    first = '✔️ %s · %s approved by %s' % (_one_line(ref), _bold(_one_line(steps_done)), _one_line(approver))
    nxt = 'Next: %s (%s/%s)' % (_one_line(next_label), next_no, total) if next_label else 'Next step pending'
    return '\n'.join([first, nxt] + _links([('🔗 Open', odoo_url)]))


def talk_applicant_result(ref, outcome, subject_text, odoo_url, decided_by=None, comment=None):
    """Final result of the reader's own request."""
    if outcome == 'approved':
        first = '✅ %s %s · %s' % (_one_line(ref), _bold('APPROVED'), _one_line(subject_text, 80))
        lines = [first]
    else:
        first = '❌ %s %s by %s' % (_one_line(ref), _bold('REJECTED'), _one_line(decided_by or 'a reviewer'))
        lines = [first]
        if comment:
            lines.append('Reason: "%s"' % _one_line(comment, 160))
    return '\n'.join(lines + _links([('🔗 Open', odoo_url)]))

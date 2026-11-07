"""Texts of the safety tool notifications (Nextcloud Talk and email). Pure functions, same look as the
e-approval notifications (they reuse its building blocks)."""
from odoo.addons.kdvn_e_approval.models import approval_notify_render as render

_e, _one, _bold, _links = render._e, render._one_line, render._bold, render._links

EVENTS = {
    # key: (emoji, email heading, accent colour)
    'approved_stock': (u'\U0001F4E6', 'Approved: ready to hand over', render.DONE),
    'approved_short': (u'\U0001F6D2', 'Approved: short of stock, please purchase', render.CURRENT),
    'handover': (u'\U0001F4E6', 'Your safety tools were handed over', render.DONE),
    'reminder': (u'⏰', 'Please confirm the receipt of your safety tools', render.CURRENT),
    'not_received': (u'⚠️', 'The applicant says the tools were not received', render.REJECTED),
}


def talk_text(event, ref, who, tools_text, note, odoo_url):
    emoji, heading, _accent = EVENTS[event]
    lines = ['%s %s · %s' % (emoji, _bold(_one(heading)), _one(ref))]
    if who:
        lines.append(_one(who))
    if tools_text:
        lines.append(_one(tools_text, 200))
    if note:
        lines.append(_one(note, 200))
    return '\n'.join(lines + _links([(u'\U0001F517 Open', odoo_url)]))


def email_parts(event, reader_name, ref, who, tools_text, note, odoo_url):
    """(subject, html)"""
    emoji, heading, accent = EVENTS[event]
    rows = [('Request', ref), ('Applicant', who), ('Tools', tools_text)]
    table = ''.join(
        '<tr><td style="padding:4px 12px 4px 0;font-size:13px;color:%s;white-space:nowrap;vertical-align:top;">%s</td>'
        '<td style="padding:4px 0;font-size:13px;color:%s;">%s</td></tr>' % (render.MUTED, _e(k), render.TEXT, _e(v))
        for k, v in rows if v)
    body = ['<p style="margin:0 0 12px;color:%s;">Hello %s,</p>' % (render.TEXT_SOFT, _e(reader_name)),
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">%s</table>' % table]
    if note:
        body.append('<p style="margin:0 0 16px;color:%s;">%s</p>' % (render.TEXT_SOFT, _e(note)))
    body.append('<table role="presentation" cellpadding="0" cellspacing="0"><tr>%s</tr></table>'
                % render.email_button('Open request', odoo_url, 'primary'))
    return '%s · %s' % (heading, ref), render.email_shell(heading, ''.join(body), accent=accent, preheader=note or heading)

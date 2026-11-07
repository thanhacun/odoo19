"""Email for the KOM peak time reminder. Pure function (no database access),
built from the shared E-Approval email blocks so it looks like the other emails."""
from odoo.addons.kdvn_e_approval.models import approval_notify_render as render

_e = render._e


def kom_reminder_email(pm_name, job_ref, client, kom_from, kom_to, days_left,
                       late_special_days, late_block_days, register_url):
    """Return (subject, html). Dates are already formatted strings."""
    subject = 'Reminder: register peak time for %s' % job_ref
    heading = 'Peak time starts in %s day%s' % (days_left, '' if days_left == 1 else 's')
    intro = ('Hello %s, the peak time estimated at the kick-off meeting for this project starts soon '
             'and no Peak Time request has been registered yet.') % _e(pm_name)
    rows = [('Project', job_ref), ('Client', client),
            ('KOM peak time', '%s – %s' % (kom_from, kom_to) if kom_to else kom_from)]
    table = ''.join(
        '<tr><td style="padding:4px 12px 4px 0;font-size:13px;color:%s;white-space:nowrap;vertical-align:top;">%s</td>'
        '<td style="padding:4px 0;font-size:13px;color:%s;">%s</td></tr>'
        % (render.MUTED, _e(k), render.TEXT, _e(v)) for k, v in rows if v)
    # Rules switched off are passed as None
    parts = []
    if late_special_days is not None:
        parts.append('Requests registered more than %s days after the actual peak start need special approval.'
                     % late_special_days)
    if late_block_days is not None:
        parts.append('More than %s days after, they cannot be submitted.' % late_block_days)
    note = ' '.join(parts) or 'Please register it before the peak starts.'
    body = (
        '<p style="margin:0 0 16px;color:%s;">%s</p>' % (render.TEXT_SOFT, intro)
        + '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">%s</table>' % table
        + '<div style="margin:0 0 16px;padding:10px 12px;background:#f8f9fa;border-left:3px solid %s;'
          'border-radius:3px;font-size:13px;color:%s;">%s</div>' % (render.KDVN, render.TEXT_SOFT, _e(note))
        + '<table role="presentation" cellpadding="0" cellspacing="0"><tr>%s</tr></table>'
        % render.email_button('Register peak time', register_url, 'company')
    )
    return subject, render.email_shell(heading, body, accent=render.KDVN, preheader=intro)

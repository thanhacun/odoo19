# -*- coding: utf-8 -*-
"""Runs what the Odoo 19 web client runs for every window action of our modules, so errors show up here and not in the browser:
get_views, then per view mode: list/kanban -> web_search_read with the view's default_order and the action's default facets (search_default_*),
grouped -> web_read_group, pivot/graph -> formatted_read_group, form -> onchange of a new record (defaults) and web_read of the first record.
Used by the module tests (small database) and by `odoo shell` on a database with real data:  run(env)  returns the list of failures.
"""
import datetime
import re
import time

from dateutil import relativedelta
from lxml import etree

from odoo.tools import safe_eval as safe_eval_module
from odoo.tools.safe_eval import safe_eval

X2MANY = ('one2many', 'many2many')


def _eval_context(env, ctx):
    today = datetime.date.today()
    return {
        # safe_eval refuses raw modules: use the wrapped ones Odoo itself uses for action contexts and domains (before this fix every context, domain
        # and default facet fell back to empty, so the screens were never read with their real filters)
        'uid': env.uid, 'user': env.user, 'time': safe_eval_module.time, 'datetime': safe_eval_module.datetime, 'relativedelta': relativedelta.relativedelta,
        'context_today': lambda: today, 'current_date': today.strftime('%Y-%m-%d'), 'context': ctx, 'allowed_company_ids': env.companies.ids,
        'active_id': False, 'active_ids': [], 'active_model': False, 'id': False,
    }


def _safe(expr, env, ctx, default):
    if not expr:
        return default
    try:
        return safe_eval(expr, _eval_context(env, ctx))
    except Exception:
        return default


def _field_names(arch_node, model):
    """Fields of the view that exist on the model (what the client asks the server to read)."""
    names = set()
    for node in arch_node.iter('field'):
        name = node.get('name')
        if name and name in model._fields:
            names.add(name)
    return names


def _spec(model, names):
    spec = {}
    for name in names:
        field = model._fields[name]
        if field.type in X2MANY:
            spec[name] = {'fields': {'display_name': {}}}
        elif field.type == 'many2one':
            spec[name] = {'fields': {'display_name': {}}}
        else:
            spec[name] = {}
    return spec


def _default_facets(env, search_arch, ctx):
    """Domain and group-bys of the search_default_* keys of the action context (what the client applies on opening)."""
    domain, groupby = [], []
    if not search_arch:
        return domain, groupby
    root = etree.fromstring(search_arch)
    nodes = {n.get('name'): n for n in root.iter() if isinstance(n.tag, str) and n.get('name') and n.tag in ('filter', 'field')}
    for key, value in ctx.items():
        if not key.startswith('search_default_') or not value:
            continue
        node = nodes.get(key[len('search_default_'):])
        if node is None:
            continue
        if node.tag == 'filter':
            if node.get('domain'):
                result = _safe(node.get('domain'), env, ctx, [])
                domain += result if isinstance(result, list) else []
            elif node.get('context'):
                found = re.search(r"group_by['\"]?\s*:\s*['\"]([\w.:]+)['\"]", node.get('context'))
                if found:
                    groupby.append(found.group(1))
        else:
            domain.append((node.get('name'), 'ilike', value) if isinstance(value, str) else (node.get('name'), '=', value))
    return domain, groupby


def run(env, prefixes=('kdvn_',), limit=80, form_records=1, login=None):
    """Return a list of 'action / view / call: error' strings (empty when everything the UI does works).
    login: run as that user (a role of the guide users: employees, managers...) instead of the administrator; actions the user may not
    open (groups) are skipped, as the menu would not show them."""
    user = env['res.users'].with_context(active_test=False).search([('login', '=', login)], limit=1) if login else env.ref('base.user_admin')
    if not user:
        return ['no user with login %s' % login]
    env = env(user=user.id)
    failures = []
    data = env['ir.model.data'].sudo().search([('model', '=', 'ir.actions.act_window')])
    actions = [(d.complete_name, env['ir.actions.act_window'].sudo().browse(d.res_id).exists()) for d in data if d.module.startswith(prefixes)]
    for xmlid, action in actions:
        if not action or action.res_model not in env:
            continue
        if action.group_ids and not (action.group_ids & env.user.all_group_ids):
            continue        # the menu would not show it to this user
        model = env[action.res_model]
        if not model.has_access('read'):
            continue        # no access rights at all: a screen for other roles
        menus = env['ir.ui.menu'].sudo().search([('action', '=', 'ir.actions.act_window,%d' % action.id)])
        if menus and not any(not m.group_ids or (m.group_ids & env.user.all_group_ids) for m in menus):
            continue        # every menu of this action is limited to other groups: the user cannot reach the screen
        ctx = _safe(action.context, env, {}, {})
        if not isinstance(ctx, dict):
            ctx = {}
        domain = _safe(action.domain, env, ctx, [])
        modes = [m for m in (action.view_mode or 'list,form').split(',') if m]
        view_by_mode = {v.view_mode: v.view_id.id for v in action.view_ids}
        requests = [(view_by_mode.get(m) or (action.view_id.id if action.view_id and action.view_id.type == m else False), m) for m in modes]
        requests.append((action.search_view_id.id or False, 'search'))

        def attempt(label, func):
            try:
                with env.cr.savepoint():
                    func()
            except Exception as error:   # report every kind of failure, one line each
                failures.append('%s | %s: %s: %s' % (xmlid, label, type(error).__name__, str(error).strip().splitlines()[-1][:160] if str(error).strip() else ''))

        views = {}

        def load():
            views.update(model.with_context(**ctx).get_views(requests, options={'action_id': action.id, 'toolbar': False})['views'])
        attempt('get_views', load)
        if not views:
            continue
        search_arch = (views.get('search') or {}).get('arch')
        facet_domain, facet_group = _default_facets(env, search_arch, ctx)
        full_domain = list(domain) + facet_domain
        for mode in modes:
            view = views.get(mode)
            if not view:
                continue
            root = etree.fromstring(view['arch'])
            if mode in ('list', 'kanban'):
                names = _field_names(root, model)
                order = root.get('default_order')
                attempt('%s read' % mode, lambda: model.with_context(**ctx).web_search_read(full_domain, _spec(model, names), limit=limit, order=order))
                if facet_group:
                    attempt('%s group by %s' % (mode, facet_group), lambda: model.with_context(**dict(ctx, read_group_expand=True)).web_read_group(   # the web client sets read_group_expand on grouped lists
                        full_domain, facet_group[:1], ['__count'], limit=limit, unfold_read_specification=_spec(model, names)))
            elif mode in ('pivot', 'graph'):
                rows = [n.get('name') + (':' + n.get('interval') if n.get('interval') else '') for n in root.iter('field')
                        if n.get('type') in ('row', 'col') and n.get('name') in model._fields]
                if mode == 'graph' and not rows:
                    rows = [n.get('name') for n in root.iter('field') if n.get('name') in model._fields][:1]
                measures = [n.get('name') + ':sum' for n in root.iter('field') if n.get('type') == 'measure' and n.get('name') in model._fields
                            and model._fields[n.get('name')].type in ('integer', 'float', 'monetary')]
                attempt('%s read_group' % mode, lambda: model.with_context(**ctx).formatted_read_group(full_domain, rows[:2], measures + ['__count'], limit=limit))
            elif mode == 'form':
                names = _field_names(root, model)
                # a new record can only be started from the UI when the form and the list allow create and the user may create
                list_root = etree.fromstring(views['list']['arch']) if views.get('list') else None
                can_create = (root.get('create') not in ('0', 'false', 'False')
                              and (list_root is None or list_root.get('create') not in ('0', 'false', 'False'))
                              and model.has_access('create'))
                if can_create:
                    attempt('form onchange (new record)', lambda: model.with_context(**ctx).onchange({}, [], {n: {} for n in names}))
                if form_records:
                    ids = model.with_context(**ctx).search(full_domain, limit=form_records).ids
                    if ids:
                        attempt('form read of first record', lambda: model.browse(ids).with_context(**ctx).web_read(_spec(model, names)))
    return failures

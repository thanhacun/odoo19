#!/usr/bin/env python3
"""Odoo 12 -> 19 migration sweep: finds code patterns that no longer work (or are deprecated) in Odoo 19 / Python 3.12.
Static only (no database). Run after `odoo upgrade_code` (see docs/odoo19_migration_checklist.md).

    python3 tools/odoo19_sweep.py [addons_dir] [module ...]      (default: addons/ and every kdvn_* module)

Exit code 1 when a BREAK finding exists. WARN = works now, deprecated. Every rule says why and what to use instead.
"""
import ast
import glob
import os
import re
import sys
import warnings

from lxml import etree

BREAK, WARN = 'BREAK', 'WARN'

# (severity, id, file kind, regex, why / fix)
RULES = [
    (BREAK, 'api-multi', 'py', r'@api\.(multi|one|returns)\b', '@api.multi/@api.one/@api.returns are gone: delete the decorator (methods work on recordsets)'),
    (BREAK, 'name_get', 'py', r'def name_get\(|\.name_get\(', 'name_get is gone: override _compute_display_name (depends on the fields it uses)'),
    (BREAK, '_name_search', 'py', r'def _name_search\(', '_name_search is gone: use _rec_names_search or _search_display_name'),
    (BREAK, 'fields_view_get', 'py', r'fields_view_get|fields_get_keys', 'fields_view_get is gone: use get_view / _get_view'),
    (BREAK, 'sudo-user', 'py', r'\.sudo\((?!\s*\)|\s*(True|False)\s*\)|[^)]*(==|!=|\bnot\b|\bis\b|\bin\b))[^)]', 'sudo(user) is gone: use with_user(user)'),
    (BREAK, 'groups_id', 'any', r'[\'"]groups_id[\'"]|\.groups_id\b|name="groups_id"', 'res.users.groups_id / actions groups_id are group_ids in Odoo 19'),
    (BREAK, 'invalidate_cache', 'py', r'invalidate_cache\(|\.recompute\(', 'removed: use env.invalidate_all() / records.invalidate_recordset(), flush_all()'),
    (BREAK, 'view_type', 'any', r'["\']view_type["\']\s*[:=]|<field name="view_type">', 'view_type is gone from actions'),
    (BREAK, 'tree-view-mode', 'any', r'view_mode["\'>=:\s]+[^"\'<\n]*\btree\b|mode="tree|\(False,\s*["\']tree["\']\)', 'the "tree" view type is "list" (python upgrade_code 17.5-01 does this)'),
    (BREAK, 'attrs-states', 'xml', r'\battrs\s*=|\sstates\s*=\s*"', 'attrs= and states= are removed: use invisible/readonly/required expressions'),
    (BREAK, 'kanban-box', 'xml', r't-name="kanban-box"', 'kanban template is "card" in Odoo 18+'),
    (BREAK, 't-esc/t-raw', 'xml', r'\bt-(esc|raw)\s*=', 't-esc/t-raw are t-out'),
    (BREAK, 'track_visibility', 'py', r'track_visibility', 'use tracking=True'),
    (BREAK, 'py2', 'py', r'\b(unicode|basestring|iteritems|itervalues|iterkeys|xrange|has_key)\b\(?', 'python 2 leftovers'),
    (BREAK, 'py312-removed', 'py', r'^\s*(import|from)\s+(distutils|imp|asyncore|asynchat|pkg_resources|cgi)\b', 'removed or deprecated in Python 3.12'),
    (BREAK, 'cron-numbercall', 'xml', r'name="(numbercall|doall)"', 'removed from ir.cron'),
    (BREAK, 'message_post-subtype', 'py', r'message_post[^\n]*\bsubtype\s*=', 'use subtype_xmlid='),
    (BREAK, 'message_post_with_template', 'py', r'message_post_with_template', 'use message_post_with_source'),
    (BREAK, 'old-http-json', 'py', r'type\s*=\s*[\'"]json[\'"]', "http.route(type='json') is type='jsonrpc'"),
    (BREAK, 'odoo.define', 'js', r'odoo\.define\(|require\(["\']web\.', 'legacy JS modules are gone: write ES modules (@odoo-module) / OWL'),
    (BREAK, 'transient-max', 'py', r'_transient_max_(hours|count)', 'removed'),
    (BREAK, 'refresh-flush', 'py', r'\.(refresh|flush|recompute)\(\)', 'removed: env.invalidate_all(), flush_all(), flush_model()/flush_recordset() (OCA migrator rule [16])'),
    (BREAK, 'api.model_cr', 'py', r'@api\.model_cr\b', 'removed decorator (OCA migrator rule [13])'),
    (BREAK, 'message_post_with_view', 'py', r'message_post_with_view', 'use message_post_with_source'),
    (BREAK, 'xpath-string', 'xml', r'xpath[^>]*@string\s*=', "xpath on @string is deprecated: use @name or a stable attribute (OCA migrator)"),
    (WARN, 'user-company', 'py', r'env\.user\.company_id', 'the active company is env.company (multi-company); user.company_id is the default company (OCA migrator rule [13])'),
    (WARN, 'sql_constraints', 'py', r'_sql_constraints\s*=', 'use models.Constraint (python upgrade_code 18.1-00 does it)'),
    (WARN, 'group_operator', 'py', r'group_operator\s*=', 'renamed aggregator='),
    (WARN, 'read_group', 'py', r'\.read_group\(', 'deprecated: _read_group / formatted_read_group'),
    (WARN, 'osv', 'py', r'from odoo\.osv|odoo\.osv\.expression', 'deprecated: odoo.fields.Domain'),
    (WARN, 'utcnow', 'py', r'datetime\.utcnow\(|utcfromtimestamp\(', 'deprecated in Python 3.12: datetime.now(timezone.utc) or fields.Datetime.now()'),
    (WARN, 'context-private', 'py', r'self\._context\b', 'use self.env.context (python upgrade_code 18.5 does it)'),
    (WARN, 'sudo-bool', 'py', r'\.sudo\((True|False)\)', 'sudo(flag) is with_user/sudo(); check'),
    (WARN, 'tuple-commands', 'py', r'\(\s*[0-6]\s*,\s*(0|False|None)\s*,', 'x2many commands as tuples work; Command.* is clearer'),
    (WARN, 'user-groups', 'py', r'user\.groups_id|\.has_group\(', 'has_group is fine; groups_id is group_ids'),
]


def files(module_dir, kind):
    exts = {'py': ['.py'], 'xml': ['.xml'], 'js': ['.js'], 'any': ['.py', '.xml', '.js']}[kind]
    for root, dirs, names in os.walk(module_dir):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules', '.git', 'lib')]
        for n in names:
            if os.path.splitext(n)[1] in exts and not n.endswith('.min.js'):
                yield os.path.join(root, n)


def strip_comments(path, text):
    if path.endswith('.py'):
        return '\n'.join('' if l.lstrip().startswith('#') else l for l in text.split('\n'))
    if path.endswith('.xml'):
        return re.sub(r'<!--.*?-->', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text, flags=re.S)
    if path.endswith('.js'):
        return re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text, flags=re.S)
    return text


def regex_findings(module_dir):
    out = []
    for severity, rid, kind, rx, why in RULES:
        pattern = re.compile(rx, re.M)
        for path in files(module_dir, kind):
            if os.path.basename(path) == '__manifest__.py':
                continue   # descriptions mention old names
            text = strip_comments(path, open(path, encoding='utf-8', errors='replace').read())
            for m in pattern.finditer(text):
                line = text.count('\n', 0, m.start()) + 1
                out.append((severity, rid, path, line, why))
    return out


def xml_findings(module_dir):
    """Structural checks that need a parser."""
    out = []
    for path in files(module_dir, 'xml'):
        try:
            root = etree.parse(path).getroot()
        except Exception as e:
            out.append((BREAK, 'xml-parse', path, 0, str(e)[:100]))
            continue
        for lst in root.iter('list'):
            for child in lst:
                if child.tag == 'field' and child.get('invisible') in ('1', 'True', 'true') and child.get('column_invisible') is None:
                    out.append((BREAK, 'list-invisible', path, child.sourceline,
                                'in a list invisible="1" hides only the cell: use column_invisible="1" (Odoo 12 hid the column)'))
        for rec in root.iter('record'):
            if rec.get('model') == 'ir.ui.view':
                names = {f.get('name'): f for f in rec.findall('field')}
                if 'inherit_id' not in names and names.get('priority') is not None and (names['priority'].text or '').strip().isdigit() \
                        and int((names['priority'].text or '0').strip()) >= 16 and (names.get('model') is not None and names['model'].text or '').startswith(('hr.attendance', 'hr.leave', 'hr.employee', 'hr.department')):
                    out.append((WARN, 'view-priority', path, rec.sourceline,
                                'primary view with priority >= 16 on a core model: the core view (16) may win; check `get_view` (lowest priority number wins)'))
    return out


def python_findings(module_dir):
    out = []
    for path in files(module_dir, 'py'):
        source = open(path, encoding='utf-8', errors='replace').read()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            try:
                tree = ast.parse(source, path)
            except SyntaxError as e:
                out.append((BREAK, 'py-syntax', path, e.lineno or 0, str(e)[:100]))
                continue
        for w in caught:
            if issubclass(w.category, (SyntaxWarning, DeprecationWarning)):
                out.append((WARN, 'py312-warning', path, getattr(w, 'lineno', 0) or 0, str(w.message)[:90]))
        field_computes = set(re.findall(r"compute\s*=\s*['\"](\w+)['\"]", strip_comments(path, source)))
        for node in ast.walk(tree):
            # field compute methods that call ensure_one(): break when a list view computes many records at once
            if isinstance(node, ast.FunctionDef) and node.name in field_computes and 'ensure_one' in ast.dump(node):
                out.append((BREAK, 'compute-ensure_one', path, node.lineno, 'a compute method may receive many records (list view): loop over self'))
            # Selection with integer keys
            if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'Selection' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.List):
                    for item in arg.elts:
                        if isinstance(item, ast.Tuple) and item.elts and isinstance(item.elts[0], ast.Constant) and not isinstance(item.elts[0].value, str):
                            out.append((BREAK, 'selection-key', path, node.lineno, 'Odoo 19 selection keys must be strings'))
                            break
            # create() override without model_create_multi
            if isinstance(node, ast.FunctionDef) and node.name == 'create':
                decos = [ast.dump(d) for d in node.decorator_list]
                params = [a.arg for a in node.args.args]
                if params[:2] == ['self', 'vals'] and not any('model_create_multi' in d for d in decos):
                    out.append((WARN, 'create-single', path, node.lineno, 'create(self, vals) is deprecated: @api.model_create_multi and a list'))
    return out


def manifest_findings(module_dir):
    out = []
    path = os.path.join(module_dir, '__manifest__.py')
    if os.path.exists(path):
        data = ast.literal_eval(open(path, encoding='utf-8').read())
        version = str(data.get('version', ''))
        if not version.startswith('19.0.'):
            out.append((BREAK, 'manifest-version', path, 1, 'version %s must start with 19.0.' % version))
        for key in ('qweb', 'css', 'js'):
            if key in data:
                out.append((BREAK, 'manifest-' + key, path, 1, "'%s' key is gone: use 'assets'" % key))
    return out


def main(argv):
    addons = argv[0] if argv and os.path.isdir(argv[0]) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'addons')
    wanted = [a for a in argv if not os.path.isdir(a)]
    modules = sorted(m for m in os.listdir(addons) if os.path.isdir(os.path.join(addons, m)) and (m in wanted if wanted else m.startswith('kdvn_')))
    total = {BREAK: 0, WARN: 0}
    for module in modules:
        mdir = os.path.join(addons, module)
        found = regex_findings(mdir) + xml_findings(mdir) + python_findings(mdir) + manifest_findings(mdir)
        found = sorted(set(found), key=lambda f: (f[0] != BREAK, f[1], f[2], f[3]))
        print('=' * 8, module, ' BREAK %d  WARN %d' % (sum(f[0] == BREAK for f in found), sum(f[0] == WARN for f in found)))
        by_rule = {}
        for sev, rid, path, line, why in found:
            by_rule.setdefault((sev, rid, why), []).append('%s:%s' % (os.path.relpath(path, mdir), line))
            total[sev] += 1
        for (sev, rid, why), places in by_rule.items():
            print('%-5s %-20s %3d  %s' % (sev, rid, len(places), why))
            for place in places[:4]:
                print('        ' + place)
            if len(places) > 4:
                print('        ... %d more' % (len(places) - 4))
    print('TOTAL BREAK %d  WARN %d' % (total[BREAK], total[WARN]))
    return 1 if total[BREAK] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

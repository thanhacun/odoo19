#!/usr/bin/env python3
"""Convert Odoo 12 `attrs="{'invisible': [domain], 'readonly': [...]}"` and `states="a,b"` in XML view files to Odoo 17+ attributes
(invisible="...", readonly="...", required="..."). Plain text edit of the files (formatting kept).
    python3 tools/attrs_to_expr.py file.xml [file.xml ...]
Domains are prefix notation ('|', '&', '!'); operators = != in not in < > <= >=. Anything it cannot convert is reported and left alone.
"""
import ast
import re
import sys

OPS = {'=': '==', '==': '==', '!=': '!=', '<>': '!=', '<': '<', '>': '>', '<=': '<=', '>=': '>='}


def term(t):
    field, op, value = t
    op = op.lower()
    if op in ('in', 'not in'):
        return '%s %s %s' % (field, op, repr(tuple(value)) if len(value) != 1 else '(%r,)' % value[0])
    if op in OPS:
        if value == [] and op in ('=', '=='):
            return 'not %s' % field
        if value == [] and op in ('!=', '<>'):
            return field
        if value is False and op in ('=', '=='):
            return 'not %s' % field
        if value is True and op in ('=', '=='):
            return field
        if value is False and op in ('!=', '<>'):
            return field
        if value is True and op in ('!=', '<>'):
            return 'not %s' % field
        return '%s %s %r' % (field, OPS[op], value)
    raise ValueError('operator %s' % op)


def domain(items):
    items = list(items)
    if not items:
        return 'True'

    def parse(pos):
        tok = items[pos]
        if tok in ('|', '&'):
            a, pos = parse(pos + 1)
            b, pos = parse(pos)
            joiner = ' or ' if tok == '|' else ' and '
            return '(%s%s%s)' % (a, joiner, b), pos
        if tok == '!':
            a, pos = parse(pos + 1)
            return 'not %s' % a, pos
        return term(tok), pos + 1

    parts = []
    pos = 0
    while pos < len(items):
        expr, pos = parse(pos)
        parts.append(expr)
    out = ' and '.join(parts)
    # drop the outer parentheses of a single group
    if len(parts) == 1 and out.startswith('(') and out.endswith(')'):
        out = out[1:-1]
    return out


def convert_tag(tag, problems, where):
    m = re.search(r'''\sattrs=("([^"]*)"|'([^']*)')''', tag)
    if m:
        raw = m.group(2) if m.group(2) is not None else m.group(3)
        try:
            data = ast.literal_eval(raw.replace('&quot;', '"').strip())
            new = ''.join(' %s="%s"' % (k, domain(v) if isinstance(v, list) else str(v)) for k, v in data.items())
            tag = tag.replace(m.group(0), new)
        except Exception as error:   # noqa
            problems.append('%s: %s (%s)' % (where, raw[:70], error))
    m = re.search(r'''\sstates="([^"]*)"''', tag)
    if m:
        states = [s.strip() for s in m.group(1).split(',') if s.strip()]
        tag = tag.replace(m.group(0), ' invisible="state not in (%s)"' % ', '.join(repr(s) for s in states))
    return tag


def main(paths):
    for path in paths:
        text = open(path, encoding='utf-8').read()
        problems = []
        count = [0]

        def repl(m):
            tag = m.group(0)
            if 'attrs=' not in tag and ' states=' not in tag:
                return tag
            count[0] += 1
            return convert_tag(tag, problems, '%s:%d' % (path, text[:m.start()].count('\n') + 1))

        new = re.sub(r'<[a-zA-Z_]+\b[^<>]*?(?:attrs=(?:"[^"]*"|\'[^\']*\')|\sstates="[^"]*")[^<>]*?/?>', repl, text, flags=re.S)
        if new != text:
            open(path, 'w', encoding='utf-8').write(new)
        print('%s: %d tags, %d left, %d not converted' % (path, count[0], new.count('attrs='), len(problems)))
        for p in problems:
            print('   NOT CONVERTED', p)


if __name__ == '__main__':
    main(sys.argv[1:])

#!/usr/bin/env python3
"""Run Odoo (any arguments, e.g. tests) and record every DeprecationWarning / FutureWarning / PendingDeprecationWarning that is raised
from our code: the warning text plus the first stack frame inside a kdvn_* module. Use it to see what Odoo 20 will remove.

    docker exec odoo19 python3 /home/odoo/project/<tree>/tools/odoo_deprecations.py -c /etc/odoo/odoo.conf -d kdvn_test -u kdvn_hr_attendance \
        --test-tags /kdvn_hr_attendance --stop-after-init --http-port=8079 --gevent-port=8082
    then: python3 tools/odoo_deprecations.py --report temp/deprecations.tsv

Output (appended): temp/deprecations.tsv   columns: count  warning  file:line  function
"""
import collections
import os
import sys
import traceback
import warnings

OUT = os.environ.get('DEPRECATION_OUT', '/home/odoo/project/temp/deprecations.tsv')
CATEGORIES = (DeprecationWarning, PendingDeprecationWarning, FutureWarning)


def report(path):
    rows = collections.Counter()
    for line in open(path, encoding='utf-8'):
        parts = line.rstrip('\n').split('\t')
        if len(parts) == 3:
            rows[tuple(parts)] += 1
    for (warning, where, func), count in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print('%5d  %-90s  %s  %s' % (count, warning[:90], where, func))
    print('%d distinct findings' % len(rows))


if len(sys.argv) >= 3 and sys.argv[1] == '--report':
    report(sys.argv[2])
    sys.exit(0)

seen = set()
handle = open(OUT, 'a', encoding='utf-8')


def show(message, category, filename, lineno, file=None, line=None):
    if not issubclass(category, CATEGORIES):
        return
    for frame in reversed(traceback.extract_stack()):
        if '/addons/kdvn_' in frame.filename and frame.filename.endswith('.py'):
            key = (str(message), frame.filename, frame.lineno)
            if key not in seen:
                seen.add(key)
                handle.write('%s\t%s:%s\t%s\n' % (str(message).replace('\t', ' ').replace('\n', ' ')[:200], frame.filename.split('/addons/', 1)[-1], frame.lineno, frame.name))
                handle.flush()
            return


warnings.simplefilter('always')
warnings.showwarning = show
import logging  # noqa: E402
logging._showwarning = show   # Odoo calls logging.captureWarnings(True), which would replace our hook with this one
import odoo.cli  # noqa: E402
odoo.cli.main()

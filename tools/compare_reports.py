# Compares the xlsx of both sides row by row, ignoring row order: python3 tools/compare_reports.py overtime attendance ...
import sys, os, openpyxl
from collections import Counter
A = os.path.expanduser('~/odoo12/tmp/parity_reports/o12_%s.xlsx'); B = os.path.expanduser('~/odoo19_thcn/temp/parity_reports/o19_%s.xlsx')
def norm(v):
    if isinstance(v, float): return round(v, 4)
    if isinstance(v, str): return v.strip() or None
    return v
def rows(path):
    out = []
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    for r in ws.iter_rows(values_only=True):
        t = tuple(norm(v) for v in r)
        while t and t[-1] is None: t = t[:-1]
        if t: out.append(t)
    return out
for key in sys.argv[1:]:
    a, b = Counter(rows(A % key)), Counter(rows(B % key))
    only12 = a - b; only19 = b - a
    print('==', key, 'rows 12:', sum(a.values()), '19:', sum(b.values()), 'only in 12:', sum(only12.values()), 'only in 19:', sum(only19.values()))
    for t in list(only12)[:3]: print('   12>', t[:14])
    for t in list(only19)[:3]: print('   19>', t[:14])

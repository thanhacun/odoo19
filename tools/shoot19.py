#!/usr/bin/env python3
"""Take pictures of Odoo 19 screens by replaying the Odoo 12 guide scenarios, and put each one next to its Odoo 12 guide picture.
Also an error finder: every UI error (error dialog, JS error, failed RPC call) met while replaying is reported with the step.

    ~/.venvs/kderp-guides/bin/python tools/shoot19.py [--db odoo19_dev] [--url http://172.30.0.4:8069] [--list] [--fresh] [name ...]

name = part of the scenario path (e.g. my-attendance, hr-admin). Default: every scenario of kderp_hr_attendance.
Output (git-ignored, in temp/):  temp/shots19/<scenario>/<picture>.png   the Odoo 19 pictures
                                 temp/compare/<scenario>/<picture>.png   Odoo 12 (guide) above, Odoo 19 below
                                 temp/shoot19_errors.txt                 UI errors with scenario / step
How it works: no password is needed. `odoo shell` (docker) creates a web session for each role's login (logins come from the guide users file, only the
login name is used) and the session cookie is put in the browser. Pages are judged ready by what is on the screen, never by "network idle"
(Odoo's long polling never goes idle). Scenarios and the Odoo 12 pictures are read from ~/odoo12 and never changed.
Role -> user: a role of the scenario is the user with that login in the Odoo 19 database (they are imported from Odoo 12).
Steps: as, go (action=, id=, view_type=, model=), click, unfilter, search, fill, select, wait, shot (mode shot|tall, crop, clip). `rpc` and fixtures that need
`create` are skipped (nothing is ever written to the database).
"""
import argparse
import functools
import glob
import json
import os
import re
import string
import subprocess
import sys
import time

import yaml
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.basename(os.path.dirname(REPO)) == '.worktrees':
    REPO = os.path.dirname(os.path.dirname(REPO))          # the main tree owns temp/
TEMP = os.path.join(REPO, 'temp')
ODOO12 = os.path.expanduser(os.environ.get('ODOO12', '~/odoo12'))
SCENARIOS = os.path.join(ODOO12, 'documentation', 'guides', 'scenarios')
USERS_FILE = os.environ.get('GUIDE_USERS', os.path.join(ODOO12, 'tmp', 'guide_users.txt'))
CONTAINER = os.environ.get('CONTAINER', 'odoo19')
# Odoo 12 xml ids that moved: {odoo12 xml id: odoo19 xml id}. kderp_x.name -> kdvn_x.name is automatic.
XMLID_MAP = {
    'hr_attendance.hr_attendance_action': 'kdvn_hr_attendance.hr_attendance_action',
}
XMLID_MAP_FILE = os.path.join(HERE, 'shoot19_xmlid_map.yaml')
SELECTOR_MAP = {}      # Odoo 12 click selector -> Odoo 19 selector (key `_selectors` of the map file)
if os.path.exists(XMLID_MAP_FILE):
    _map = yaml.safe_load(open(XMLID_MAP_FILE)) or {}
    SELECTOR_MAP.update(_map.pop('_selectors', None) or {})
    XMLID_MAP.update(_map)
W, H = 1366, 768
print = functools.partial(print, flush=True)      # live progress even when the output is piped
READY_MS = 15000          # a screen that is not ready after this is an error, not a reason to wait a minute
SCENARIO_SECONDS = 150    # time budget of one scenario


def role_logins():
    """{role: login}: only the login names of the guide users file (passwords are never read into memory)."""
    out = {}
    for line in open(USERS_FILE, encoding='utf-8'):
        if line.lstrip().startswith('#') or not line.strip():
            continue
        parts = [p.strip() for p in re.split(r'[;:]', line) if p.strip()]
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def make_sessions(db, logins):
    """{login: session id} for the Odoo 19 database, created by `odoo shell` (filesystem session store shared with the running server)."""
    script = """
import json
from odoo import http
store = http.root.session_store
out = {}
for login in %r:
    user = env['res.users'].with_context(active_test=False).search([('login', '=', login)], limit=1)
    if not user:
        out[login] = None
        continue
    session = store.new()
    session.update(http.get_default_session(), db=env.cr.dbname, login=login, uid=user.id,
                   context=dict(user.with_user(user).context_get()), session_token=user._compute_session_token(session.sid))
    store.save(session)
    out[login] = session.sid
print('SESSIONS=' + json.dumps(out))
""" % sorted(logins)
    run = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'odoo', 'shell', '-c', '/etc/odoo/odoo.conf', '-d', db, '--no-http', '--log-level=error'],
                         input=script, capture_output=True, text=True, timeout=300)
    for line in run.stdout.splitlines():
        if line.startswith('SESSIONS='):
            return json.loads(line[len('SESSIONS='):])
    raise SystemExit('could not create sessions:\n' + run.stdout[-500:] + run.stderr[-500:])


def map_xmlid(xmlid):
    if xmlid in XMLID_MAP:
        return XMLID_MAP[xmlid]
    module, name = xmlid.split('.', 1)
    return re.sub(r'^kderp_', 'kdvn_', module) + '.' + name


class Shooter:
    def __init__(self, base, db, sessions, out_dir, compare_dir, errors):
        self.base, self.db, self.sessions = base.rstrip('/'), db, sessions
        self.out_dir, self.compare_dir, self.errors = out_dir, compare_dir, errors
        self.p = sync_playwright().start()
        self.browser = self.p.chromium.launch()
        self.pg = None
        self.who = None
        self.scenario = ''
        self.step = ''
        self.vars = {}

    # ---- session / page
    def login(self, role, login):
        if self.who == role:
            return
        if self.pg:
            self.pg.context.close()
        sid = self.sessions.get(login)
        if not sid:
            raise RuntimeError('no user with login %s (role %s) in the Odoo 19 database' % (login, role))
        context = self.browser.new_context(viewport={'width': W, 'height': H}, locale='en-US')
        host = re.sub(r'^https?://', '', self.base).split(':')[0].split('/')[0]
        context.add_cookies([{'name': 'session_id', 'value': sid, 'domain': host, 'path': '/'}])
        self.pg = context.new_page()
        self.pg.set_default_timeout(READY_MS)
        self.pg.on('pageerror', lambda e: self.error('JS error: %s' % str(e)[:300]))
        self.pg.on('response', self._on_response)
        self.who = role
        self.pg.goto(self.base + '/odoo', timeout=90000, wait_until='commit')
        self.pg.wait_for_selector('.o_main_navbar', timeout=60000)

    def _on_response(self, response):
        url = response.url
        if '/web/dataset/call_kw' not in url and '/web/action/load' not in url:
            return
        try:
            if response.status >= 400:
                self.error('HTTP %s %s' % (response.status, url.split('/web/')[-1][:90]))
            else:
                body = response.json()
                if isinstance(body, dict) and body.get('error'):
                    data = body['error'].get('data') or {}
                    sent = (response.request.post_data or '')[:3500].replace('\n', ' ')
                    self.error('RPC error %s: %s | request: %s' % (url.split('/call_kw/')[-1][:80], (data.get('message') or body['error'].get('message') or '')[:200].replace('\n', ' '), sent))
        except Exception:
            pass

    def error(self, text):
        line = '%s | %s | %s' % (self.scenario, self.step, text)
        if line not in self.errors:
            self.errors.append(line)
            print('   !! ' + text[:170])

    def settle(self, extra=700):
        """Ready = the action is on screen and nothing is loading."""
        pg = self.pg
        pg.wait_for_selector('.o_main_navbar', timeout=READY_MS)
        try:
            pg.wait_for_selector('.o_action_manager .o_action, .o_action_manager .o_view_controller, .modal-content', timeout=READY_MS)    # an action opened as a dialog has no .o_action in the manager
            pg.wait_for_function("() => !document.querySelector('.o_loading_indicator, .o_blockUI, .o_list_view .o_list_loading, .o_view_controller.o_loading')", timeout=READY_MS)
        except Exception:
            self.error('screen did not settle (spinner or no action)')
        pg.wait_for_timeout(extra)
        # only real error dialogs: wizards and forms in a window (.o_technical_modal) are normal screens and stay open
        dialog = pg.locator('.modal:visible').filter(has_text=re.compile(r'^\s*(Odoo (Server )?Error|Access Error|Validation Error|User Error|Missing Record|Invalid Operation|Warning)', re.I))
        if pg.locator('.o_error_dialog').count() or dialog.count():
            box = pg.locator('.o_error_dialog').first if pg.locator('.o_error_dialog').count() else dialog.first
            self.error('error dialog: ' + ' '.join(box.inner_text().split())[:300])
            try:
                pg.keyboard.press('Escape')
                pg.wait_for_timeout(300)
            except Exception:
                pass

    # ---- navigation
    def url_for(self, go):
        """Odoo 12 hash style `action=$x&id=5&view_type=form` -> Odoo 19 path."""
        params = dict(p.split('=', 1) for p in go.split('&') if '=' in p)
        if 'action' in params:
            action = params['action']
            if re.match(r'^[a-z_0-9]+\.[A-Za-z_0-9.]+$', action):
                action = map_xmlid(action)
            path = '/odoo/action-%s' % action
            if params.get('id'):
                path += '/%s' % params['id']
            elif params.get('view_type') and params['view_type'] != 'list':
                path += '?view_type=%s' % params['view_type']
            return path
        if 'model' in params:
            return '/odoo/%s/%s' % (params['model'], params.get('id', 'new'))
        raise RuntimeError('cannot translate go: ' + go)

    def go(self, go):
        url = self.base + self.url_for(go)
        for attempt in (1, 2):
            try:
                self.pg.goto(url, timeout=45000, wait_until='commit')
                break
            except Exception:
                if attempt == 2:
                    raise
        self.settle(1200)

    def kw(self, model, method, args=None, kwargs=None):
        return self.pg.evaluate("""async ([model, method, args, kwargs]) => {
            const r = await fetch('/web/dataset/call_kw/' + model + '/' + method, {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {model, method, args, kwargs}})});
            const j = await r.json(); if (j.error) throw new Error(j.error.data ? j.error.data.message : 'rpc error'); return j.result; }""",
                               [model, method, args or [], kwargs or {}])

    # ---- steps
    def sub(self, text):
        return string.Template(str(text)).safe_substitute(self.vars)

    def shot(self, spec, scenario_name):
        name = spec['name']
        target = os.path.join(self.out_dir, scenario_name, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        pg = self.pg
        if spec.get('crop'):
            crop = SELECTOR_MAP.get(self.sub(spec['crop']), self.sub(spec['crop']))
            if 'modal' in crop:      # Odoo 19: take the dialog that is on screen now (the first match can be a hidden or closing one)
                crop = '.modal ' + crop if not crop.startswith('.modal ') else crop
                pg.wait_for_timeout(600)
                try:
                    box = pg.locator(crop).last.bounding_box(timeout=5000)     # a clip of the page: no wait for the element to be 'stable'
                    pg.screenshot(path=target, clip={'x': max(box['x'], 0), 'y': max(box['y'], 0), 'width': box['width'], 'height': box['height']})
                except Exception as error:
                    self.error('dialog crop failed (%s), full page taken' % str(error).splitlines()[0][:80])
                    pg.screenshot(path=target)
            else:
                pg.locator(crop).first.screenshot(path=target)
        elif spec.get('clip'):
            x, y, w, h = spec['clip']
            pg.screenshot(path=target, clip={'x': x, 'y': y, 'width': w, 'height': h})
        elif spec.get('mode') == 'tall':
            height = pg.evaluate("() => { const c = document.querySelector('.o_content');"
                                 " return Math.ceil((c ? c.getBoundingClientRect().top + c.scrollHeight : document.body.scrollHeight) + 10); }")
            pg.set_viewport_size({'width': W, 'height': max(H, min(height, 4000))})
            pg.wait_for_timeout(600)
            pg.screenshot(path=target)
            pg.set_viewport_size({'width': W, 'height': H})
        else:
            pg.screenshot(path=target)
        discard = pg.locator('.o_form_button_cancel:visible')
        if discard.count():
            discard.first.click()
            pg.wait_for_timeout(500)
        return target

    def run_step(self, st, roles, scenario_name, old_dir):
        if time.time() > self.deadline:
            raise RuntimeError('time budget of %d s used up' % SCENARIO_SECONDS)
        pg = self.pg
        if 'as' in st:
            role = st['as']
            if role not in roles:
                raise RuntimeError('role "%s" is not in the guide users file' % role)
            self.login(role, roles[role])
        if 'go' in st:
            self.go(self.sub(st['go']))
        for sel in ([st['click']] if isinstance(st.get('click'), str) else st.get('click') or []):
            try:
                sel = SELECTOR_MAP.get(self.sub(sel), self.sub(sel))
                target = pg.locator(self.sub(sel)).first
                button = target.locator('button')
                if re.search(r'td(:nth-child\(\d+\))?$', self.sub(sel)) and button.count():
                    button.first.click(timeout=5000)      # a list cell with a button: click the button, not the middle of the (wider) cell
                else:
                    target.click(timeout=5000)
            except Exception:
                print('   (click skipped: %s)' % sel)
            self.settle(500)
        if 'unfilter' in st:
            facet = pg.locator(".o_searchview_facet:has-text('%s') .o_facet_remove" % self.sub(st['unfilter']))
            if facet.count():
                facet.first.click()
                self.settle(500)
        for item in st.get('search') or []:
            text, field = self.sub(item).split('|')
            pg.click('.o_searchview_input')
            pg.keyboard.type(text)
            pg.wait_for_timeout(500)
            try:
                pg.locator('.o_searchview_autocomplete').get_by_text(re.compile(r'Search\s+%s' % re.escape(field), re.I)).first.click(timeout=5000)
            except Exception as error:
                print('   (search skipped: %s: %s)' % (item, str(error).splitlines()[0][:120]))
                pg.fill('.o_searchview_input', '')
            self.settle(500)
        for sel, value in (st.get('fill') or {}).items():
            real = SELECTOR_MAP.get(self.sub(sel), self.sub(sel))
            try:
                pg.fill(real, self.sub(value), timeout=5000)
                pg.keyboard.press('Tab')      # Odoo 19 commits a field on blur / change
            except Exception as error:
                print('   (fill skipped: %s: %s)' % (sel, str(error).splitlines()[0][:100]))
            self.settle(500)
        for sel, label in (st.get('select') or {}).items():
            real = SELECTOR_MAP.get(self.sub(sel), self.sub(sel))
            try:
                if pg.locator(real).first.evaluate('e => e.tagName') == 'SELECT':
                    pg.select_option(real, label=self.sub(label), timeout=5000)
                else:      # a field that is a select in Odoo 12 and a plain input in 19 (month names -> month number)
                    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    text = self.sub(label)
                    pg.fill(real, str(months.index(text) + 1) if text in months else text, timeout=5000)
                    pg.keyboard.press('Tab')
            except Exception as error:
                print('   (select skipped: %s: %s)' % (sel, str(error).splitlines()[0][:100]))
            self.settle(500)
        if 'wait' in st:
            pg.wait_for_timeout(min(int(st['wait']), 1500))
        if 'rpc' in st:
            print('   (rpc step skipped: nothing is written)')
        if 'shot' in st:
            target = self.shot(st['shot'], scenario_name)
            old = os.path.join(old_dir, st['shot']['name'])
            if os.path.exists(old):
                compose(old, target, os.path.join(self.compare_dir, scenario_name, st['shot']['name']))
                print('   shot %-28s compare: %s' % (st['shot']['name'], os.path.relpath(os.path.join(self.compare_dir, scenario_name, st['shot']['name']), REPO)))
            else:
                print('   shot %-28s (no Odoo 12 picture to compare)' % st['shot']['name'])

    def resolve_vars(self, scenario, roles):
        self.vars = {}
        for name, spec in (scenario.get('vars') or {}).items():
            if 'xmlid' in spec:
                # users may not read ir.model.data: the id is mapped and a missing action shows as an error on the screen
                self.vars[name] = map_xmlid(spec['xmlid'])
            elif 'search' in spec:
                if spec.get('as'):
                    self.login(spec['as'], roles[spec['as']])
                elif not self.pg:
                    first = next((st['as'] for st in scenario['steps'] if 'as' in st), None)
                    self.login(first, roles[first])
                model, domain = spec['search']
                ids = self.kw(model, 'search', [domain], {'limit': 1, 'order': spec.get('order', 'id desc')})
                if not ids:
                    raise RuntimeError('fixture %s: no %s matches %s (it would be created in Odoo 12; nothing is created here)' % (name, model, domain))
                self.vars[name] = ids[0]
            else:
                self.vars[name] = spec

    def run_scenario(self, path, roles):
        rel = os.path.relpath(path, SCENARIOS)
        module = rel.split(os.sep)[0]
        scenario = yaml.safe_load(open(path, encoding='utf-8'))
        scenario_name = os.path.splitext(rel)[0].replace(module + os.sep, '', 1)
        old_dir = os.path.join(ODOO12, 'addons', module, 'guides', scenario['category'], 'img')
        self.scenario, self.who = scenario_name, None
        self.deadline = time.time() + SCENARIO_SECONDS
        started = time.time()
        print(scenario_name)
        try:
            self.step = 'vars'
            self.resolve_vars(scenario, roles)
            for index, st in enumerate(scenario['steps'], 1):
                self.step = 'step %d %s' % (index, next(iter(k for k in st if k in ('as', 'go', 'click', 'search', 'shot', 'fill', 'select', 'unfilter', 'wait')), '?'))
                self.run_step(st, roles, scenario_name, old_dir)
        except Exception as error:
            self.error('SCENARIO STOPPED: %s: %s' % (type(error).__name__, str(error).splitlines()[0][:200]))
        finally:
            print('   (%d s)' % (time.time() - started))
            if self.pg:
                self.pg.context.close()
                self.pg = None

    def close(self):
        self.browser.close()
        self.p.stop()


def compose(old, new, out):
    """Odoo 12 picture above, Odoo 19 picture below, both labelled, scaled to the same width."""
    a, b = Image.open(old).convert('RGB'), Image.open(new).convert('RGB')
    width = max(a.width, b.width)
    parts = []
    for label, img in (('ODOO 12 (guide picture)', a), ('ODOO 19', b)):
        if img.width != width:
            img = img.resize((width, round(img.height * width / img.width)))
        bar = Image.new('RGB', (width, 26), (40, 40, 40))
        ImageDraw.Draw(bar).text((8, 7), label, fill=(255, 255, 255))
        parts.append((bar, img))
    sheet = Image.new('RGB', (width, sum(26 + i.height + 6 for _, i in parts)), (255, 255, 255))
    y = 0
    for bar, img in parts:
        sheet.paste(bar, (0, y)); sheet.paste(img, (0, y + 26)); y += 26 + img.height + 6
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*')
    ap.add_argument('--db', default='odoo19_dev')
    ap.add_argument('--url', default=os.environ.get('ODOO19_URL', 'http://172.30.0.4:8069'))
    ap.add_argument('--module', default='kderp_hr_attendance')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--fresh', action='store_true', help='create new sessions even when the cached ones exist')
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(SCENARIOS, args.module, '**', '*.yaml'), recursive=True))
    files = [f for f in files if not args.names or any(n in f for n in args.names)]
    if args.list:
        print('\n'.join(os.path.relpath(f, SCENARIOS) for f in files))
        return 0
    roles = role_logins()
    used = set()
    for f in files:
        text = open(f, encoding='utf-8').read()
        used |= set(re.findall(r'(?:^|\s)as:\s*([^\n#]+?)\s*(?:#.*)?$', text, re.M))
    logins = {roles[r] for r in used if r in roles}
    os.makedirs(TEMP, exist_ok=True)
    cache = os.path.join(TEMP, 'shoot19_sessions.json')
    sessions = {}
    if not args.fresh and os.path.exists(cache):
        cached = json.load(open(cache))
        if cached.get('db') == args.db:
            sessions = cached.get('sessions', {})
    if not logins <= set(sessions):
        print('creating sessions for %d logins (one `odoo shell`, about 15 s) ...' % len(logins))
        sessions = make_sessions(args.db, logins)
        json.dump({'db': args.db, 'sessions': sessions}, open(cache, 'w'))
        os.chmod(cache, 0o600)
    errors = []
    shooter = Shooter(args.url, args.db, sessions, os.path.join(TEMP, 'shots19'), os.path.join(TEMP, 'compare'), errors)
    try:
        for f in files:
            shooter.run_scenario(f, roles)
    finally:
        shooter.close()
    open(os.path.join(TEMP, 'shoot19_errors.txt'), 'w').write('\n'.join(errors) + ('\n' if errors else ''))
    print('\n%d UI errors (temp/shoot19_errors.txt); pictures in temp/shots19, comparisons in temp/compare' % len(errors))
    return 0


if __name__ == '__main__':
    sys.exit(main())

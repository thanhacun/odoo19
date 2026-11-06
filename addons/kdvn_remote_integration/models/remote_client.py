"""Direct JSON-RPC client for the remote (KDERP, Odoo 12) server.

Port of kderp_remote_integration 12.0.1.0.1 (same behaviour, same parameter names `kderp_remote.*`).

Two logins, chosen by the kind of call:
  * WRITER: every write, and the reads of a task that needs the writer's wide visibility.
  * READER: plain reads. If no Reader is entered the Writer is used for reads too.
The client enforces it: a write NEVER uses the Reader, whatever rights that login has on the remote.

Safety: a write needs a task name (`advance`, `staff_location`, ...) and is refused (RemoteNotLive) unless the live switch of that
task is ON, so dry run is the default and a restored copy of the database can never change the remote server.
Credentials live in ir.config_parameter (`kderp_remote.*`, system admins only).
"""
import logging

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM = 'kderp_remote.'
# Methods that change data on the remote. Anything else is treated as a read.
WRITE_METHODS = {'create', 'write', 'unlink', 'copy', 'name_create', 'toggle_active'}
TASKS = [('advance', 'Advance requests'), ('staff_location', 'Staff locations')]
TIMEOUT = 30
# Models whose rights the settings page reports for each login (information only)
WATCHED_MODELS = ['kderp.advance.payment', 'kderp.hr.employee.location', 'hr.employee', 'account.analytic.account']


class RemoteNotLive(UserError):
    """A write was attempted while the live switch of its task is off."""


class KderpRemoteClient(models.AbstractModel):
    _name = 'kderp.remote.client'
    _description = 'Direct JSON-RPC client for the remote server'

    # ------------------------------------------------------------------ settings
    @api.model
    def _get_config(self, account, override=None):
        """Saved settings for `account` ('reader' or 'writer'). `override` (non-empty values only) replaces them: used by the Test
        button before saving. A Reader that is not set up falls back to the Writer."""
        icp = self.env['ir.config_parameter'].sudo()
        override = {k: v.strip() for k, v in (override or {}).items() if v and v.strip()}

        def pick(key):
            return override.get(key) or (icp.get_param(PARAM + key) or '').strip()

        cfg = {'url': pick('url'), 'db': pick('db'), 'login': pick(account + '_login'),
               'password': pick(account + '_password'), 'account': account}
        if account == 'reader' and not (cfg['login'] and cfg['password']):
            cfg.update({'login': pick('writer_login'), 'password': pick('writer_password'), 'account': 'writer'})
        missing = [k for k in ('url', 'db', 'login', 'password') if not cfg[k]]
        if missing:
            raise UserError(_(
                "Remote server settings are incomplete for the %(account)s login (missing: %(missing)s). "
                "Fill them in Settings > Remote Server Connection.", account=cfg['account'], missing=', '.join(missing)))
        cfg['url'] = cfg['url'].rstrip('/')
        return cfg

    @api.model
    def is_live(self, task):
        """True only when real writes of this task are switched on (production only)."""
        return (self.env['ir.config_parameter'].sudo().get_param(PARAM + 'live.' + task) or '') == 'True'

    # ------------------------------------------------------------------ transport
    @api.model
    def _rpc(self, cfg, service, method, args):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                   'params': {'service': service, 'method': method, 'args': args}}
        try:
            resp = requests.post(cfg['url'] + '/jsonrpc', json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            # Never log the payload: it contains the password.
            _logger.warning("Remote server %s unreachable: %s", cfg['url'], e.__class__.__name__)
            raise UserError(_("Could not reach the remote server (%s).", e.__class__.__name__)) from e
        if data.get('error'):
            err = data['error'].get('data') or {}
            raise UserError(_("The remote server refused the request: %s",
                              err.get('message') or data['error'].get('message')))
        return data.get('result')

    # uid per (server, db, login) for the life of the process: a uid does not depend on the password, and a wrong password is
    # still refused by every execute_kw, so this only saves one round trip per call.
    _uids = {}

    @api.model
    def _login(self, cfg, force=False):
        key = (cfg['url'], cfg['db'], cfg['login'])
        if force or key not in self._uids:
            uid = self._rpc(cfg, 'common', 'login', [cfg['db'], cfg['login'], cfg['password']])
            if not uid:
                self._uids.pop(key, None)
                raise UserError(_("The remote server did not accept the %s login.", cfg.get('account', '')))
            self._uids[key] = uid
        return self._uids[key]

    # ------------------------------------------------------------------ public API
    @api.model
    def execute(self, model, method, args=None, kwargs=None, account=None, task=None, _cfg=None):
        """execute_kw on the remote.

        Reads run with `account` ('reader' by default; pass 'writer' for a task that needs the writer's visibility).
        A write needs `task` and raises RemoteNotLive unless that task's live switch is on; it always uses the Writer.
        Returns whatever the remote returns."""
        if method in WRITE_METHODS:
            if not task:
                raise UserError(_("Internal error: a write to the remote server must name its task."))
            if not self.is_live(task):
                raise RemoteNotLive(_("Writing to the remote server is switched off (dry run)."))
            account = 'writer'
        cfg = _cfg or self._get_config(account or 'reader')
        uid = self._login(cfg)
        return self._rpc(cfg, 'object', 'execute_kw',
                         [cfg['db'], uid, cfg['password'], model, method, args or [], kwargs or {}])

    @api.model
    def test_connection(self, override=None):
        """Read-only check used by the settings button.
        Returns {'version', 'accounts': {name: facts}, 'live': {task: bool}}.

        Each configured login is tested separately (what is typed on the page counts, nothing is saved). The Reader is also checked
        for write rights on the remote, to tell you when it could do more than it should (the client never writes with it anyway)."""
        facts = {}
        version = ''
        for account in ('reader', 'writer'):
            try:
                cfg = self._get_config(account, override)
            except UserError:
                facts[account] = None          # not set up
                continue
            if account == 'reader' and cfg['account'] == 'writer':
                facts[account] = {'same_as_writer': True}
                continue
            version = version or (self._rpc(cfg, 'common', 'version', []) or {}).get('server_version') or ''
            uid = self._login(cfg, force=True)

            def run(m, meth, a, kw=None, cfg=cfg, uid=uid):
                return self._rpc(cfg, 'object', 'execute_kw', [cfg['db'], uid, cfg['password'], m, meth, a, kw or {}])

            me = run('res.users', 'read', [[uid], ['login', 'location_user_id']])[0]
            rights = {}
            for model in WATCHED_MODELS:
                rights[model] = ''.join(
                    letter if run(model, 'check_access_rights', [op], {'raise_exception': False}) else '-'
                    for letter, op in (('r', 'read'), ('c', 'create'), ('w', 'write'), ('u', 'unlink')))
            facts[account] = {'uid': uid, 'login': me.get('login'),
                              'location': me.get('location_user_id') and me['location_user_id'][1] or '',
                              'rights': rights}
        if facts['writer'] is None:
            raise UserError(_("The Writer login is not set up. Fill it in Settings > Remote Server Connection."))
        return {'version': version, 'accounts': facts, 'live': {task: self.is_live(task) for task, label in TASKS}}

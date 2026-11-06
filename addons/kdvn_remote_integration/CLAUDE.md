# kdvn_remote_integration (Odoo 19)
Port of ~/odoo12/addons/kderp_remote_integration (reference only; its CLAUDE.md explains the Reader/Writer rule, tasks and dry run, all unchanged here).
When Thanh changes the Odoo 12 module, mirror the change here.
- Same model `kderp.remote.client` and parameters `kderp_remote.*`; settings are fields on `res.config.settings` (prefix `kderp_remote_`), page = Settings > Remote Server Connection.
- Passwords never go to the browser (get_values returns '', set_values writes only when typed). Test button opens a dialog (`kderp.remote.test.result`) instead of the Odoo 12 notification wizard.
- No post_init_hook: Odoo 19 has no old keys to take over.
- Tests: `docker exec odoo19 odoo -c <conf with the worktree addons path> -d kdvn_test -u kdvn_remote_integration --test-tags /kdvn_remote_integration --stop-after-init --http-port=8079 --gevent-port=8082` (18 tests, fake transport).

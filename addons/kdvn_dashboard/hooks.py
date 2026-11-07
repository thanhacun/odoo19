import logging

_logger = logging.getLogger(__name__)


def post_init_set_home_action(env):
    """On install: make the dashboard the home screen of every active internal user
    who has no home action yet. Users who chose another home action keep it."""
    action = env.ref('kdvn_dashboard.action_kderp_dashboard')
    users = env['res.users'].with_context(active_test=True).search([
        ('share', '=', False), ('action_id', '=', False)])
    users.write({'action_id': action.id})
    _logger.info("KDERP Dashboard set as home action for %s users.", len(users))

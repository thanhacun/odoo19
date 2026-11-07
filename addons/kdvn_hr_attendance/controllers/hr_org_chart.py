from odoo import http
from odoo.http import request

from odoo.addons.hr_org_chart.controllers.hr_org_chart import HrOrgChartController


class KdvnHrOrgChartController(HrOrgChartController):
    """Port of Odoo 12 controllers/hr_org_chart.py. Our staff have two reporting lines (Functional = parent_id, Administrative = admin_manager_id)
    and many have left: the org chart hides staff who are not working (except codes S9..., the top management), and returns the
    Administrative line as `admin`, in the same shape as the Functional one (the tabs of the widget, static/src/org_chart)."""

    def _is_shown(self, employee):
        return employee.working or (employee.code or '')[:2] == 'S9'

    def _only_shown(self, items):
        """items: dicts built by _prepare_employee_data."""
        employees = request.env['hr.employee.public'].sudo().browse([item['id'] for item in items])
        shown = set(employees.filtered(self._is_shown).ids)
        return [item for item in items if item['id'] in shown]

    @http.route()
    def get_org_chart(self, employee_id, new_parent_id=None, **kw):
        values = super().get_org_chart(employee_id, new_parent_id=new_parent_id, **kw)
        if not values.get('self'):      # no access or no employee: the core answer
            return values
        values['managers'] = self._only_shown(values['managers'])
        values['children'] = self._only_shown(values['children'])
        values['admin'] = self._get_admin_branch(request.env['hr.employee.public'].sudo().browse(values['self']['id']))
        return values

    # ---- Administrative line
    def _admin_children_of(self, employees):
        return request.env['hr.employee.public'].sudo().search([('admin_manager_id', 'in', employees.ids)]).filtered(self._is_shown)

    def _get_admin_branch(self, employee):
        ancestors, current, seen = request.env['hr.employee.public'].sudo(), employee, set()
        while current.admin_manager_id and current.admin_manager_id.id not in seen:
            seen.add(current.admin_manager_id.id)
            ancestors += request.env['hr.employee.public'].sudo().browse(current.admin_manager_id.id)
            current = ancestors[-1]
        ancestors = ancestors.filtered(self._is_shown)

        def sub_counts(emp):
            direct = self._admin_children_of(emp)
            total, frontier, visited = len(direct), direct, set(direct.ids) | {emp.id}
            while frontier:
                frontier = self._admin_children_of(frontier).filtered(lambda c: c.id not in visited)
                visited |= set(frontier.ids)
                total += len(frontier)
            return len(direct), total

        def data(emp):
            result = self._prepare_employee_data(emp)
            result['direct_sub_count'], result['indirect_sub_count'] = sub_counts(emp)
            return result

        return dict(
            self=data(employee),
            managers=list(reversed([data(a) for idx, a in enumerate(ancestors) if idx < self._managers_level])),
            managers_more=len(ancestors) > self._managers_level,
            children=[data(c) for c in self._admin_children_of(employee)],
        )

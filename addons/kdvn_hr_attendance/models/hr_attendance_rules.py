import copy as _copy
import datetime
import time as _time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class HrAttendanceRules(models.Model):
    """Rules part of hr.attendance (stage A1): the merged rules of an employee on a day, holidays, Saturday working.
    The attendance record itself (fields, status, OT) comes with stages A2 / A3."""
    _name = 'hr.attendance'
    _inherit = ['hr.attendance', 'hr.mixin']   # methods ported literally from kderp_hr_attendance 12.0.1.0.11

    at_date = fields.Date('AT date', index=True, help='Attendance day (day starts at the policy hour, see hr.mixin.get_at_date)')

    # ===== holidays =====
    def _is_holiday(self, a_date):
        """
        Return holiday code for the given date.

        Returns:
            False : Normal working day
            'H'    : Sunday, substitute holiday or non-working Saturday
            'SH'   : Special Holiday (Public Holiday)
            'OH'   : Other Holiday
        """
        if not a_date:
            return False

        holiday_type = self.env["hr.holidays.public"].is_public_holiday(
            a_date,
            employee_id=self.employee_id.id if self.employee_id else None,
        )

        holiday_map = {
            1: "SH",
            2: "OH",
            3: "H",
        }

        if holiday_type in holiday_map:
            return holiday_map[holiday_type]

        if a_date.weekday() == 6:
            return "H"

        if (
            a_date.weekday() == 5
            and self.is_no_sat_working(self.employee_id, a_date)
        ):
            return "H"

        return False


    # ===== rules =====
    def _at_rules(self, employee_id=None, at_date=None, get_rule_desc=False):
        """Memoised wrapper of _at_rules_compute: one transaction asks the same (employee, section, company, date) 5-8 times
        per attendance. The memo lives on the cursor (never shared between transactions), is dropped when a rule or company
        is written (clear_at_rules_memo) and expires after 60 s for long-lived cursors."""
        emp = employee_id if employee_id else (self.employee_id or self.env.user.employee_id)
        if isinstance(emp, int):
            emp = self.env['hr.employee'].browse(emp)
        if not at_date or type(at_date) is not datetime.date:
            at_date = self.at_date or fields.Date.context_today(self)
        memo = self.env.cr.cache.setdefault('kderp_at_rules_memo', {})
        key = (emp.id, emp.admin_dept_id.id if emp.admin_dept_id else 0, emp.company_id.id, at_date, bool(get_rule_desc))
        hit = memo.get(key)
        now = _time.monotonic()
        if hit is None or now - hit[0] > 60:
            hit = (now, self._at_rules_compute(emp, at_date, get_rule_desc))
            memo[key] = hit
        return _copy.deepcopy(hit[1])

    def clear_at_rules_memo(self):
        # also drops the early-offset memo of hr.mixin.get_early_offset (depends on the rules and on early_in requests)
        self.env.cr.cache.pop('kderp_at_rules_memo', None)
        self.env.cr.cache.pop('kderp_early_offset_memo', None)
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)  # holiday list depends on by_employee calendar rules

    def _at_rules_compute(self, employee_id=None, at_date=None, get_rule_desc=False):
        """[Attendance rules dictionary ]

        Args:
            employee_id ([type], optional): id. Defaults to None.
            at_date: date type defaults to None
            get_rule_desc [Boolean], optional): Defautls to False: if True, 
            return active rule set name/desc (for display rules in web page)

        Returns:
            [dict]: [rules] active attendance rules during this at_date
        """
        # TODO [X]: validation dates
        # TODO [X]: AT Policy
        # TODO [X]: force_apply
        # self.ensure_one()
        if not employee_id:
            emp_id = self.employee_id or self.env.user.employee_id
        else:
            emp_id = employee_id

        if isinstance(emp_id, int):
            emp_id = self.env['hr.employee'].browse(emp_id)

        at_rules = {}
        policy_keys = [('date_start', 'day'), ('day_start', 'hour'), ('working_start', 'hour'), ('late_in', 'minute'), ('early_out', 'minute'), ('absence', 'minute'), ('special_ot_hour', 'duration')]
        rule_keys = [('ot_apply_rule', ''), ('wd_allowed_ot', 'hour'), ('hd_allowed_ot', 'hour'), ('child_care_period', ''), ('early_offset', 'minutes'), ('allow_morning_ot', ''),
                     ('override_day_start', 'hour'), ('override_working_start', 'hour'), ('override_late_in', 'minute'), ('override_early_out', 'minute'), ('override_absence', 'minute'), 
                     ('valid_start', ''), ('valid_stop', ''), ('force_apply', ''), ('resource_calendar_id', ''), ('ot_hour_allowed', 'hours'), ('no_need_check', ''), ('no_checkin', '')]
        force_apply_keys = [('wd_allowed_ot', 'hour'), ('hd_allowed_ot', 'hour')]
        # poicy_defaults = [21, 6, 8, 5, 5, 30, [22, 6]]
        default_rc = self.env.company.resource_calendar_id
        default_rc_rule = (default_rc.id, default_rc.name) if default_rc else None
        rule_defaults = ['actual', 0, 0, False, 0, True, 0,0, 0, 0, 0, None, None, False, default_rc_rule, 0, False, False]
        # at_policy = dict(zip(policy_keys, poicy_defaults))
        at_rules = dict(zip(list(map(lambda k: k[0], rule_keys)), rule_defaults))

        if not at_date or type(at_date) is not datetime.date:
            at_date = self.at_date or fields.Date.context_today(self)
        # rules_domain = [('active', '=', True), ('valid_start', '<=', at_date), '|', ('valid_stop', '=', False), ('valid_stop', '>=', at_date),
        #                 '|', '|', ('employee_ids', '=', emp_id.id), ('department_ids', '=', emp_id.admin_dept_id.id if emp_id.admin_dept_id else 0), ('company_id', '=', emp_id.company_id.id)]
        rules_domain = ["&","&","&", ["active","=",True],["valid_start","<=",at_date],"|",["valid_stop","=",False],["valid_stop",">=",at_date],
                        "|","|",["employee_ids","=",emp_id.id],["department_ids","=",emp_id.admin_dept_id.id if emp_id.admin_dept_id else 0],["company_id","=",emp_id.company_id.id]]
        # TODO [X]: rules ordered by id - find a better way => using sequence
        rules = self.env['hr.attendance.rule'].search(rules_domain, order='sequence').filtered(lambda r: r.state == 'done')
        # all_rules = [[r[k] for k in [t[0] for t in rule_keys]] for r in rules]

        # Compute rule set name/decsription for showing in UI
        rule_desc = {}
        # TODO [X]: check override rules for special late_in; early_out; absence
        override_rule = rules.filtered(lambda r: any([r.override_late_in, r.override_early_out, r.override_absence, r.override_day_start, r.override_working_start]))
        already_force_apply = False
        for i, rule in enumerate(rules):
            rule = rules[i]
            # !NOTE: no need to repeat policy for every rule
            if i == 0:
                for key in policy_keys:
                    if key[0] == 'special_ot_hour':
                        special_ot_hour = list(map(lambda e: int(e), rule[key[0]].split(':')))
                        at_rules[key[0]] = special_ot_hour
                    else:
                        if override_rule and key[0] in ['late_in', 'early_out', 'absence', 'day_start', 'working_start'] and override_rule.filtered(lambda r: f'override_{key[0]}' in r):
                            for r in override_rule:
                                if f'override_{key[0]}' in r:
                                    at_rules[key[0]] = r[f'override_{key[0]}'] if r[f'override_{key[0]}'] else rule[key[0]]
                        else:
                            at_rules[key[0]] = rule[key[0]]
                    rule_desc[key[0]] = ('Policy', key[1])

            if rule.force_apply:
                for key in force_apply_keys:
                    at_rules[key[0]] = rule[key[0]] or False
                    rule_desc[key[0]] = (rule.name, key[1])
                already_force_apply = True
            else:
                rule_keys = [r for r in rule_keys if r not in force_apply_keys] if already_force_apply else rule_keys
                for key in rule_keys:
                    if rule[key[0]]:
                        if key[0] != 'allow_morning_ot':
                            at_rules[key[0]] = rule[key[0]]
                            rule_desc[key[0]] = (rule.name, key[1])
                        else:
                            at_rules[key[0]] = True
                            rule_desc[key[0]] = (rule.name, 'Yes')
                    else:
                        if key[0] == 'allow_morning_ot':
                            at_rules[key[0]] = False
                            rule_desc[key[0]] = (rule.name, 'No')
                        if key[0] not in rule_desc:
                            rule_desc[key[0]] = ('', '')

        # set value for child_care !NOTE: better to store this value in database but not in source code like this
        if at_rules.get('child_care_period', False):
            at_rules['child_care_period'] = 60
            rule_desc['child_care_period'] = (rule.name, 'minute')

        if at_rules['wd_allowed_ot'] == 0:
            at_rules['ot_apply_rule'] = False
            at_rules['allow_morning_ot'] = False

        rc_rule = at_rules.get('resource_calendar_id', None)
        if rc_rule and type(rc_rule) != tuple:  # by default, rc_rule already is a tuple => need to check before conversion
            at_rules['resource_calendar_id'] = (at_rules['resource_calendar_id'].id, at_rules['resource_calendar_id'].name)

        if get_rule_desc:
            return rule_desc
        return at_rules

    def is_no_sat_working(self, employee_id, at_date):
        """
        Check if the employee is working on Saturday
        """
        start_dt = self.get_start_dt(at_date, for_month=True)
        # default_rc_id = self.env.company.resource_calendar_id
        # TODO [X]: check cases that return many rules of resource_calendar
        rc_domain = [('state', '=', 'done'), ('valid_start', '<=', start_dt), ('resource_calendar_id', '!=', False),
                     '|', ('employee_ids', '=', employee_id.id), ('company_id', '!=', False)]
        rc_ids = self.env['hr.attendance.rule'].search(rc_domain)
        if not rc_ids:
            return False   # Odoo 12 raised ValueError (min of nothing) when no calendar rule exists; nothing to compare with
        # Return the one that having valid_start closest to start_dt (valid_start is always <= start_dt in this case)
        applied_rc_id = min(rc_ids, key=lambda r: start_dt - r.valid_start)
        sat_working_periods = applied_rc_id.resource_calendar_id.attendance_ids.filtered(lambda a: a.dayofweek == '5')
        is_no_sat_working_apply = not bool(sat_working_periods)
        # is_no_sat_working_apply = bool(applied_rc_id and applied_rc_id.resource_calendar_id.id != default_rc_id.id)
        return is_no_sat_working_apply
    

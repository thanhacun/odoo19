# from calendar import day_abbr, leapdays
from collections import defaultdict
import copy as _copy
import time as _time
import datetime
import calendar
import math
import json
import re
from dateutil.relativedelta import relativedelta
# from dateutil import tz
from pytz import utc
import pytz
import random
import requests
import logging
from itertools import chain
from time import process_time
from calendar import month_abbr
import psycopg2
from datetime import timezone, timedelta


# from werkzeug.routing import parse_converter_args

from odoo import models, fields, api, tools, _
# from odoo import exceptions
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_round
from odoo.osv import expression
# from odoo.tools.profiler import profile

from .rounding import roundPartial

vn_tz = pytz.timezone(' '.join(pytz.country_timezones('vn')))

# vn_tz = tz.gettz('Asia/Ho_Chi_Minh')
# utc = tz.gettz('UTC')
utc_diff = 7

_logger = logging.getLogger(__name__)


def summary_key(employee_id, at_year, at_month):
    """Id of hr.attendance.summary (a SQL view) and of hr.attendance.summary_id: employee_id * 10000 + months since Jan 2000.
    Same formula as the SQL in the views, the index and the migration. (Until 12.0.1.0.2 the id was employee*1000000 + year*100 + month,
    which overflows an integer from employee id 2147.)"""
    return int(employee_id) * 10000 + (int(at_year) - 2000) * 12 + int(at_month)


def summary_key_decode(key):
    employee_id, idx = divmod(int(key), 10000)
    return employee_id, 2000 + (idx - 1) // 12, (idx - 1) % 12 + 1



class KderpHrAttendanceSummary(models.Model):
    _name = 'hr.attendance.summary'
    _auto = False
    _description = "Monthly AT Summary"

    employee_id = fields.Many2one('hr.employee', readonly=True)
    department_id = fields.Many2one('hr.department', readonly=True)
    at_month = fields.Integer(readonly=True, group_operator='min')
    at_year = fields.Integer(readonly=True, group_operator='min')
    # AT
    late_in_count = fields.Integer(readonly=True)
    early_out_count = fields.Integer(readonly=True)
    forget_count = fields.Integer(readonly=True)
    attendance_count = fields.Float(readonly=True, digits=(3,1), string="Attendances")
    absence_count = fields.Float(readonly=True, digits=(3,1), string="Absence")
    leaves_count = fields.Float(readonly=True, digits=(3,1), string="Leaves")
    oh_count = fields.Float(readonly=True, digits=(3,1), string="Holidays")
    sh_count = fields.Float(readonly=True, digits=(3,1), string="Other special holidays")
    psh_count = fields.Float(readonly=True, digits=(3,1), string="Public holidays")
    ssh_count = fields.Float(readonly=True, digits=(3,1), string="Special holidays")
    working_days_sum = fields.Integer(readonly=True, string="Total working days")
    # OT
    wd_ot_sum = fields.Float(readonly=True)
    wd_st_sum = fields.Float(readonly=True)
    hd_ot_sum = fields.Float(readonly=True)
    hd_st_sum = fields.Float(readonly=True)
    ph_ot_sum = fields.Float(readonly=True)
    ph_st_sum = fields.Float(readonly=True)
    wd_sum = fields.Float(readonly=True)
    hd_sum = fields.Float(readonly=True)
    # allowed overtime
    allow_wd_overtime = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_wd_ot = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_wd_st = fields.Float(compute='_compute_allow_fields', readonly=True)
    # holiday overtime
    allow_hd_overtime = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_hd_ot = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_hd_st = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_ph_ot = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_ph_st = fields.Float(compute='_compute_allow_fields', readonly=True)
    # allowed ot by law
    allow_overtime_bylaw = fields.Float(compute='_compute_allow_fields', readonly=True)
    allow_ot_bylaw = fields.Float(compute='_compute_allow_fields', readonly=True)
    bonus_ot_hours = fields.Float(compute='_compute_allow_fields', readonly=True)
    bonus_ot_level = fields.Integer(compute='_compute_allow_fields', readonly=True, help='By definition, this level is from 0 ~ 10')
    # exceed
    exceed_wd_overtime = fields.Float(compute='_compute_allow_fields', readonly=True)
    exceed_hd_overtime = fields.Float(compute='_compute_allow_fields', readonly=True)
    exceed_ot_to_leave = fields.Float(compute='_compute_allow_fields', readonly=True)
    exceed_ot_subtitude = fields.Float(compute='_compute_allow_fields', digits=(3,1), readonly=True, search='_search_exceed_ot')

    # at_ids_list = fields.Text(readonly=True)
    # at_ids = fields.One2many('hr.attendance', compute='_compute_at_ids', readonly=True)
    at_ids = fields.One2many('hr.attendance', 'summary_id', readonly=True, context={'active_test': False})
    summary_for_at = fields.Html(compute='_compute_at_monthly_summary', readonly=True)
    # exceed_ot = fields.Float(compute='_compute_exceed_ot', digits=(3,1), readonly=True, search='_search_exceed_ot')
    month_dsp = fields.Char('Month', compute='_compute_month_display', readonly=True)
    need_hr_action = fields.Boolean(compute='_compute_need_hr_action', search='_search_need_hr_action', readonly=True)
    need_hr_action_explain = fields.Text(compute='_compute_need_hr_action', readonly=True)
    states_sync = fields.Boolean(readonly=True)
    working_total = fields.Float(readonly=True)
    by_request_absence_total = fields.Float(readonly=True)
    status_enough = fields.Boolean(readonly=True)
    sat_leave = fields.Boolean(readonly=True, help="Take a leave on SAT")
    sat_status = fields.Text(readonly=True)
    ah_count = fields.Float(readonly=True, digits=(3,1), string="Total AH")
    is_current = fields.Boolean(readonly=True, string="Is Current")
    show_current = fields.Boolean(readonly=True, string="Show Current")
    enough_attendance = fields.Boolean(readonly=True, string="Enough Attendance Records")
    finish_waiting = fields.Boolean(readonly=True, string="Finish Waiting for Reauests")
    not_enough_status = fields.Boolean(readonly=True, string="Not Enough AT status")


    _at_month_summary_unique = models.Constraint('unique(employee_id, at_year, at_month)', 'Employee, Month, Year')

    # def _month_ats(self):
    #     self.ensure_one()
    #     summary = self
    #     related_ats_domain = [('employee_id', '=', summary.employee_id.id), ('at_year', '=', summary.at_year), ('at_month', '=', summary.at_month)]
    #     return self.env['hr.attendance'].with_context(active_test=False).search(related_ats_domain)
    
    # @api.multi
    # def _compute_at_ids(self):
    #     for s in self:
    #         # s.at_ids = s._month_ats().mapped('id')
    #         s.at_ids = json.loads(s.at_ids_list)

    def _legacy_name_get(self):
        # The id encodes employee, year and month (summary_key): decode it instead of reading the view,
        # because the view aggregates the whole hr_attendance table for every lookup (~0.5 s per call).
        employees = self.env['hr.employee'].sudo()
        names = []
        for s in self:
            employee_id, year, month = summary_key_decode(s.id)
            names.append((s.id, 'Attendance of {}, {} for {}'.format(calendar.month_name[month], year, employees.browse(employee_id).name)))
        return names


    @api.depends_context("uid")
    def _compute_display_name(self):
        """Odoo 19 has no name_get(): display_name is computed. The Odoo 12 body is kept as _legacy_name_get (same strings)."""
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or ''

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = """
            CREATE OR REPLACE VIEW hr_attendance_summary AS
            (SELECT (att.employee_id::bigint * 10000 + (att.at_year - 2000) * 12 + att.at_month)::int AS id,  -- summary_key(): employee_id*10000 + months since Jan 2000 (fits an integer up to employee id 214,748); immutable so a read by id can use hr_attendance_summary_id_idx 
                -- row_number() OVER(ORDER BY att.employee_id, att.at_year, att.at_month) AS id, 
                att.employee_id employee_id, emp.admin_dept_id department_id, att.at_month at_month, att.at_year at_year,
                --JSON_AGG(att.id ORDER BY att.at_date) at_ids_list,
                ARRAY_AGG(att.id ORDER BY att.at_date) at_ids,
				SUM(late_in::int)::int late_in_count, SUM(early_out::int)::int early_out_count, SUM(COALESCE(wd_ot, 0)) wd_ot_sum, SUM(COALESCE(wd_st, 0)) wd_st_sum,
                SUM(COALESCE(hd_ot, 0)) hd_ot_sum, SUM(COALESCE(hd_st, 0)) hd_st_sum, SUM(COALESCE(ph_ot, 0)) ph_ot_sum, SUM(COALESCE(ph_st, 0)) ph_st_sum,
                SUM(COALESCE(wd_ot, 0) + COALESCE(wd_st, 0)) wd_sum, SUM(COALESCE(hd_ot, 0) + COALESCE(hd_st, 0) + COALESCE(ph_ot, 0) + COALESCE(ph_st, 0)) hd_sum,
                SUM(CASE WHEN 'L' = ANY(status.status) THEN 1 WHEN '1/2 L' = ANY(status.status) THEN 0.5 ELSE 0 END) leaves_count,
                SUM(CASE WHEN 'OH' = ANY(status.status) THEN 1 WHEN '1/2 OH' = ANY(status.status) THEN 0.5 ELSE 0 END) oh_count,
                SUM(CASE WHEN 'SH' = ANY(status.status) THEN 1 WHEN '1/2 SH' = ANY(status.status) THEN 0.5 ELSE 0 END) sh_count,
                SUM(CASE WHEN att.is_public_holiday = TRUE THEN 0 WHEN 'SH' = ANY(status.status) THEN 1 WHEN '1/2 SH' = ANY(status.status) THEN 0.5 ELSE 0 END) psh_count,
				SUM(CASE WHEN att.is_public_holiday != TRUE THEN 0 WHEN 'SH' = ANY(status.status) THEN 1 WHEN '1/2 SH' = ANY(status.status) THEN 0.5 ELSE 0 END) ssh_count,
                SUM(CASE WHEN 'O' = ANY(status.status) THEN 1 WHEN '1/2 O' = ANY(status.status) THEN 0.5 ELSE 0 END) attendance_count,
                SUM(CASE WHEN 'X' = ANY(status.status) THEN 1 WHEN '1/2 X' = ANY(status.status) THEN 0.5 ELSE 0 END) absence_count,
                -- COUNT(CASE WHEN EXTRACT(ISODOW FROM att.at_date) != 7 THEN True ELSE null END)::int - 2 working_days_sum,
                --(SELECT COUNT(*) - 2 FROM generate_series(MAX(att.start_date), MAX(att.end_date) - INTERVAL '1 day', '1 day') AS at_month_date WHERE EXTRACT(ISODOW FROM at_month_date) != 7) working_days_sum,
                (
					SUM(CASE WHEN 'L' = ANY(status.status) THEN 1 WHEN '1/2 L' = ANY(status.status) THEN 0.5 ELSE 0 END) + 
					SUM(CASE WHEN 'OH' = ANY(status.status) THEN 1 WHEN '1/2 OH' = ANY(status.status) THEN 0.5 ELSE 0 END) +
					SUM(CASE WHEN 'SH' = ANY(status.status) THEN 1 WHEN '1/2 SH' = ANY(status.status) THEN 0.5 ELSE 0 END) +
					SUM(CASE WHEN 'O' = ANY(status.status) THEN 1 WHEN '1/2 O' = ANY(status.status) THEN 0.5 ELSE 0 END) +
					SUM(CASE WHEN 'X' = ANY(status.status) THEN 1 WHEN '1/2 X' = ANY(status.status) THEN 0.5 ELSE 0 END)
				) working_days_sum,
				-- (SELECT COUNT(*) FROM generate_series(MIN(att.start_date), MAX(att.end_date) - INTERVAL '1 day', '1 day') AS at_month_date) - (SUM(CASE WHEN ARRAY['1/2 H', '1/2 AH'] && status.status::text[] THEN 0.5 WHEN ARRAY['H', 'AH'] && status.status::text[] THEN 1 ELSE 0 END)) working_days_sum,
                COUNT(CASE WHEN att.id IN 
                        (SELECT at_id FROM hr_attendance_request re JOIN hr_attendance_request_type rt ON re.sub_request_type_id=rt.id WHERE rt.code IN ('forget_in', 'forget_out')) 
                        THEN True ELSE Null END)::int forget_count,
				every(att.states_sync) as states_sync,
				SUM(CASE WHEN att.absence IS NULL THEN 1 WHEN att.absence = 'absence' THEN 0 ELSE 0.5 END) working_total,
                --SUM(CASE WHEN att.absence IS NULL THEN 0 WHEN att.absence = 'absence' THEN 1 ELSE 0.5 END) absence_total,
                SUM(CASE WHEN att.absence IS NULL THEN 
					(CASE WHEN ARRAY['1/2 L', '1/2 SH', '1/2 X'] && status.status::text[] THEN 0.5 WHEN ARRAY['L', 'X'] && status.status::text[] THEN 1 ELSE 0 END) 
					WHEN att.absence = 'absence' THEN 0 ELSE 
					(CASE WHEN ARRAY['L', 'X'] && status.status::text[] THEN 0.5 ELSE 0 END) END) by_request_absence_total,
                every(att.status_codes != '') status_enough,
                bool_or(CASE WHEN (att.at_day = 'Sat' AND (POSITION('L' IN att.status_codes) > 0 OR POSITION('1/2 L' IN att.status_codes) > 0)) THEN true ELSE false END ORDER BY att.at_date) sat_leave,
				JSON_AGG(CASE WHEN att.at_day = 'Sat' THEN att.status_codes END ORDER BY att.at_date)::text sat_status,
                SUM(CASE WHEN 'AH' = ANY(status.status) THEN 1 WHEN '1/2 AH' = ANY(status.status) THEN 0.5 ELSE 0 END) ah_count,
                every(att.start_date <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AND att.end_date > (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) is_current,
				every(att.start_date <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AND (DATE_TRUNC('month', att.end_date) + INTERVAL '1 month' - INTERVAL '1 day') > (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) show_current,
                MAX(att.end_date - att.start_date) = COUNT(att.id) enough_attendance,
                every((att.end_date + INTERVAL '1 day') <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) finish_waiting,
                SUM(CASE WHEN att.at_date <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date THEN (att.status_codes != '')::int ELSE 0 END) < (COUNT(CASE WHEN att.at_date <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date THEN att.id ELSE NULL END) - 2) not_enough_status
            FROM hr_attendance att
                LEFT JOIN LATERAL (SELECT array_agg(code.code) status FROM hr_attendance_kderp_base_code_rel status 
                        JOIN kderp_base_code code ON status.kderp_base_code_id=code.id WHERE status.hr_attendance_id = att.id) status ON true
                LEFT JOIN hr_employee emp ON att.employee_id = emp.id
			GROUP BY emp.admin_dept_id, emp.code, att.employee_id, att.at_month, att.at_year
            ORDER BY emp.code, emp.admin_dept_id, att.at_year DESC, att.at_month DESC)
        """
        self.env.cr.execute(query)
        # lets a read by summary id (list pages) touch only that month's attendances instead of all of them
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS hr_attendance_summary_id_idx ON hr_attendance
            (((employee_id::bigint * 10000 + (at_year - 2000) * 12 + at_month)::int))
        """)
    
    def _count_allow(self, actual_list, allow_number):
            """
                - Helper method
                return a list of number matched with actual_list to make sure 
                the total number of return list equal to allow_number
            """
            res = []
            if sum(actual_list) <= allow_number:
                res = actual_list
            else:
                # REF: https://stackoverflow.com/questions/3705670/best-way-to-create-a-reversed-list-in-python
                # reverse a list 
                for n in actual_list[::-1]:
                    if n >= allow_number - sum(res):
                        res.append(allow_number - sum(res))
                    else:
                        res.append(n)
                res.reverse()
            return res

    def _compute_allow_fields(self):
        for s in self:
            s.update(s._compute_allow())

    def _compute_allow(self):
        # TODO [X]: compute OT compensation for G8 employee:
        # - Apply for Working on Sat AH, Sunday and holidays
        # - compute by unit of half working day as normal day (08 ~ 17)
        self.ensure_one()
        date_start = self.env['hr.attendance'].at_policy()['date_start'] or 21
        s = self
        (allow_wd_overtime, allow_hd_overtime, allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st,
                    exceed_wd_overtime, exceed_hd_overtime, exceed_ot_to_leave, exceed_ot_subtitude, allow_overtime_bylaw, allow_ot_bylaw, bonus_ot_hours, bonus_ot_level) = (0,) * 16
        comp_categories = (s.employee_id.company_id or self.env.user.company_id).ot_comp_categories()
        if not (s.employee_id.category_ids & comp_categories):
            if s.wd_sum > 0 or s.hd_sum > 0:
                # allowed overtime
                end_date = datetime.date(s.at_year, s.at_month, date_start - 1)
                at_rules = self.env['hr.attendance']._at_rules(employee_id=s.employee_id.id, at_date=end_date)
                allow_wd_overtime = at_rules.get('wd_allowed_ot', 0)
                allow_hd_overtime = at_rules.get('hd_allowed_ot', 0)
                allow_overtime_bylaw = at_rules.get('ot_hour_allowed', 0)

                (allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st, allow_ot_bylaw) = (0,) * 7
                if allow_wd_overtime > 0:
                    (allow_wd_ot, allow_wd_st) = self._count_allow([s.wd_ot_sum, s.wd_st_sum], allow_wd_overtime)
                if allow_hd_overtime >0:
                    (allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st) = self._count_allow([s.hd_ot_sum, s.hd_st_sum, s.ph_ot_sum, s.ph_st_sum], allow_hd_overtime)

                # exceed overtime
                exceed_wd_overtime = 0 if s.wd_sum <= allow_wd_overtime else s.wd_sum - allow_wd_overtime
                exceed_hd_overtime = 0 if s.hd_sum <= allow_hd_overtime else s.hd_sum - allow_hd_overtime

                # exceed OT to leaves
                exceed_hours = exceed_wd_overtime + exceed_hd_overtime
                if exceed_hours > 0:
                    exceed_ot_to_leave = roundPartial(exceed_hours, 0.5, False)
                else:
                    exceed_ot_to_leave = 0
                # exceed_ot_subtitude = roundPartial(exceed_ot_to_leave / 8, 0.5, False)
                exceed_ot_subtitude = roundPartial(exceed_hours / 8, 0.5, False)

                # Compute allow_ots once more time based on allow_overtime_bylaw
                # Need compute at this step to backward compartible before applying this law
                if allow_overtime_bylaw > 0:
                    allow_ot_bylaw_list = self._count_allow([allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st], allow_overtime_bylaw)
                    allow_ot_bylaw = sum(allow_ot_bylaw_list)
                    bonus_ot_hours = sum([allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st]) - allow_ot_bylaw
                    (allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st) = allow_ot_bylaw_list
                    if bonus_ot_hours> 0:
                        # n < 1 => level 0, n >= 101 => level 10, n in [1, 11), [11, 21), ... [91, 101) => level 1 to 10
                        bonus_ot_level = max(0, min(10, int((bonus_ot_hours - 1) / 10 + 1)))

        else:
            # exceed_ot_subtitude = sum(s.at_ids.mapped(lambda a: 1 if not a.absence else 0.5 if a.absence in ['absence_am', 'absence_pm'] else 0)) - (s.attendance_count + s.absence_count)
            # print('=====', s.working_total, s.by_request_absence_total, s.attendance_count, s.absence_count)
            exceed_ot_subtitude = s.working_total - s.by_request_absence_total - (s.attendance_count + s.absence_count) if (s.status_enough and s.enough_attendance) else 0
            if exceed_ot_subtitude < 0:
                exceed_ot_subtitude = 0

        keys = ('allow_wd_overtime', 'allow_hd_overtime', 'allow_wd_ot', 'allow_wd_st', 'allow_hd_ot', 'allow_hd_st', 'allow_ph_ot', 'allow_ph_st',
                'exceed_wd_overtime', 'exceed_hd_overtime', 'exceed_ot_to_leave', 'exceed_ot_subtitude', 'allow_overtime_bylaw', 'allow_ot_bylaw', 'bonus_ot_hours', 'bonus_ot_level')
        values= (allow_wd_overtime, allow_hd_overtime, allow_wd_ot, allow_wd_st, allow_hd_ot, allow_hd_st, allow_ph_ot, allow_ph_st,
                    exceed_wd_overtime, exceed_hd_overtime, exceed_ot_to_leave, exceed_ot_subtitude, allow_overtime_bylaw, allow_ot_bylaw, bonus_ot_hours, bonus_ot_level)
        return dict(zip(keys, values))

    def is_no_ah_employee(self):
        self.ensure_one()
        return {'House Maid', 'Driver', 'Outsource'} & set(self.employee_id.category_ids.mapped('name'))

    def _compute_at_monthly_summary(self):
        # self.ensure_one()
        view = self.env.ref('kdvn_hr_attendance.at_monthly_summary')
        for s in self:
            values = {'monthly_summary': [], 'allocation_summary': {'summary': []}}
            categories = [
                {'category': 'AT', 'fields': ['late_in_count', 'early_out_count', 'forget_count', 'attendance_count', 'absence_count', 'leaves_count', 'oh_count', 'sh_count', 'working_days_sum']},
                {'category': 'OT', 'fields': ['wd_ot_sum', 'wd_st_sum', 'hd_ot_sum', 'hd_st_sum', 'ph_ot_sum', 'ph_st_sum', 'wd_sum', 'hd_sum']},
                {'category': 'Allow WD', 'fields': ['allow_wd_overtime', 'allow_wd_ot', 'allow_wd_st']},
                {'category': 'Allow HD', 'fields': ['allow_hd_overtime', 'allow_hd_ot', 'allow_hd_st', 'allow_ph_ot', 'allow_ph_st']},
                {'category': 'Exceed', 'fields': ['exceed_wd_overtime', 'exceed_hd_overtime', 'exceed_ot_to_leave', 'exceed_ot_subtitude']},
                {'category': 'Bonus OT', 'fields': ['bonus_ot_hours', 'bonus_ot_level']},
                {'category': 'Exempt PIT OT', 'fields': ['allow_overtime_bylaw', 'allow_ot_bylaw']}
            ]
            compute_category = s._compute_allow()
            for c in categories:
                for f in c['fields']:
                    if f in s:
                        values['monthly_summary'].append({'category': c['category'], 'name': s.fields_get()[f]['string'], 'field': f, 'value': s[f]})
                        # if f == 'working_days_sum':
                        #     values['monthly_summary'].append({'category': c['category'], 'name': s.fields_get()[f]['string'], 'field': f, 'value': sum([s.attendance_count, s.absence_count, s.leaves_count, s.oh_count, s.sh_count])})
                        # else:
                        #     values['monthly_summary'].append({'category': c['category'], 'name': s.fields_get()[f]['string'], 'field': f, 'value': s[f]})
                    elif f in compute_category:
                        values['monthly_summary'].append({'category': c['category'], 'name': f, 'field': f, 'value': compute_category[f]})
            
            # Compute leave allocation summary
            any_leave_cover = self.env['hr.leave.cover'].search([('employee_id', '=', s.employee_id.id)], limit=1)
            # !NOTE: need sudo for SM/GM to see his/her staffs leave allocation
            values['allocation_summary'] = any_leave_cover.sudo().with_context(valid_allocation_date=self.env['hr.mixin'].at_period_last_day(s.at_year, s.at_month))._compute_allocation(employee_id=s.employee_id.id)
            html = self.env['ir.qweb']._render(view.id, values)
            s.summary_for_at = html
            
            # return html

    # @api.multi
    # def _compute_exceed_ot(self):
    #     for s in self:
    #         # s.exceed_ot = s._compute_allow()['exceed_ot_to_leave']
    #         s.exceed_ot = s.exceed_ot_to_leave or s.exceed_ot_subtitude

    def _compute_month_display(self):
        for s in self:
            s.month_dsp = datetime.datetime.strftime(datetime.date(s.at_year, s.at_month, 1) ,'%b. %y')

    def _compute_need_hr_action(self):
        for s in self:
            need_hr_action = False
            need_hr_action_explain = []
            # Having states unsync
            # if s.at_ids.filtered(lambda a: not a.states_sync):
            # if s.at_ids.search([('states_sync', '=', False)]):
            if not s.states_sync:
                need_hr_action = True
                need_hr_action_explain.append('States-unsynced attendances')
            # Not enough AT status
            # if not s.is_current and not s.status_enough and s.finish_waiting:
            if s.finish_waiting:
                if s.is_current and not s.status_enough:
                    need_hr_action = True
                    need_hr_action_explain.append('NOT enough attendance status')
            else:
                if s.not_enough_status:
                    need_hr_action = True
                    need_hr_action_explain.append('NOT enough attendance status')
            if not s.is_current and s.status_enough:
                # Attendance status:
                if (s.working_days_sum + (2 if s.is_no_ah_employee() else 0) != s.attendance_count + s.absence_count + s.leaves_count + s.oh_count + s.sh_count):
                    need_hr_action = True
                    need_hr_action_explain.append('Check working status')
                # Not enough AH
                ah_validity_stop = self.env['hr.mixin'].at_period_last_day(s.at_year, s.at_month)
                ah_allocation = self.env['hr.leave.allocation'].search([('employee_id', '=', s.employee_id.id), ('holiday_status_id.is_ah', '=', True), ('holiday_status_id.validity_stop', '=', ah_validity_stop)], limit=1)
                if s.ah_count < (ah_allocation.number_of_days if ah_allocation else 0) and not s.is_no_ah_employee():
                    need_hr_action = True
                    need_hr_action_explain.append('Do NOT take enough AH leaves')
                # Take a leave on SAT
                else:
                    if s.sat_leave and not ({'House Maid', 'Driver', 'Outsource'} & set(s.employee_id.category_ids.mapped('name'))):
                        sat_status = json.loads(s.sat_status)
                        ah_index = [i for (i, e) in enumerate(sat_status) if e and 'AH' in e]
                        last_ah_index = max(ah_index) if ah_index else 0
                        need_hr_action = any(['L' in e for e in sat_status[:last_ah_index] if e]) if last_ah_index else False
                        if need_hr_action:
                            need_hr_action_explain.append('Take Leave on SAT instead of AH')
            if not s.is_current and not s.enough_attendance:
                need_hr_action = True
                need_hr_action_explain.append('Attendance Records NOT enough -- Ask IT!')
            if s.by_request_absence_total and (s.employee_id.category_ids & (s.employee_id.company_id or self.env.user.company_id).ot_comp_categories()):
                need_hr_action = True
                need_hr_action_explain.append('OT-compensated staff (G8); Attended but request Leave/Absence -- IT review')
            s.update({'need_hr_action': need_hr_action, 'need_hr_action_explain': False if not need_hr_action_explain else '\n'.join(need_hr_action_explain)})
    
    def _search_need_hr_action(self, operator, value):
        if operator == '=' and value == True:
            ids = self.search([]).filtered('need_hr_action').mapped('id')
            return [('id', 'in', ids)]
        return []

    def _search_exceed_ot(self, operator, value):
        comp_categories = self.env.user.company_id.ot_comp_categories()
        domain = ['|', '|', ('employee_id.category_ids', 'in', comp_categories.ids), ('wd_sum', '>', 0), ('hd_sum', '>', 0)]
        if operator == '>' and value == 0:
            ids = self.search(domain).filtered(lambda s: s.exceed_ot_subtitude > 0).mapped('id')
            return [('id', 'in', ids)]
        elif operator == '=' and value > 0:
            ids = self.search(domain).filtered(lambda s: s.exceed_ot_subtitude == value).mapped('id')
            return [('id', 'in', ids)]
        return []

    # @api.multi
    # def action_ot_compensation(self):
    #     for s in self:
    #         # at_rules = self.env['hr.attendance']._at_rules(employee_id=s.employee_id.id, at_date=self.at_ids[-1].at_date)
    #         allow_values = s._compute_allow()
    #         if allow_values['exceed_ot_to_leave'] > 0:
    #             _logger.warning(_('Convert exceed hour into current year leave allocation: {}'.format(allow_values['exceed_ot_to_leave'])))
    #         else:
    #             return False

    
    def report_attendance_records(self, employee_ids=None, at_months=None, at_years=None):
        """
            - [{'code, name, section, from, to, O, X, L, OH, SH, Total, Late, Early, Forget', 'attendances': []}]
            - argurment type array
        """
        employees, months, years = employee_ids or self.mapped('employee_id.id'), at_months or self.mapped('at_month'), at_years or self.mapped('at_year')
        
        sql = """
            SELECT att.employee_id, emp.code, emp.name, att.at_month, att.at_year, min(dept.name) AS department, min(start_date) AS from, min(end_date) AS to, 
				SUM(late_in::int) late_in_count, SUM(early_out::int) early_out_count,
				COUNT(CASE WHEN att.id IN 
                        (SELECT at_id FROM hr_attendance_request re JOIN hr_attendance_request_type rt ON re.sub_request_type_id=rt.id WHERE rt.code IN ('forget_in', 'forget_out')) 
                        THEN True ELSE Null END)::int forget_count,
				SUM(CASE WHEN 'X' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 1 WHEN '1/2 X' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 0.5 ELSE 0 END) absence_count,
				SUM(CASE WHEN 'O' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 1 WHEN '1/2 O' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 0.5 ELSE 0 END) attendance_count,
				SUM(CASE WHEN 'L' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 1 WHEN '1/2 L' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 0.5 ELSE 0 END) leaves_count,
				SUM(CASE WHEN 'OH' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 1 WHEN '1/2 OH' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 0.5 ELSE 0 END) oh_count,
                SUM(CASE WHEN 'SH' = ANY(sTRING_TO_ARRAY(status.status, ';')) THEN 1 WHEN '1/2 SH' = ANY(STRING_TO_ARRAY(status.status, ';')) THEN 0.5 ELSE 0 END) sh_count,
                COUNT(CASE WHEN EXTRACT(ISODOW FROM att.at_date) != 7 THEN True ELSE null END)::int - 2 working_days_sum,
                array_agg(EXTRACT(day FROM att.at_date) ORDER BY att.at_date) at_days, array_agg(att.at_day ORDER BY att.at_date) at_weekdays, array_agg(status.status ORDER BY att.at_date) at_status,
                array_agg(compute_in ORDER BY att.at_date) check_in, array_agg(compute_out ORDER BY att.at_date) check_out, array_agg(il.name ORDER BY att.at_date) location_in, array_agg(ol.name ORDER BY att.at_date) location_out,
                array_agg(raw_request_description ORDER BY att.at_date) description,
                array_agg(COALESCE(wd_ot, 0) ORDER BY att.at_date) wd_ot, array_agg(COALESCE(wd_st, 0) ORDER BY att.at_date) wd_st, array_agg(COALESCE(hd_ot, 0) ORDER BY att.at_date) hd_ot, array_agg(COALESCE(hd_st, 0) ORDER BY att.at_date) hd_st,
                array_agg(COALESCE(ph_ot, 0) ORDER BY att.at_date) ph_ot, array_agg(COALESCE(ph_st, 0) ORDER BY att.at_date) ph_st,
                sum(wd_ot) wd_ot_sum, sum(wd_st) wd_st_sum, sum(hd_ot) hd_ot_sum, sum(hd_st) hd_st_sum, sum(ph_ot) ph_ot_sum, sum(ph_st) ph_st_sum
            FROM hr_attendance att
            LEFT JOIN hr_employee emp ON att.employee_id=emp.id LEFT JOIN hr_department dept ON emp.department_id=dept.id
            LEFT JOIN hr_attendance_location il ON att.check_in_location_id=il.id
            LEFT JOIN hr_attendance_location ol ON att.check_out_location_id=ol.id
            LEFT JOIN (SELECT status.hr_attendance_id at_id, string_agg(code.code, ';') status FROM hr_attendance_kderp_base_code_rel status 
                JOIN kderp_base_code code ON status.kderp_base_code_id=code.id GROUP BY status.hr_attendance_id) status ON att.id=status.at_id
            --JOIN hr_attendance_summary summary ON (att.employee_id=summary.employee_id AND att.at_month=summary.at_month AND att.at_year=summary.at_year)
            WHERE att.employee_id IN %(employee_ids)s AND att.at_year IN %(at_years)s AND att.at_month IN %(at_months)s
            GROUP BY att.employee_id, emp.code, emp.name, att.at_month, att.at_year
            ORDER BY att.at_year, att.at_month, emp.code
        """
        # values are bound as parameters (this method is callable over RPC); an empty list matches nothing
        self.env.cr.execute(sql, {
            'employee_ids': tuple(int(e) for e in employees) or (0,),
            'at_years': tuple(int(y) for y in years) or (0,),
            'at_months': tuple(int(m) for m in months) or (0,),
        })
        at_keys = ('at_day', 'at_weekday', 'at_status', 'check_in', 'check_out', 'location_in', 'location_out', 'description', 'wd_ot', 'wd_st', 'hd_ot', 'hd_st', 'ph_ot', 'ph_st')
        res = [{
            'staff_no': r['code'],
            'staff_name': r['name'],
            'dept_name': r['department'],
            'month': calendar.month_name[r['at_month']],
            'year': str(r['at_year']),
            'from_date': r['from'], 'to_date': r['to'],
            'late_in': r['late_in_count'], 'early_out': r['early_out_count'],
            'forget': r['forget_count'], 'absence': r['absence_count'], 'leaves': r['leaves_count'],
            'wd_ot_sum': r['wd_ot_sum'], 'wd_st_sum': r['wd_st_sum'], 'hd_ot_sum': r['hd_ot_sum'], 'hd_st_sum': r['hd_st_sum'],
            'ph_ot_sum': r['ph_ot_sum'], 'ph_st_sum': r['ph_st_sum'],
            'attendance': r['attendance_count'], 'oh': r['oh_count'], 'sh': r['sh_count'], 'working': r['working_days_sum'],
            'attendances': [dict(zip(at_keys, values)) for values in zip(r['at_days'], r['at_weekdays'], 
                                                                        list(map(lambda s: '' if not s else ';'.join([e for e in s.split(';') if e != '1/2 O']), r['at_status'])), 
                                                                        list(map(lambda i: i and (i + relativedelta(hours=7)).strftime('%-H:%M%Z') or '', r['check_in'])), 
                                                                        list(map(lambda o: o and (o + relativedelta(hours=7)).strftime('%-H:%M%Z') or '', r['check_out'])), 
                                                                        [e.replace(' Face', '') if e else '' for e in r['location_in']], 
                                                                        [e.replace(' Face', '') if e else '' for e in r['location_out']],
                                                                        list(map(lambda d: '' if not d else '\n'.join([s[:40] for s in d.split('\n')]), r['description'])),
                                                                        r['wd_ot'], r['wd_st'], r['hd_ot'], r['hd_st'], r['ph_ot'], r['ph_st'])]
        } for r in self.env.cr.dictfetchall()]
        # res.sort(key=lambda e: f"{e['year']}-{e['month']}-{e['staff_no']}")
        return res

    def report_approved_attendance_records(self):
        at_keys = ('at_day', 'at_weekday', 'at_status', 'check_in', 'check_out', 'location_in', 'location_out', 'description', 'less_description', 'wd_ot', 'wd_st', 'weekday_ot', 'hd_ot', 'hd_st', 'ph_ot', 'ph_st', 'holiday_ot')
        res = [{
            'staff_no': r.employee_id.code, 'staff_name': r.employee_id.name, 'dept_name': r.employee_id.department_id.name,
            'month': calendar.month_name[r.at_month], 'year': str(r.at_year),
            'from_date': (datetime.date(r.at_year, r.at_month, 21) - relativedelta(months=1)).strftime('%-d %b'), 'to_date': datetime.date(r.at_year, r.at_month, 20).strftime('%-d %b %Y'),
            'late_in': r.late_in_count or None, 'early_out': r.early_out_count or None,
            'forget': r.forget_count or None, 'absence': r.absence_count or None, 'leaves': r.leaves_count or None,
            'wd_ot_sum': r.wd_ot_sum or None, 'wd_st_sum': r.wd_st_sum or None, 'weekday_ot_sum': (r.wd_ot_sum + r.wd_st_sum) or None,
            'hd_ot_sum': r.hd_ot_sum or None, 'hd_st_sum': r.hd_st_sum or None, 'ph_ot_sum': r.ph_ot_sum or None, 'ph_st_sum': r.ph_st_sum or None,
            'holiday_ot_sum': sum([r.hd_ot_sum, r.hd_st_sum, r.ph_ot_sum, r.ph_st_sum]) or None,
            'attendance': r.attendance_count, 'oh': r.oh_count or None, 'sh': r.sh_count or None, 'working': r.working_days_sum,
            'at_rules': self.env['hr.attendance']._at_rules(employee_id=r.employee_id, at_date=self.env['hr.mixin'].at_period_end(r.at_year, r.at_month) - relativedelta(months=1)),
            'exceed_wd_overtime': r.exceed_wd_overtime or None, 'exceed_hd_overtime': r.exceed_hd_overtime or None, 
            'ot_substitute': r.exceed_ot_subtitude or None,
            'allow_wd_ot': r.allow_wd_ot or None, 'allow_wd_st': r.allow_wd_st or None,
            'allow_hd_ot': r.allow_hd_ot or None, 'allow_hd_st': r.allow_hd_st or None,
            'allow_ph_ot': r.allow_ph_ot or None, 'allow_ph_st': r.allow_ph_st or None,
            'allow_overtime_bylaw': r.allow_overtime_bylaw or 0,
            'allow_ot_bylaw': r.allow_ot_bylaw or 0,
            'bonus_ot_hours': r.bonus_ot_hours or None, 'bonus_ot_level': r.bonus_ot_level or None,
            'attendances': [dict(zip(at_keys, value)) for value in r.at_ids.mapped(lambda a: (
                    a.at_date.day, a.at_day_dsp,
                    a.status_codes.replace('1/2 O', '').replace(', ', ''),
                    (a.compute_in + relativedelta(hours=7)).strftime('%-H:%M') if a.compute_in else '',
                    (a.compute_out + relativedelta(hours=7)).strftime('%-H:%M') if a.compute_out else '',
                    a.check_in_location_id.display_name.replace(' Face', '') if a.check_in_location_id else '',
                    a.check_out_location_id.display_name.replace(' Face', '') if a.check_out_location_id else '',
                    '\n'.join(s[:40] for s in a.raw_request_description.split('\n')) if (a.raw_request_description) else '',
                    '\n'.join(s[:40] for s in a.raw_request_description.split('\n')) if (a.raw_request_description and not a.wd_ot) else '',
                    a.wd_ot or None, a.wd_st or None, (a.wd_ot + a.wd_st) or None,
                    a.hd_ot or None, a.hd_st or None, a.ph_ot or None, a.ph_st or None, sum([a.hd_ot, a.hd_st, a.ph_ot, a.ph_st]) or None
                ))]
        } for r in self]
        return res


class KderpHrAttendanceRefuse(models.Model):
    """
        Extend this for leave and at requests
    """
    _name = "hr.attendance.refuse"
    _description = "KDErp Attendance/Leave refuse comments"

    # !Note: no need
    at_ids = fields.One2many('hr.attendance', readonly=True, compute='_compute_at_ids', context={'active_test': False})
    # related_request_ids = fields.Many2many('hr.attendance.request', readonly=True, defautl=False)
    related_request_id = fields.Many2one('hr.attendance.request', readonly=True, context={'active_test': False})
    related_request_batch_id = fields.Char(related='related_request_id.batch_id', store=True, readonly=True)
    multiple_refuse = fields.Boolean()
    related_leave_cover_id = fields.Many2one('hr.leave.cover', readonly=True, context={'active_test': False})
    employee_id = fields.Many2one('hr.employee', compute='_compute_employee', store=True)
    name = fields.Text(string="Refuse comments", required=True)
    active = fields.Boolean(default=True)


    # @api.model
    # def default_get(self, fields_list):
    #     defaults = super().default_get(fields_list)
    #     return defaults

    def _compute_at_ids(self):
        for r in self:
            at_ids = []
            if r.related_request_id:
                at_ids += r.related_request_id.at_id
            elif r.related_leave_cover_id:
                at_ids += r.related_leave_cover_id.related_at_ids().mapped('id')
            r.at_ids = at_ids
    
    @api.depends('related_request_id', 'related_leave_cover_id')
    def _compute_employee(self):
        for r in self:
            employee_id = False
            if r.related_request_id:
                employee_id = r.related_request_id.employee_id.id
            elif r.related_leave_cover_id:
                employee_id = r.related_leave_cover_id.employee_id.id
            r.employee_id = employee_id
    
    ##### ACTIONS #####
    def save(self):
        # [X] TODO: change status of active_id record to refuse
        # [X] TODO: handling leave refuse and request refuse here as well
        self.ensure_one()
        if self.related_request_id:
            if self.multiple_refuse and self.related_request_batch_id:
                other_request_ids = self.env['hr.attendance.request'].search([('id', '!=', self.related_request_id.id), ('batch_id', '=', self.related_request_batch_id)])
                other_refuse = [{
                    'related_request_id': r.id,
                    'name': self.name,
                } for r in other_request_ids]
                self.create(other_refuse)
                other_request_ids.write({'state': 'refuse'})
                other_request_ids.filtered(lambda r: r.request_type == 'over_time').mapped('at_id')._compute_ot_request()
            
            request_id = self.env['hr.attendance.request'].browse(self.related_request_id.id)
            request_id.state = 'refuse'
            if request_id.request_type == 'over_time':
                request_id.at_id._compute_ot_request()
        
        if self.related_leave_cover_id:
            leave_cover_id = self.env['hr.leave.cover'].browse(self.related_leave_cover_id.id)
            leave_cover_id.state = 'refuse'
            

    def discard(self):
        self.ensure_one()
        if self.related_request_id:
            if self.multiple_refuse and self.related_request_batch_id:
                other_request_ids = self.env['hr.attendance.request'].search([('id', '!=', self.related_request_id.id), ('batch_id', '=', self.related_request_batch_id)])
                other_refuse = self.search([('related_request_id', 'in', other_request_ids.filtered(lambda r: r.state == 'draft').mapped('id'))])
                other_refuse.unlink()

            request_id = self.env['hr.attendance.request'].browse(self.related_request_id.id)
            if request_id.state == 'draft':
                # self.related_request_id = False
                self.unlink()
                return  # self not exist anymore
            else:
                raise UserError(_('Can delete a refuse comment only in DRAFT state!'))

        if self.related_leave_cover_id:
            leave_cover_id = self.env['hr.leave.cover'].browse(self.related_leave_cover_id.id)
            if leave_cover_id.state == 'draft':
                # self.related_leave_cover_id = False
                self.unlink()
                return  # self not exist anymore
            else:
                raise UserError(_('Can delete a refuse comment only in DRAFT state!'))
        
        # [] TODO: consider delete the comment or not

    @api.constrains('name', 'related_request_id', 'related_leave_cover_id')
    def _check_comment(self):
        for r in self:
            if not r.name:
                raise ValidationError(_("You should give some comment why the request is refused!"))
            if not any([r.related_request_id , r.related_leave_cover_id]):
                raise ValidationError(_("Need either WT/OT Request or Leave Request!"))
            if all([r.related_request_id , r.related_leave_cover_id]):
                raise ValidationError(_("Refuse one request at a time only!"))


class KderpHrAttendanceOTHolidaySummary(models.Model):
    _name = 'hr.attendance.ot.holiday.summary'
    _auto = False
    _description = 'OT on Holiday Summary'

    employee_id = fields.Many2one('hr.employee', readonly=True, domain=[('ot_apply', '=', True)])
    department_id = fields.Many2one('hr.department', readonly=True)
    area_id = fields.Many2one('hr.department', readonly=True)
    admin_manager_id = fields.Many2one('hr.employee', string='SM', readonly=True)
    admin_gm_id = fields.Many2one('hr.employee', string='GM', readonly=True)
    at_year = fields.Char('Year', readonly=True)
    at_month = fields.Integer(readonly=True)   # Odoo 12: Selection of month names (int keys); Odoo 19 selections need str keys. at_month_dsp shows the name
    at_month_dsp = fields.Char(compute='compute_at_month_dsp', string="Month", readonly=True)

    ot_wd = fields.Float('Weekday Used', readonly=True)
    ot_hd = fields.Float('Holiday Used', readonly=True)
    ot_wd_allow = fields.Float('Weedkay Limit',readonly=True)
    ot_hd_allow = fields.Float('Holiday Limit', readonly=True)
    ot_wd_remain = fields.Float('Weekday Remain', readonly=True)
    ot_hd_remain = fields.Float('Holiday Remain', readonly=True)
    ot_wd_ratio = fields.Float('Weekday Ratio', readonly=True, group_operator="avg")
    ot_hd_ratio = fields.Float('Holiday Ratio', readonly=True, group_operator="avg")

    ot_total = fields.Float('OT Total', readonly=True)
    ot_wd_over = fields.Boolean('Weekday Over', readonly=True, help="Weekday Over limit", group_operator="bool_or")
    ot_hd_over = fields.Boolean('Holiday Over', readonly=True, help="Holiday Over limit", group_operator="bool_or")
    weekly_over = fields.Boolean('Weekly Over', readonly=True, help="Weekly Over limit", group_operator="bool_or")
    day_over = fields.Boolean('Day Over', readonly=True, help="Daily Over limit", group_operator="bool_or")
    avg_section_ot = fields.Float('Avg. Section OT', readonly=True, group_operator="min")
    avg_area_ot = fields.Float('Avg. Area OT', readonly=True, group_operator="min")

    at_ids = fields.One2many('hr.attendance', 'summary_id', readonly=True, context={'active_test': False})
    current_month = fields.Boolean(compute='compute_current_month', search='search_current_month')
    last_month = fields.Boolean(compute='compute_last_month', search='search_last_month')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        query = """
            CREATE OR REPLACE VIEW hr_attendance_ot_holiday_summary AS
            (
            SELECT ot_monthly.*, area_ot.avg_area_ot, section_ot.avg_section_ot FROM
            (SELECT (att.employee_id::bigint * 10000 + (att.at_year - 2000) * 12 + att.at_month)::int AS id,
                att.employee_id, att.department_id, att.area_id, att.admin_manager_id, att.admin_gm_id, att.at_year::text, att.at_month,
                SUM(att.ot_wd) ot_wd, SUM(att.ot_hd) ot_hd, 
				(MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) ot_wd_allow, 
				(MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) ot_hd_allow, MIN(ot_wd_remain) ot_wd_remain, MIN(ot_hd_remain) ot_hd_remain,
                (CASE WHEN (MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) = 0 THEN 0 ELSE SUM(att.ot_wd) / (MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) END) ot_wd_ratio,
				(CASE WHEN (MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) = 0 THEN 0 ELSE SUM(att.ot_hd) / (MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) END) ot_hd_ratio,
	            (MIN(ot_wd_remain) < 0) ot_wd_over, (MIN(ot_hd_remain) < 0) ot_hd_over, (MIN(weekly_wd_remain) < 0) weekly_over,
                BOOL_OR(ot_wd > 4) day_over,
                SUM(ot_total) ot_total,
                --SUM(CASE WHEN section_ot_staff = 0 THEN 0 ELSE (ot_total/section_ot_staff) END) avg_section_ot,
				--SUM(CASE WHEN area_ot_staff = 0 THEN 0 ELSE (ot_total/area_ot_staff) END) avg_area_ot,
                --MIN(avg_section_ot) avg_section_ot, MIN(avg_area_ot) avg_area_ot,
                ARRAY_AGG(att.id ORDER BY att.at_date) at_ids
            FROM hr_attendance att
                LEFT JOIN hr_employee emp ON att.employee_id=emp.id
                    LEFT JOIN hr_department dept ON emp.admin_dept_id=dept.id
	        GROUP BY att.at_year, att.at_month, att.employee_id, att.department_id, att.area_id, att.admin_manager_id, att.admin_gm_id) AS ot_monthly
            
            LEFT JOIN

            (SELECT at_year::text, at_month, att1.area_id,
                    SUM(CASE WHEN dept.area_ot_staff = 0 THEN 0 ELSE (ot_total/dept.area_ot_staff) END) avg_area_ot
                FROM hr_attendance att1
                LEFT JOIN hr_department dept ON att1.department_id=dept.id
                GROUP BY att1.at_year, att1.at_month, att1.area_id) AS area_ot ON ot_monthly.at_year=area_ot.at_year AND ot_monthly.at_month=area_ot.at_month AND ot_monthly.area_id=area_ot.area_id
            
            LEFT JOIN
            
            (SELECT at_year::text, at_month, att2.department_id,
		            SUM(CASE WHEN section_ot_staff = 0 THEN 0 ELSE (ot_total/section_ot_staff) END) avg_section_ot
                FROM hr_attendance att2
                LEFT JOIN hr_department dept ON att2.department_id=dept.id
                GROUP BY att2.at_year, att2.at_month, att2.department_id) AS section_ot ON ot_monthly.at_year=section_ot.at_year AND ot_monthly.at_month=section_ot.at_month AND ot_monthly.department_id=section_ot.department_id

            )
        """
        query1 = """
                CREATE OR REPLACE VIEW hr_attendance_ot_holiday_summary AS
                (SELECT (att.employee_id::bigint * 10000 + (att.at_year - 2000) * 12 + att.at_month)::int AS id,
                att.employee_id, att.department_id, att.area_id, att.admin_manager_id, att.admin_gm_id, att.at_year::text, att.at_month,
                SUM(att.ot_wd) ot_wd, SUM(att.ot_hd) ot_hd, 
				(MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) ot_wd_allow, 
				(MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) ot_hd_allow, MIN(ot_wd_remain) ot_wd_remain, MIN(ot_hd_remain) ot_hd_remain,
                (CASE WHEN (MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) = 0 THEN 0 ELSE SUM(att.ot_wd) / (MAX(ot_wd_remain) + COALESCE((ARRAY_AGG(ot_wd ORDER BY att.at_date))[1], 0)) END) ot_wd_ratio,
				(CASE WHEN (MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) = 0 THEN 0 ELSE SUM(att.ot_hd) / (MAX(ot_hd_remain) + COALESCE((ARRAY_AGG(ot_hd ORDER BY att.at_date))[1], 0)) END) ot_hd_ratio,
	            (MIN(ot_wd_remain) < 0) ot_wd_over, (MIN(ot_hd_remain) < 0) ot_hd_over, (MIN(weekly_wd_remain) < 0) weekly_over,
                BOOL_OR(ot_wd > 4) day_over,
                SUM(ot_total) ot_total,
                SUM(CASE WHEN section_ot_staff = 0 THEN 0 ELSE (ot_total/section_ot_staff) END) avg_section_ot,
				SUM(CASE WHEN area_ot_staff = 0 THEN 0 ELSE (ot_total/area_ot_staff) END) avg_area_ot,
                --MIN(avg_section_ot) avg_section_ot, MIN(avg_area_ot) avg_area_ot,
                ARRAY_AGG(att.id ORDER BY att.at_date) at_ids
                FROM hr_attendance att
                    LEFT JOIN hr_employee emp ON att.employee_id=emp.id
                        LEFT JOIN hr_department dept ON emp.admin_dept_id=dept.id
                GROUP BY att.at_year, att.at_month, att.employee_id, att.department_id, att.area_id, att.admin_manager_id, att.admin_gm_id)
        """
        self.env.cr.execute(query)

    def _legacy_name_get(self):
        return [(s.id, 'OT detail of {}-{} for {}'.format(calendar.month_name[s.at_month], s.at_year, s.employee_id.name)) for s in self]
    

    @api.depends('employee_id', 'at_month', 'at_year')
    def _compute_display_name(self):
        """Odoo 19 has no name_get(): display_name is computed. The Odoo 12 body is kept as _legacy_name_get (same strings)."""
        names = dict(self._legacy_name_get())
        for rec in self:
            rec.display_name = names.get(rec.id) or ''

    def compute_at_month_dsp(self):
        for r in self:
            r.at_month_dsp = month_abbr[r.at_month] + '-' + str(r.at_year)
    
    def compute_current_month(self):
        today = fields.Date.context_today(self)
        current_year, current_month = self.env['hr.mixin'].get_at_year_month(today)
        for r in self:
            r.current_month = int(r.at_year) == current_year and r.at_month == current_month

    @api.model
    def search_current_month(self, operator, value):
        today = fields.Date.context_today(self)
        current_year, current_month = self.env['hr.mixin'].get_at_year_month(today)
        domain = [('at_year', operator, str(current_year)), ('at_month', operator, current_month)]

        if operator == '!=':
            domain = ['|'] + domain
        
        return domain
    
    def compute_last_month(self):
        last_month_today = fields.Date.context_today(self) - relativedelta(months=1)
        year, last_month = self.env['hr.mixin'].get_at_year_month(last_month_today)
        for r in self:
            r.last_month = int(r.at_year) == year and r.at_month == last_month

    @api.model
    def search_last_month(self, operator, value):
        last_month_today = fields.Date.context_today(self) - relativedelta(months=1)
        year, last_month = self.env['hr.mixin'].get_at_year_month(last_month_today)
        domain = [('at_year', operator, str(year)), ('at_month', operator, last_month)]
        
        if operator == '!=':
            domain = ['|'] + domain

        return domain
    
        




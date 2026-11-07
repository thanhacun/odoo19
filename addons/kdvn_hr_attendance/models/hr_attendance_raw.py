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



class KderpHrAttendanceRaw(models.Model):
    _name = 'hr.attendance.raw'
    _description = 'HR Attendance raw data from external server'
    _order = 'at_code desc, check_in'

    employee_id = fields.Many2one('hr.employee', domain=[('working', '=', True)], required=True, index=True)
    check_in = fields.Datetime()
    check_out = fields.Datetime()
    check_date = fields.Date(index=True)
    first_location_id = fields.Many2one('hr.attendance.location')
    last_location_id = fields.Many2one('hr.attendance.location')
    sync_time = fields.Datetime()
    sync_state = fields.Selection([
        ('success', 'Success'),
        ('fail', 'Fail')
    ])
    at_code = fields.Char(readonly=True)
    data_enough = fields.Boolean(default=False)
    raw_checks = fields.Text(help="Keep check times as json for refference")
    manual_mode = fields.Boolean(help='In this mode, data will enter manually', default=False)
    is_delete = fields.Boolean(default=False, help='When selected, this record will not be used!')
    active = fields.Boolean(default=True)

    _at_code_unique = models.Constraint('unique(at_code)', 'AT code must be unique!')

    # @api.multi
    # @api.depends('check_in', 'check_out')
    # def _compute_at_date(self):
    #     for raw_at in self:
    #         can_compute = any([raw_at.check_in, raw_at.check_out])
    #         if can_compute:
    #             at_rules = self.env['hr.attendance']._at_rules(raw_at.employee_id.id)
    #             day_start = at_rules['day_start']
    #             early_check_in = at_rules['early_check_in']
    #             dt_value = raw_at.check_in or raw_at.check_out or False
    #             raw_at.check_date = raw_at.date_by_start_hour(dt_value, day_start, early_check_in, vn_tz)
    #         else:
    #             raw_at.check_date = False

    def date_by_start_hour(self, dt_value, start_hour=0, employee_id=None, tz=vn_tz):
        """
            - Using one method only (DRY)
            - Do not change the name of method for backward compatible
        """
        get_at_date = self.env['hr.mixin'].get_at_date
        res = get_at_date(dt_value, get_time=False, start_hour=start_hour, employee_id=employee_id)
        return res
    
    def old_date_by_start_hour(self, dt_value, start_hour=0, early_check_in=False, next_day_early=False, tz=vn_tz):
        """Return at_date from a datetime by tz and start hour

        Args:
            dt_value [datetime]: datetime value to convert, utc time zone
            start_hour (int, optional): [Start hour of the day: 1~24]. Defaults to 0.
            tz ([timezone], optional): [description]. Defaults to vn_tz.
            early_check_in: is early_check_in maximum 30 minutes
            next_day_early: is early_checi_in next day

        Ex: (10-15-21 05:50:00, start_hour=6, tz=vn_tz) => 10-14-21 => if early_check_in 10-15-21
        Ex: (10-15-21 07:50:00, start_hour=6, tz=vn_tz) => 10-15-21
        """
        company = self.env.user.company_id
        if not company:
            raise UserError(_('User {} should belong to a company!'.format(self.env.user.name)))
        start_hour = start_hour or company.at_policy()['day_start']
        start_hour = start_hour - 1 if early_check_in else start_hour
        if not dt_value:
            raise UserError(_('Need a datetime as an required input! REF: Calling method [date_by_start_hour]'))
        
        early_minute_offset = 30 if early_check_in else 0
        late_minute_offset = 30 if next_day_early else 0
        
        start_time = dt_value.astimezone(tz) + relativedelta(hour=start_hour, minute=early_minute_offset)
        end_time = start_time + relativedelta(days=1, minutes=-late_minute_offset)
        
        if dt_value.astimezone(tz) < start_time:
            # res = dt_value.astimezone(tz).date() - datetime.timedelta(days=1)
            res = start_time.date() - datetime.timedelta(days=1)
        elif dt_value.astimezone(tz) > end_time:
            res = end_time.date()
        else:
            res = start_time.date()
            # return dt_value.astimezone(tz).date()
        return res

    @api.depends('employee_id')
    def _compute_at_code_backup(self):
        for raw_at in self:
            if (not raw_at.at_code) and (raw_at.check_date and raw_at.employee_id):
                raw_at.at_code = '-'.join(['AT', raw_at.check_date.strftime('%y%m%d'), raw_at.employee_id.code])

    def batch_action(self, batch_employee_ids, at_date, new_commit_size, loops_number, max_process_time, test_mode, force_sync):
        """
            Helper method to prepair for queue job
            employees: hr.employee
            at_date: date
            ats: hr.attendance
            ats_raw: hr.attendance.raw
        """
        # further_action_at_ids = []
        # t_start = process_time()
        batch_employees = self.env['hr.employee'].browse(batch_employee_ids)
        # ats = self.env['hr.attendance'].browse(at_ids)
        # ats_raw = self.env['hr.attendance.raw'].browse(at_raw_ids)
        for staff in batch_employees:
            # further_action_at_ids = self.env['hr.attendance']
            at_code = '-'.join(['AT', at_date.strftime('%y%m%d'), staff.code])
            # at = ats.filtered(lambda a: a.code == at_code)
            at = self.env['hr.attendance'].search([('code', '=', at_code)])
            # at_raw = ats_raw.filtered(lambda r: r.at_code == at_code)
            at_raw = self.env['hr.attendance.raw'].search([('at_code', '=', at_code)])
            further_action = False

            if at and at_raw:
                update = {}
                # Case switch check_out to check_in
                if not at_raw.check_in and at.check_in:
                    update['check_in'] = False
                if not at_raw.check_out and at.check_out:
                    update['check_out'] = False

                if (at_raw.check_in != at.check_in or force_sync) and at_raw.check_in:
                    if at_raw.first_location_id:
                        update['check_in'] = at_raw.check_in
                    else:
                        update['check_in'] = False
                if (at_raw.check_out != at.check_out or force_sync) and at_raw.check_out:
                    if at_raw.last_location_id:
                        update['check_out'] = at_raw.check_out
                    else:
                        update['check_out'] = False
                if update:
                    at.with_context(do_not_run_at_status=True).write(update)
                # Some time when user register leave then change the date, need to re-run at_status
                at.read(['status_ids'])
                further_action = update or (not at.status_ids or 'X' in at.status_ids.mapped('code') ) or at.at_day == 'Sat'

            elif not at:  # 2 cases: (not at but at_raw) and (not at and not at_raw)
                # TODO [X]: Only create at if employee create_date before at_date
                # TODO [X]: try...except to prevent the batch from terminating
                if staff._compute_start_working_date() <= at_date:
                    try:
                        at = self.env['hr.attendance'].with_context(do_not_run_at_status=True).create({
                            'employee_id': staff.id, 'code': at_code,
                            'check_in': at_raw.check_in if at_raw else False,
                            'check_out': at_raw.check_out if at_raw else False,
                        })
                        further_action = True if at_raw else False
                    except Exception as e:
                        _logger.error(e)
            else:  # at and not at_raw
                # reload at to avoid cachemiss error
                # at = self.env['hr.attendance'].browse(at.id)
                at.read(['status_ids'])
                further_action = not at.status_ids or at.at_day == 'Sat'
                # Fix at data if at_raw not available (when wanting to update)
                if at.check_in or at.check_out:
                    at.with_context(do_not_run_at_status=True).update({'check_in': False, 'check_out': False})
                    further_action = True

            if at and further_action:
                try:
                    # self.env['hr.attendance'].browse(further_action_at_ids)._compute_at_status()
                    at._compute_at_status()
                except Exception as e:
                    _logger.error(e)
                
                # further_action_at_ids.append(at.id)
                # further_action_at_ids |= at
            
        
        _logger.warning('{} records updated for {}'.format(len(batch_employees), at_date))
        

        # TODO [X]: commit based on time spend
        # TODO [ ]: Can remove - need test
        # t_stop = process_time()
        # total_process = (t_stop - t_start) * loops_number
        # if not test_mode and (len(batch_employees) == new_commit_size or total_process >= max_process_time):
        #     try:
        #         self.env.cr.commit()
        #     except Exception as e:
        #         self.env.cr.rollback() # rollback when error happen
        #         _logger.error(e)
        #     _logger.warning('{} records updated for {} (cr_commit)'.format(len(batch_employees), at_date))

    @api.model
    def _sync_attendance_record(self, at_date=None, duration=None, employee_ids=[], department_ids=[], force_sync=False, location_name=None, commit_size=50, test_mode=False, delay=True):
        """ Sync attendance information to hr.attendance model

        Args:
            at_date (date, optional): Date that the sync to be based on, normally today
            duration (int, optional): How far the sync will take place. Defaults to None; 0 if sync for one day as at_date
            employee_ids
            department_ids,
            commit_size: number of records to make a cr commit
            Ex: 1 at ()check: at_date='2021-11-10', duration=0, employee_ids=[10]
            test_mode: True, do not commit

        Notes: this method takes quite a long time since original use commit_size to commit the result before timeout (default 120 seconds)
               May have a better approach by using queue job to separate the method into smaller independent jobs that surely running under 120 seconds
        """
        # !NOTE: should not sync/create data for B.O.D and any none employed employees
        # [X] TODO: create at for even stop working employee till the end of the at month
        # [X] TODO: no checkin employees
        today = fields.Date.context_today(self)
        at_start_dt = self.env['hr.mixin'].get_start_dt(today, True)
        emp_domain = ['|', ('working', '=', True), '&', '&', ('working', '=', False), ('stop_working_date', '<', at_start_dt + relativedelta(months=1)), ('stop_working_date', '>=', at_start_dt)]
        location_emp_ids = None
        if location_name:
            machine_id = self.env['hr.attendance.location'].search([('name', '=', location_name)]).id
            if machine_id:
                sql_string = """
                    SELECT DISTINCT employee_id
                    FROM hr_attendance_raw
                    WHERE first_location_id = {machine_id} OR last_location_id = {machine_id}
                """.format(machine_id=machine_id)
                self.env.cr.execute(sql_string)
                location_emp_ids = list(map(lambda e: e[0], self.env.cr.fetchall()))
                if employee_ids:
                    employee_ids += location_emp_ids
                else:
                    employee_ids = location_emp_ids
        if employee_ids:
            emp_domain.insert(0, "&")
            emp_domain.append(('id', 'in', employee_ids))
        if department_ids:
            emp_domain.insert(0, "&")
            emp_domain.append(('admin_dept_id', 'in', department_ids))

        employees = self.env['hr.employee'].search(emp_domain)
        attendance = self.env['hr.attendance']
        at_date = at_date or (today + relativedelta(months=-1, day=self.env['hr.mixin'].at_start_day()))
        if duration is None:
            duration = (today - at_date).days
        at_dates = [at_date + relativedelta(days=i) for i in range(duration + 1)]
        at_dates.reverse()  # reverse for better logic (new date always sync first)
        for at_date in at_dates:
            # TODO []: only need active_test=False if at_date is too old (default 14-month will archive)
            active_test = at_date <= (today - relativedelta(months=14))
            no_checkin_employees = self.env['hr.attendance.rule'].search([('active', '=', True), ('no_checkin', '=', True), ('valid_start', '<=', at_date), '|', ('valid_stop', '=', False), ('valid_stop', '>=', at_date)]).mapped('employee_ids')
            check_employees = employees - no_checkin_employees
            if at_date.weekday() == 5:
                new_commit_size = 30
            else:
                new_commit_size = commit_size
            batch_size = new_commit_size if len(check_employees) > new_commit_size else len(check_employees)
            # ats = attendance.with_context(active_test=active_test).search([('at_date', '=', at_date)])
            # ats_raw = self.with_context(active_test=active_test).search([('check_date', '=', at_date), ('is_delete', '=', False)])

            # REF: https://www.geeksforgeeks.org/break-list-chunks-size-n-python/
            # break employees into chunks with size of batch_size
            batchs = [check_employees] if not batch_size else [check_employees[n:n + batch_size] for n in range(0, len(check_employees), batch_size)]
            max_process_time = 118  # Default timeout 120 seconds
            loops_number = len(batchs) * len(at_dates)

            if delay:  # No delay if small loops
                if len(employees) * loops_number <= (60 if at_date.weekday() == 5 else 100):
                    delay = False

            if delay and self.delayable:
                sync_att_batch = self.env['queue.job.batch'].get_new_batch(f'Sync {len(check_employees)} employees att records for {at_date} (UID: {self.env.uid} | Total jobs: {len(batchs)})')
                for batch_number, batch_employees in enumerate(batchs):
                    batch_employee_ids = batch_employees.ids
                    # batch_ats_ids = ats.filtered(lambda e: e.employee_id.id in batch_employee_ids).ids
                    # batch_ats = attendance.browse(batch_ats_ids)
                    # batch_ats_raw_ids = ats_raw.filtered(lambda e: e.employee_id.id in batch_employee_ids).ids
                    # batch_ats_raw = self.env['hr.attendance.raw'].browse(batch_ats_raw_ids)
                    description = f'Sync {len(batch_employees)} employees att records for {at_date} | job: {batch_number + 1}/{len(batchs)}'
                    
                    # TODO []: check other pending jobs (same description, state in ['pending', 'started'] and retry == 0 if started)
                    # pending_jobs_domain = expression.AND([('state', '=', 'started'), ('retry', '=', 0), ('exec_time', '=', 0)])
                    # pending_jobs_domain = expression.OR([[('state', '=', 'pending')], pending_jobs_domain])
                    # pending_jobs_domain = expression.AND([[('name', '=', description)], pending_jobs_domain])
                    pending_jobs = self.env['queue.job'].search([('name', '=', description), '|', ('state', '=', 'pending'), '&', '&', ('state', '=', 'started'), ('retry', '=', 0), ('exec_time', '=', 0)])
                    _logger.warning(pending_jobs)
                    if pending_jobs:
                        for job in pending_jobs:
                            job.button_done()
                    
                    self.env['hr.attendance.raw'].with_context(job_batch=sync_att_batch).with_delay(max_retries=1, description=description).batch_action(batch_employee_ids=batch_employee_ids, at_date=at_date, new_commit_size=new_commit_size, 
                                                                                                                                                         loops_number=loops_number, max_process_time=max_process_time, test_mode=test_mode, force_sync=force_sync)
                    # delayable = self.delayable()
                    # delayable.set(description=_(f"Sync {len(batch_employees)} employees at records for {at_date} (UID: {self.env.uid})"))
                    # delayable.batch_action(batch_employees=batch_employees, at_date=at_date, ats=ats, ats_raw=ats_raw, new_commit_size=new_commit_size, loops_number=loops_number, max_process_time=max_process_time, test_mode=test_mode, force_sync=force_sync)
                    # delayable.delay()
                sync_att_batch.enqueue()
            else:
                for batch_employees in batchs:
                    # batch_ats_ids = ats.filtered(lambda e: e.employee_id in batch_employees).ids
                    # batch_ats_raw_ids = ats_raw.filtered(lambda e: e.employee_id in batch_employees).ids
                    self.batch_action(batch_employee_ids=batch_employees.ids, at_date=at_date, new_commit_size=new_commit_size, loops_number=loops_number, max_process_time=max_process_time, test_mode=test_mode, force_sync=force_sync)

        # TODO []: signaling UI to refresh

    @api.model
    def _random_faked_data(self, at_date=None, duration=0):
        employees = self.env['hr.employee'].search([('working', '=', True), ('category_ids', '=', 'Testing')])
        AT = self.env['hr.attendance']
        today = datetime.datetime.now(vn_tz).date()
        at_date = at_date or today
        at_dates = [at_date - datetime.timedelta(days=i) for i in range(duration + 1)]

        at_status = ['normal', 'late-in', 'early-out', 'absence']
        status_weight = [None, None]
        inout_minutes = [i for i in range(60)]
        in_minutes_late = [i for i in range(5, 60)]
        out_minutes_early = [i for i in range(30, 56)]

        PH = self.env['hr.holidays.public'].search([])

        for staff in employees:
            for date in at_dates:
                data_enough = False
                finger_time = [None, None]
                is_holiday = date.weekday() == 6
                is_public_holiday = bool(PH.is_public_holiday(date, employee_id=self.id))

                # [x] check-in or check-out
                # [x] NOT generate for holiday and public holiday
                if is_holiday or is_public_holiday:
                    status_weight = [None, None]
                else:
                    if date < today:
                        status_weight = [[0.9, 0.06, 0.0, 0.04], [0.9, 0.0, 0.06, 0.04]]
                        data_enough = True
                    else:
                        now = datetime.datetime.now(vn_tz)
                        start_time = datetime.datetime.combine(now.date(), datetime.time(1)).astimezone(vn_tz)
                        end_time = datetime.datetime.combine(now.date(), datetime.time(10)).astimezone(vn_tz)
                        if now > start_time and now < end_time:
                            status_weight = [[0.9, 0.06, 0.0, 0.04], None]
                            data_enough = False
                        elif now > end_time:
                            status_weight = [None, [0.9, 0.0, 0.06, 0.04]]
                            data_enough = True
                        else:
                            status_weight = [None, None]
                            data_enough = False

                # [x] random: check_in, late, check_out, early, absence
                if any(status_weight):
                    rnd_status = [None if not status else random.choices(at_status, status)[0] for status in status_weight]
                else:
                    rnd_status = [None, None]

                for i in [0, 1]:
                    if rnd_status[i] == 'normal':
                        finger_time[i] = datetime.time(0 if i == 0 else 10, random.choice(inout_minutes))
                    if rnd_status[i] == 'late-in':
                        finger_time[i] = datetime.time(1, random.choice(in_minutes_late))
                    if rnd_status[i] == 'early-out':
                        finger_time[i] = datetime.time(16 - 7, random.choice(out_minutes_early))
                    if rnd_status[i] == 'absence':
                        finger_time[i] = None

                # Add date to finger_time
                finger_time = [None if not time else datetime.datetime.combine(date, time) for time in finger_time]

                at_code = '-'.join(['AT', date.strftime('%y%m%d'), staff.code])
                # [X] update/create into database
                at_raw = self.search([('at_code', '=', at_code)])

                # NOTE: at_code is compute field that depends on other fields
                # need to update to avoid override by the compute function
                if any(rnd_status) and any(status_weight):
                    if at_raw:
                        if not at_raw.data_enough:
                            # update existed record
                            at_raw.write({
                                # 'check_in': finger_time[0] if not at_raw.check_in else at_raw.check_in,
                                'check_out': finger_time[1] if not at_raw.check_out else at_raw.check_out,
                                'data_enough': data_enough
                            })
                            at_raw.at_code = at_code

                    else:
                        raw = self.create({
                            'employee_id': staff.id,
                            # 'at_code': at_code, 
                            'check_in': finger_time[0],
                            'check_out': finger_time[1],
                            'data_enough': data_enough
                        })
                        raw.at_code = at_code

                print('=====', staff.code, date, rnd_status, finger_time)

    def _get_api_token_face_server(self, server, email, password):
        query = """
            query Login($email: String!, $password: String!){
                login(email: $email, password: $password){
                    accessToken,
                    email,
                    roles{id},
                    fullName,
                    avatar,
                    id}
            }
        """
        variables = {"email": email, "password": password}
        try:
            request = requests.post(server, json={'query': query, 'variables': variables}, timeout=120)
            if request.status_code == 200:
                return request.json()['data']['login']['accessToken']
            else:
                _logger.error("Login query connectrion error: {} {}".format(request.status_code, variables))
                raise Exception("Login query connectrion error: {} {}".format(request.status_code, variables))
        except Exception as e:
            _logger.error('Login query failed: {}'.format(e))
            raise Exception('Login query failed: {}'.format(e))

    @api.model
    def _get_face_devices(self, server, device_names=[]):
        """
            Return face id devices list
            NOTE: only ACTIVE status
        """
        query = """
                    query GetACLocations($search: String!, $page: Float!, $perPage: Float!) {
            acLocations(search: $search, page: $page, perPage: $perPage) {
                id
                name
                status
            }
            }
        """
        variables = {"search": "", "page": 1, "perPage": 100}
        server_uri = server.get('server_uri', '')
        server_login = server.get('server_login', '')
        server_password = server.get('server_password', '')
        headers = {'Authorization': self._get_api_token_face_server(server_uri, server_login, server_password)}
        try:
            request = requests.post(server_uri, json={'query': query, 'variables': variables}, headers=headers, timeout=120)
            if request.status_code == 200:
                devices_list = request.json()['data']['acLocations']
                if isinstance(devices_list, list):
                    if device_names:
                        devices_list = [d for d in devices_list if d['name'] in device_names]
                return devices_list
            else:
                _logger.error('Connection error {} {}'.format(request.status_code, variables))
                raise Exception("Connection error: {} {}".format(request.status_code, variables))
        except Exception as e:
            _logger.error('Error {}'.format(e))
            raise Exception("Error: {}".format(e))


    @api.model
    def _get_data_from_face_server(self, start_time, end_time, employee_ids=[], staff_no='', fix_data=False, location_name=None, continue_mode=False, test_mode=[], server={}, staff_codes=[]):
        """
            - Helper method to be used in _get_raw_data method
            - To get check_in, check_out data from CMC Face Server
            - Using api post graphql request to the server
            - TODO [X]: remove too close checks (same minutes)
            - continue_mode: Support to query continuously by default 5 minutes
            - test_mode: for serving testing. Name of attribute that return a faked api result. Access by self[test_mode]
            - server: usecase for getting face data from other server (not defined in the database). Ex: get data from HCMC to Hanoi
            - staff_codes: having higher priority than employee_ids
        """
        if test_mode:
            return test_mode
        if server:
            server_uri = server.get('server_uri', '')
            server_login = server.get('server_login', '')
            server_password = server.get('server_password')
        else:
            company_id = self.env.user.company_id or self.env['res.company'].browse([1])
            server_uri = 'http://{}/graphql'.format(company_id.face_server)
            server_login = company_id.face_login
            server_password = company_id.face_password

        try:
            # get api token
            api_token = self._get_api_token_face_server(server_uri, server_login, server_password)
            # get face data
            if not continue_mode:
                query = """
                    query reportTimekeeping($startTime: Date!, $endTime: Date!, $deviceIds: [String!]!, $page: Float!,
                        $perPage: Float!, $type: Float!, $textSearch: String!, $departmentIds: [String!]!, $companyIds: [String!]!){
                    reportTimekeeping(startTime:$startTime, endTime:$endTime, deviceIds: $deviceIds, page:$page, perPage:$perPage, type:$type, textSearch:$textSearch,
                        departmentIds:$departmentIds, companyIds:$companyIds){
                            id, cameraIp, integrationKey, deviceId, fullName,
                            company, department, time, type, count, SrcDevice{id,name}
                        }
                }
                """
            else:
                query = """
                    query reportTimekeeping2($startTime: Date!, $endTime: Date!, $deviceIds: [String!]!, $page: Float!,
                        $perPage: Float!, $type: Float!, $textSearch: String!, $departmentIds: [String!]!, $companyIds: [String!]!){
                    reportTimekeeping2(startTime:$startTime, endTime:$endTime, deviceIds: $deviceIds, page:$page, perPage:$perPage, type:$type, textSearch:$textSearch,
                        departmentIds:$departmentIds, companyIds:$companyIds){
                            id, cameraIp, integrationKey, deviceId, fullName,
                            company, department, time, dateCreated, type, count, SrcDevice{id,name}
                        }
                }
                """
            # TODO [X]: Request many time with smaller perPage for better performance (from CMC server side)
            # Using page
            page = 1
            perPage = 80
            res = []
            headers = {'Authorization': api_token}

            emp_domain = [('working', '=', True)]
            
            if not staff_codes:
                if employee_ids:
                    staff_codes = self.env['hr.employee'].browse(employee_ids).mapped('code')
                else:
                    staff_codes = self.env['hr.employee'].search(emp_domain).mapped('code')

            variables = {
                "startTime": start_time.strftime('%Y-%m-%d %H:%M:%S+00:00'),
                "endTime": end_time.strftime('%Y-%m-%d %H:%M:%S+00:00'),
                "deviceIds": [],
                "perPage": perPage,
                "type": 2,
                "textSearch": staff_codes[0] if len(staff_codes) == 1 else staff_no,  # Can search by  01 staff_no only
                "departmentIds": [],
                "companyIds": []
            }

            if location_name:
                device_id = self.env['hr.attendance.location'].with_context(active_test=False).search([('name', '=', location_name)])
                if device_id and device_id.terminal_id:
                    variables['deviceIds'] = [device_id.terminal_id]

            if staff_codes and not continue_mode:
                # Query by staff_code for better performance
                for staff_code in staff_codes:
                    page = 1  # reset page for each for...loop
                    while page:
                        variables.update({
                            'page': page,
                            'textSearch': staff_code
                        })
                        request = requests.post(server_uri, json={'query': query, 'variables': variables}, headers=headers, timeout=120)
                        if request.status_code == 200:
                            this_res = request.json()['data']['reportTimekeeping'] if not continue_mode else request.json()['data']['reportTimekeeping2']
                            if this_res:
                                res += this_res
                                page = 0 if len(this_res) < perPage else page + 1  # to avoid request one more time
                            else:
                                page = 0
                        else:
                            _logger.error('Connection error {} {}'.format(request.status_code, variables))
                            break
            else:
                while page:
                    variables['page'] = page
                    request = requests.post(server_uri, json={'query': query, 'variables': variables}, headers=headers, timeout=120)
                    if request.status_code == 200:
                        this_res = request.json()['data']['reportTimekeeping'] if not continue_mode else request.json()['data']['reportTimekeeping2']
                        if this_res:
                            res += this_res
                            page = 0 if len(this_res) < perPage else (page + 1)
                        else:
                            page = 0
                    else:
                        _logger.error('Connection error {} {}'.format(request.status_code, variables))
                        break
            
            rows = []
            if not fix_data:
                # Remove existed data
                # It may take times here but helping reduce time for _get_raw_data
                rows = [(r['integrationKey'],
                        (datetime.datetime.strptime(r['time'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(second=0, microsecond=0) + relativedelta(hours=utc_diff)).strftime('%Y/%m/%d %H:%M'),
                        r['SrcDevice']['name'] if r['SrcDevice'] is not None else '', r['SrcDevice']['id'] if r['SrcDevice'] is not None else r['deviceId']) for r in res if r is not None]
                
                # for r in res:
                #     row = (r['integrationKey'],
                #         (datetime.datetime.strptime(r['time'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(second=0, microsecond=0) + relativedelta(hours=utc_diff)).strftime('%Y/%m/%d %H:%M'),
                #         r['SrcDevice']['name'], r['SrcDevice']['id'])

                ###### METHOD 1
                #     # if self.search([('check_date', '>=', start_time.date() - relativedelta(days=1)), ('check_date', '<=', end_time.date()), ('raw_checks', 'like', json.dumps(row[:3]))]):  # !Note: Take time here
                #     #     continue

                ###### METHOD 2
                #     # NOTE: not fast enough
                #     # sql_string = """
                #     #     SELECT id FROM hr_attendance_raw WHERE ARRAY_TO_STRING(ARRAY[raw_checks], ',') like '%{}'
                #     # """.format(json.dumps(row[:3]))
                #     # self.env.cr.execute(sql_string)
                #     # if self.env.cr.fetchall():
                #     #     continue
                #     rows.append(row)
            else:
                rows = [(r['integrationKey'],
                        # (datetime.datetime.strptime(r['time'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(second=0, microsecond=0) + relativedelta(hours=utc_diff)).date(),
                        (datetime.datetime.strptime(r['time'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(second=0, microsecond=0) + relativedelta(hours=utc_diff)).strftime('%Y/%m/%d %H:%M'),
                        r['SrcDevice']['name'] if r['SrcDevice'] is not None else '', r['SrcDevice']['id'] if r['SrcDevice'] is not None else r['deviceId']) for r in res if r is not None]

            # cols = ['code', 'at_datetime', 'location', 'terminal_id']
            # result = [dict(zip(cols, row)) for row in set(rows)]
            return list(set(rows))
        except Exception as e:
            _logger.error('Error(s) happen while getting data from CMC Server: {}'.format(e))
            raise Exception(_('Error(s) happen: {}, {}, {}'.format(e, len([r for r in res if r is not None]), len(res))))
    
    @api.model
    def _get_raw_data_back(self, at_date=None, duration=None, employee_ids=[], department_ids=[], force_sync=False, location_name=None, servers=['CMC'], fix_data=False, continue_mode=False, test_mode=False, remote_info={}):
        """
            - Note: fix_data exists due to an error that override raw_checks data instead of append.
            - DO NOT need for future usage.
            - TODO [X]: last_query_dt has to update here to avoid last_query_dt and actual raw_at not in sync.
            - TODO [X]: DRY for continue_mode
            - TODO[]: continue_mode will use query2 that query by createdDate
            - force_sync: Force getting data (in case: change from manual_mode to auto_mode)
            - remote_info: used for getting data from a remote server to local server (HCMC to HN ex)
            {'server': {'server_uri', 'server_login', 'server_password'}, 'staff_codes': [], 'staff_map': {'remote_code': 'local_code'}}
            server: for getting rawdata from server not defined in the system. Need 'server_uri', 'server_login', 'server_password'
            staff_map: for mapping a staff from other server to that of staff at this server {'remote_staff_no': 'local_staff_no'}
        """
        start = process_time()
        company_id = self.env.user.company_id
        working_start = company_id.at_policy()['working_start']
        query_duration = company_id.query_duration or 5
        max_query_duration = 60
        last_query_dt = company_id.last_query_dt if (company_id.last_query_dt and company_id.last_query_dt <= (fields.Datetime.now() - relativedelta(minutes=query_duration))) else (fields.Datetime.now() - relativedelta(minutes=query_duration))

        check_in_time = datetime.time(working_start + 4 - utc_diff)  # 12:00
        half_day_time = datetime.time(working_start + 4 - utc_diff, 30)  # 12:30
        check_out_time = datetime.time(working_start + 5 - utc_diff)  # 13:00

        if at_date is None:
            at_date = fields.Date.context_today(self) if not continue_mode else company_id.last_query_dt.date() if company_id.last_query_dt else fields.Datetime.now()
        if duration is None:
            duration = (fields.Date.context_today(self) - at_date).days if not continue_mode else None
        max_hour_earlier = 6 if not continue_mode else 0
        if continue_mode:
            start_time = last_query_dt
            # TODO []: adjust end_time to closest to query_duration to now but the duration should not longer than 1 hour
            end_time = start_time + relativedelta(minutes=query_duration)
            time_now = fields.Datetime.now()
            if end_time < time_now and (time_now - relativedelta(minutes=max_query_duration)) <= start_time:
                end_time = time_now
            elif end_time < time_now and (time_now - relativedelta(minutes=max_query_duration)) > start_time:
                end_time = start_time + relativedelta(minutes=max_query_duration)
        else:
            start_time = self.env['hr.mixin'].get_at_datetime(at_date)
            end_time = start_time + relativedelta(days=duration + 1, seconds=-1)
        start_time = start_time - relativedelta(hours=max_hour_earlier)  # earlier than some hours to cover early_check_in cases

        # get early_offset employee_ids for better performance
        # The method get_at_date (called by date_by_start_hour) check early_offset option for each employee each day
        # that makes the whole process quite slow. Trying to minimize the usage of this method here
        early_request_domain = [('sub_request_type_id.code', '=', 'early_in'), ('at_id.at_date', '>=', at_date - relativedelta(days=1)), ('at_id.at_date', '<=', at_date + relativedelta(days=duration if not continue_mode else 0))]
        early_checkin_rule_domain = ["&",["early_offset",">",0],"!","|",["valid_start",">",at_date + relativedelta(days=(duration + 1) if not continue_mode else 1)],["valid_stop","<",at_date]]
        early_employee_ids = self.env['hr.attendance.request'].sudo().with_context(active_test=False).search(early_request_domain).mapped('employee_id')
        early_employee_ids |= self.env['hr.attendance.rule'].search(early_checkin_rule_domain).mapped('employee_ids')
        early_employee_codes = early_employee_ids.mapped('code')
        self = self.with_context(early_employee_ids=early_employee_ids.mapped('id'))

        for server in servers:
            emp_count = 0
            update_count = 0
            create_count = 0
            # get rows data
            try:
                if server == 'CMC':
                    server = remote_info['server'] if 'server' in remote_info else {}
                    staff_codes = remote_info['staff_codes'] if 'staff_codes' in remote_info else {}
                    rows = self._get_data_from_face_server(start_time=start_time, end_time=end_time, employee_ids=employee_ids, fix_data=fix_data, continue_mode=continue_mode, test_mode=test_mode, server=server, staff_codes=staff_codes)
                else:
                    rows = []
            except Exception as e:
                _logger.error('Cannot get data from API server. REF.: {}'.format(e))
                continue

            end = process_time()
            _logger.warning(_('Total {} records generated from API server {} in {} seconds'.format(len(rows), server, (end - start))))

            # This way much faster (19 seconds compare with 36 seconds and 51 seconds using _cr)
            # REMOVE existed data
            ##### METHOD 3
            new_rows = []
            if rows:
                raw_checks = self.search([('check_date', '>=', start_time.date() - relativedelta(days=1)), ('check_date', '<=', end_time.date())]).mapped(lambda e: json.loads(e.raw_checks or "[]"))
                raw_checks = [tuple(e) for e in list(chain(*raw_checks))]
                new_rows = [e for e in rows if (force_sync or tuple(e[:3]) not in raw_checks) or (e[0] in early_employee_codes)]
                # new_rows = [e for e in rows if tuple(e[:3]) not in raw_checks]
                cols = ['code', 'at_datetime', 'location', 'terminal_id']
                new_rows = [dict(zip(cols, row)) for row in new_rows]

            ats = {}  # {staff_code: {at_code: [row1, row2, ...]}}
            for row in new_rows:
                staff_code = row['code']
                if 'staff_map' in remote_info and staff_code in remote_info['staff_map']:
                    staff_code = remote_info['staff_map'][staff_code]
                    # employee_id = self.env['hr.employee'].search([('code', '=', remote_info['staff_map'][staff_code])]) or None
                # else:
                #     staff_code = row['code']
                employee_id = self.env['hr.employee'].search([('code', '=', staff_code)]) or None
                check_dt = self.date_by_start_hour(datetime.datetime.strptime(row['at_datetime'], '%Y/%m/%d %H:%M') - relativedelta(hours=utc_diff), employee_id=employee_id, tz=vn_tz)
                at_code = '-'.join(['AT', check_dt.strftime('%y%m%d'), staff_code])
                if staff_code not in ats.keys():
                    ats[staff_code] = {}
                if at_code not in ats[staff_code].keys():
                    ats[staff_code][at_code] = []
                ats[staff_code][at_code].append(row)

            location_status = []
            for staff_code, staff_ats in ats.items():
                emp_count += 1
                employee = self.env['hr.employee'].search([('code', '=', staff_code)])
                if not employee:
                    continue
                for at_code, checks in staff_ats.items():
                    update_related_at = False
                    checks_data = [list(r.values()) for r in checks]

                    raw_at = self.env['hr.attendance.raw'].sudo().with_context(active_test=False).search([('at_code', '=', at_code)])
                    # unlink raw_at if force_synce to avoid from duplicate data
                    if raw_at and force_sync:
                        raw_at.sudo().unlink()
                        raw_at = self.env['hr.attendance.raw']

                    # TODO [X]: When get data by location => need to take care data from other locations 
                    # to make sure the correctioness of data
                    # TODO [X]: merge v with current raw_checks
                    if raw_at and len(raw_at['raw_checks']) > 0 and raw_at.employee_id not in early_employee_ids:
                        checks_data += json.loads(raw_at.raw_checks)
                        checks_data = list({tuple(e) for e in checks_data})
                    
                    checks_data.sort(key=lambda e: e[1])
                    raw_checks_json = json.dumps([e[:3] for e in checks_data])

                    new_v = {
                        'at_date': datetime.datetime.strptime(at_code.split('-')[1], '%y%m%d').date(),
                        'first_check': vn_tz.localize(datetime.datetime.strptime(checks_data[0][1], '%Y/%m/%d %H:%M')).astimezone(utc).replace(tzinfo=None),
                        'first_location': checks_data[0][2] or False,
                        'first_terminal_id': checks_data[0][3] if len(checks_data[0]) == 4 else False,
                        'last_check': vn_tz.localize(datetime.datetime.strptime(checks_data[-1][1], '%Y/%m/%d %H:%M')).astimezone(utc).replace(tzinfo=None) if len(checks_data) > 1 else False,
                        'last_location': checks_data[-1][2] if len(checks_data) > 1 else False,
                        'last_terminal_id': checks_data[-1][3] if len(checks_data[-1]) == 4 else False
                    }

                    if len(checks_data) == 1:
                        # TODO [X]: more smart ways to determine check_in and check_out
                        # TODO: if checkout at 12:00 and not checkin, the system will determine as check_in at 12:00 and it will be an error if user request
                        # working_time for check_in at 8:00 for example. Need to check at record here first
                        related_at = self.env['hr.attendance'].search([('code', '=', at_code)])
                        wt_request = related_at and related_at.at_request_ids.filtered(lambda r: r.request_type == 'working_time' and r.state not in ['draft', 'refuse'])
                        check_raw = new_v['first_check']

                        # 12:01 ~ 12:29 or >= 13:00
                        is_check_out = check_raw >= datetime.datetime.combine(new_v['at_date'], check_out_time) or (check_raw > datetime.datetime.combine(new_v['at_date'], check_in_time) and check_raw < datetime.datetime.combine(new_v['at_date'], half_day_time))
                        is_request_check_in = wt_request and bool(wt_request.request_in) and not bool(wt_request.request_out)
                        switch = is_check_out or is_request_check_in

                        # _logger.warning(f'===== {switch}, {bool(wt_request.request_in) + bool(wt_request.request_out)}')
                        if switch:
                            new_v.update({
                                'last_check': new_v['first_check'],
                                'last_location': new_v['first_location'],
                                'last_terminal_id': new_v['first_terminal_id'],
                                'first_check': False,
                                'first_location': False,
                                'first_terminal_id': False
                            })

                    v = new_v

                    # TODO [X]: check and create location
                    first_loc = self.env['hr.attendance.location'].with_context(active_test=False).search([('name', '=', v['first_location'])])
                    first_terminal_id = False
                    if v['first_location'] and not first_loc or (first_loc and not first_loc.terminal_id):
                        first_terminal_id = v['first_terminal_id']
                    if not first_loc and v['first_location']:
                        first_loc = first_loc.create({'name': v['first_location'], 'code': first_loc.next_code(), 'terminal_id': first_terminal_id})
                    if first_loc and not first_loc.terminal_id:
                        first_loc.terminal_id = first_terminal_id
                    v['first_location_id'] = first_loc.id

                    last_loc = self.env['hr.attendance.location'].with_context(active_test=False).search([('name', '=', v['last_location'])])
                    last_terminal_id = False
                    if v['last_location'] and not last_loc or (last_loc and not last_loc.terminal_id):
                        last_terminal_id = v['last_terminal_id']
                    if not last_loc and v['last_location']:
                        last_loc = last_loc.create({'name': v['last_location'], 'code': last_loc.next_code(), 'terminal_id': last_terminal_id})
                    if last_loc and not last_loc.terminal_id:
                        last_loc.terminal_id = last_terminal_id
                    v['last_location_id'] = last_loc.id

                    if raw_at:
                        if not raw_at.manual_mode:
                            # TODO [X]: check carefully here - NOT work correcty when want to force update (force_sync)
                            update = {}
                            if v['at_date'] == raw_at.check_date:
                                if not v['first_check'] or (v['first_check'] and v['first_check'] != raw_at.check_in):
                                    update['check_in'] = v['first_check']
                                if not v['last_check'] or (v['last_check'] and v['last_check'] != raw_at.check_out):
                                    update['check_out'] = v['last_check']
                                if not v['first_location_id'] or (v['first_location_id'] and v['first_location_id'] != raw_at.first_location_id.id):
                                    update['first_location_id'] = v['first_location_id']
                                if not v['last_location_id'] or (v['last_location_id'] and v['last_location_id'] != raw_at.last_location_id.id):
                                    update['last_location_id'] = v['last_location_id']
                                if update or force_sync:  # only allow force_sync if dont use location_name
                                    update['raw_checks'] = raw_checks_json
                                    raw_at.write(update)
                                    update_related_at = True
                                    location_status.append((v['at_date'], update.get('first_location_id', False) or update.get('last_location_id', False) or None))
                                    update_count += 1

                    else:
                        try:
                            raw_at = raw_at.create({
                                'at_code': at_code,
                                'check_date': v['at_date'],
                                'employee_id': employee.id,
                                'check_in': v['first_check'],
                                'check_out': v['last_check'],
                                'first_location_id': v['first_location_id'],
                                'last_location_id': v['last_location_id'],
                                'raw_checks': raw_checks_json
                            })
                            update_related_at = True
                            location_status.append((v['at_date'], v.get('first_location_id', False) or v.get('last_location_id', False) or None))
                            create_count += 1
                        except Exception as e:
                            _logger.error('===== {} {} {}'.format(e, at_code, v))
                    
                    if raw_at and continue_mode and update_related_at:
                        self._sync_attendance_record(at_date=raw_at['check_date'], duration=0, employee_ids=[employee.id])

            # update data status table
            for pair in location_status:
                self.env['hr.attendance.raw.data.status']._update_data_status(at_date=pair[0], machine_location_ids=[pair[1]] if pair[1] else [])
            
            _logger.warning(_("""Of these {} employees{}, there are {} records from {} server,
            {} records updated and {} ones created!""".format(emp_count, ' in ' + location_name if location_name else '', len(rows), server, update_count, create_count)))
            end = process_time()
            _logger.warning(_('Total process time for _get_raw_data: {} seconds'.format(end - start)))

            # Update back last_query_dt
            if continue_mode:
                company_id.last_query_dt = end_time - relativedelta(second=0)
            if not continue_mode and not employee_ids and not department_ids and not location_name and end_time >= fields.Datetime.now():
                # reset last_query_dt for future continue_mode running properly
                company_id.last_query_dt = False

    def _get_raw_data(self, at_date=None, duration=None, employee_ids=[], department_ids=[], force_sync=False, location_name=None, servers=['CMC'], fix_data=False, continue_mode=False, test_mode=False, remote_info={}, manual_query_duration=False):
        start = process_time()
        company_id = self.env.user.company_id
        query_duration = manual_query_duration or company_id.query_duration or 5
        max_query_duration = 60
        
        # Calculate last query window
        last_query_dt = company_id.last_query_dt if (company_id.last_query_dt and company_id.last_query_dt <= (fields.Datetime.now() - relativedelta(minutes=query_duration))) else (fields.Datetime.now() - relativedelta(minutes=query_duration))

        if at_date is None:
            at_date = fields.Date.context_today(self) if not continue_mode else company_id.last_query_dt.date() if company_id.last_query_dt else fields.Datetime.now()
        if duration is None:
            duration = (fields.Date.context_today(self) - at_date).days if not continue_mode else None
        
        max_hour_earlier = 6 if not continue_mode else 0
        if continue_mode:
            start_time = last_query_dt
            end_time = start_time + relativedelta(minutes=query_duration)
            time_now = fields.Datetime.now()
            if end_time < time_now and (time_now - relativedelta(minutes=max_query_duration)) <= start_time:
                end_time = time_now
            elif end_time < time_now and (time_now - relativedelta(minutes=max_query_duration)) > start_time:
                end_time = start_time + relativedelta(minutes=max_query_duration)
        else:
            start_time = self.env['hr.mixin'].get_at_datetime(at_date)
            end_time = start_time + relativedelta(days=duration + 1, seconds=-1)
        
        # Adjust start_time to cover early check-ins
        query_start_time = start_time - relativedelta(hours=max_hour_earlier)

        for server in servers:
            rows = []
            try:
                if server == 'CMC':
                    srv_cfg = remote_info.get('server', {})
                    staff_codes = remote_info.get('staff_codes', {})
                    if srv_cfg and not staff_codes:
                        # !NOTE: do not run in this case, it will get all checkin data from remote server
                        _logger.warning('Skip get data from CMC remote server because there is no staff_codes')
                        rows = []
                    else:
                        rows = self._get_data_from_face_server(start_time=query_start_time, end_time=end_time, employee_ids=employee_ids, fix_data=fix_data, continue_mode=continue_mode, test_mode=test_mode, server=srv_cfg, staff_codes=staff_codes)
                else:
                    rows = []

                if rows:
                    self._handle_raw_data(
                        rows=rows,
                        force_sync=force_sync,
                        continue_mode=continue_mode,
                        remote_info=remote_info,
                        location_name=location_name,
                        server_label=server
                    )
            except Exception as e:
                _logger.error('Cannot get data from API server {}. REF.: {}'.format(server, e))

        # Update sync state
        if continue_mode:
            company_id.last_query_dt = end_time - relativedelta(second=0)
        if not continue_mode and not employee_ids and not department_ids and not location_name and end_time >= fields.Datetime.now():
            company_id.last_query_dt = False
        
        _logger.warning(_('Total process time for _get_raw_data: {} seconds'.format(process_time() - start)))
    
    
    def _handle_raw_data(self, rows, force_sync=False, continue_mode=False, remote_info={}, server_label='Unknown', location_name=None):
        """
        Fixed Version: Added 'location_name' to arguments to prevent TypeError.
        Handles ISO time, +7 shift, and Device Name mapping.
        Handles remote staff mapping.
        """
        if not rows:
            return

        company_id = self.env.user.company_id
        working_start = company_id.at_policy()['working_start']
        
        # Original UTC thresholds
        check_in_time = datetime.time(working_start + 4 - utc_diff)  
        half_day_time = datetime.time(working_start + 4 - utc_diff, 30)  
        check_out_time = datetime.time(working_start + 5 - utc_diff)  

        ats = {}
        for row in rows:
            staff_code = row[0]
            loc_is_local = True
            if 'staff_map' in remote_info and staff_code in remote_info['staff_map']:
                staff_code = remote_info['staff_map'][staff_code]
                loc_is_local = False

            employee = self.env['hr.employee'].sudo().search([('code', '=', staff_code)], limit=1)
            if not employee:
                continue

            try:
                # 1. Keep time exactly as provided by API for the JSON log
                # Input: '2026-03-25T08:10:13' -> '2026/03/25 08:10'
                clean_input = row[1].replace('T', ' ').replace('-', '/')
                time_str = clean_input[:16] 
                
                dt_utc_raw = datetime.datetime.strptime(time_str, '%Y/%m/%d %H:%M')
                
                # 2. Identify Attendance Day
                check_dt = self.date_by_start_hour(dt_utc_raw - relativedelta(hours=utc_diff), employee_id=employee, tz=vn_tz)
                at_code = '-'.join(['AT', check_dt.strftime('%y%m%d'), staff_code])
                
                dev_name = row[2] if (len(row) > 2 and row[2]) else location_name or 'Unknown'
                term_id = row[3] if len(row) > 3 else False

                ats.setdefault(staff_code, {}).setdefault(at_code, []).append([
                    staff_code, time_str, dev_name, term_id
                ])
            except Exception as e:
                _logger.error("Normalization failed for row %s: %s", row, e)
                continue

        location_status = []
        for staff_code, staff_ats in ats.items():
            employee = self.env['hr.employee'].sudo().search([('code', '=', staff_code)], limit=1)
            
            for at_code, new_checks in staff_ats.items():
                raw_at = self.env['hr.attendance.raw'].sudo().with_context(active_test=False).search([('at_code', '=', at_code)], limit=1)

                if raw_at and force_sync:
                    raw_at.unlink()
                    raw_at = self.env['hr.attendance.raw']

                # --- MERGE & SORT ---
                existing_data = json.loads(raw_at.raw_checks or "[]") if raw_at else []
                combined = existing_data + [nc[:3] for nc in new_checks]
                unique_list = sorted(list(set(tuple(x) for x in combined)), key=lambda x: x[1])
                raw_checks_json = json.dumps(unique_list)

                # --- PREPARE RECORD (Localize for Odoo) ---
                first_row = unique_list[0]
                last_row = unique_list[-1] if len(unique_list) > 1 else False
                
                # Convert string to UTC Datetime object for the DB
                def to_utc(t_str):
                    dt = datetime.datetime.strptime(t_str, '%Y/%m/%d %H:%M')
                    # Use vn_tz.localize if the API was local, 
                    # OR just return dt if API was already UTC (matching your original)
                    return vn_tz.localize(dt).astimezone(utc).replace(tzinfo=None)

                v = {
                    'at_date': datetime.datetime.strptime(at_code.split('-')[1], '%y%m%d').date(),
                    'first_check': to_utc(first_row[1]),
                    'first_loc_name': first_row[2],
                    'first_tid': next((nc[3] for nc in new_checks if nc[1] == first_row[1]), False),
                    'last_check': to_utc(last_row[1]) if last_row else False,
                    'last_loc_name': last_row[2] if last_row else False,
                    'last_tid': next((nc[3] for nc in new_checks if last_row and nc[1] == last_row[1]), False) if last_row else False
                }

                # --- SWITCH LOGIC ---
                if len(unique_list) == 1:
                    related_at = self.env['hr.attendance'].sudo().search([('code', '=', at_code)], limit=1)
                    wt_req = related_at and related_at.at_request_ids.filtered(lambda r: r.request_type == 'working_time' and r.state not in ['draft', 'refuse'])
                    
                    check_raw = v['first_check'] 
                    # is_out = check_raw.time() >= check_out_time or (check_raw.time() > check_in_time and check_raw.time() < half_day_time)
                    is_out = check_raw >= datetime.datetime.combine(v['at_date'], check_out_time) or (check_raw > datetime.datetime.combine(v['at_date'], check_in_time) and check_raw < datetime.datetime.combine(v['at_date'], half_day_time))
                    is_req_in = wt_req and bool(wt_req.request_in) and not bool(wt_req.request_out)
                    if is_out or is_req_in:
                        v.update({
                            'last_check': v['first_check'], 'last_loc_name': v['first_loc_name'], 'last_tid': v['first_tid'],
                            'first_check': False, 'first_loc_name': False, 'first_tid': False
                        })

                # --- LOCATION & WRITE ---
                v['first_location_id'] = self._get_or_create_at_location(v['first_loc_name'], v['first_tid'], loc_is_local)
                v['last_location_id'] = self._get_or_create_at_location(v['last_loc_name'], v['last_tid'], loc_is_local)

                vals = {
                    'check_in': v['first_check'], 'check_out': v['last_check'],
                    'first_location_id': v['first_location_id'], 'last_location_id': v['last_location_id'],
                    'raw_checks': raw_checks_json
                }

                if raw_at:
                    if not raw_at.manual_mode: raw_at.write(vals)
                else:
                    raw_at = self.env['hr.attendance.raw'].create(dict(vals, **{
                        'at_code': at_code, 'check_date': v['at_date'], 'employee_id': employee.id,
                    }))

                if raw_at and continue_mode:
                    location_status.append((v['at_date'], v['first_location_id'] or v['last_location_id']))
                    self._sync_attendance_record(at_date=raw_at.check_date, duration=0, employee_ids=[employee.id])

        for d, l in list(set(location_status)):
            self.env['hr.attendance.raw.data.status']._update_data_status(at_date=d, machine_location_ids=[l])

    def _get_or_create_at_location(self, loc_name, terminal_id, is_local=True):
        """
        Find by Device Name (loc_name)
        Action: Create if missing, Update Terminal ID if missing on name match.
        If data is got from remote location, set is_local is False
        """
        if not loc_name:
            return False
            
        loc_model = self.env['hr.attendance.location'].sudo().with_context(active_test=False)
        
        # Try find by Name
        loc = loc_model.search([('name', '=', loc_name)], limit=1)
        
        # Try find by Terminal ID if Name failed
        # if not loc and terminal_id:
        #     loc = loc_model.search([('terminal_id', '=', terminal_id)], limit=1)
            
        if not loc:
            # Create using the Name as primary
            loc = loc_model.create({
                'name': loc_name,
                'terminal_id': terminal_id,
                'code': loc_model.next_code() if hasattr(loc_model, 'next_code') else loc_name,
                'is_local': is_local
            })
        elif terminal_id and not loc.terminal_id:
            # Link Terminal ID to existing named record
            loc.write({'terminal_id': terminal_id})
            
        return loc.id


    @api.model
    def _repair_duplicate_raw_data(self):
        for raw in self.search([]):
            raw_checks = [tuple(r) for r in json.loads(raw['raw_checks']) ]
            if len(raw_checks) > len(set(raw_checks)):
                _logger.warning(_('Duplicate found! {}'.format(raw.at_code)))
                raw.raw_checks = json.dumps(list(set(raw_checks)))

    @api.model
    def _handle_late_data(self):
        """
            - model method that get and sync data for locations that not return data ontime
            - only for current month
        """
        today = fields.Date.context_today(self)
        start_date = self.env['hr.attendance'].get_start_dt(a_date=today, for_month=True)
        status_ids = self.env['hr.attendance.raw.data.status'].search([('at_date', '>=', start_date)])
        for s in status_ids:
            if not s.data_status:
                # skip holiday for better performance
                if self.env['hr.attendance']._is_holiday(a_date=s.at_date):
                    s.action_get_machine_data()

    @api.onchange('is_delete')
    def _onchange_is_delete(self):
        for r in self:
            if r.is_delete:
                if not r.manual_mode:
                    r.manual_mode = True
                # TODO [X]: delete related attendance records
                related_at = self.env['hr.attendance'].sudo().search([('code', '=', r.at_code)])
                related_at.action_revise()
                related_at.unlink()

    @api.onchange('manual_mode')
    def _onchange_manual_mode(self):
        for r in self:
            if not r.manual_mode and r.is_delete:
                r.is_delete = False

    @api.model
    def _change_data_structure(self):
        # DANGER
        staff_count = 0
        for e in self.env['hr.employee'].sudo().with_context(active_test=False).search([]):
            staff_count += 1
            at_raw_count = 0
            for at_raw in self.search([('employee_id', '=', e.id)]):
                at_raw_count += 1
                raw_checks = json.loads(at_raw.raw_checks) if at_raw.raw_checks else []
                for row in raw_checks:
                    if len(row) == 4:
                        row.remove(row[1])
                at_raw.raw_checks = json.dumps(raw_checks)
            print('{}. {}: {} at_raws'.format(staff_count, e.name, at_raw_count))

    
    @api.model
    def _backup_listener_watchdog(self):
        """
        Runs every 5 minutes.
        Compares newest FaceResult with newest hr.attendance.raw.
        If gap > 1 minute → listener may be down → sync + notify admin.
        """
        params = self.env['ir.config_parameter'].sudo()
        
        # ── Face DB config ────────────────────────────────────────────
        face_db_config = {
            'host':     params.get_param('face_db.host'),
            'port':     int(params.get_param('face_db.port', '5432')),
            'dbname':   params.get_param('face_db.name'),
            'user':     params.get_param('face_db.user'),
            'password': params.get_param('face_db.password'),
        }
        
        # ── Nextcloud Talk config ─────────────────────────────────────
        nc_url      = params.get_param('nextcloud.url')
        nc_bot_user = params.get_param('nextcloud.bot_user')
        nc_bot_pass = params.get_param('nextcloud.bot_pass')
        admin_logins = [x.strip() for x in params.get_param('attendance.admin_logins', '').split(',') if x.strip()]

        # Odoo base_url
        odoo_url = params.get_param('web.base.url')
        
        # ── Step 1: Get newest FaceResult time ────────────────────────
        try:
            conn = psycopg2.connect(**face_db_config)
            cur = conn.cursor()
            cur.execute("""
                SELECT MAX(time) FROM "FaceResult"
                WHERE time >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 hour'
            """)
            row = cur.fetchone()
            cur.close()
            conn.close()
            newest_face = row[0] if row and row[0] else None
        except Exception as e:
            _logger.error("Watchdog: Cannot connect to Face DB: %s", e)
            return
        
        if not newest_face:
            _logger.info("Watchdog: No recent FaceResult in last hour — skipping")
            return
        
        # ── Step 2: Get newest hr.attendance.raw write_date ───────────
        last_raw = self.search([], order='write_date desc', limit=1)
        last_updated = last_raw.write_date if last_raw else None
        
        if not last_updated:
            _logger.warning("Watchdog: No attendance.raw records found")
            # Still fire sync just in case
            self._get_raw_data(servers=['CMC'], continue_mode=True)
            return
        
        # ── Step 3: Compare ───────────────────────────────────────────
        # newest_face is UTC from Face DB
        # last_updated is UTC from Odoo
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        if newest_face.tzinfo:
            newest_face = newest_face.replace(tzinfo=None)  # strip tz for comparison
        
        # 1. How behind is Odoo compared to FaceID?
        gap_with_odoo = (newest_face - last_updated).total_seconds()
        
        # 2. How fresh is the data in FaceID right now?
        # If the check-in happened 5 seconds ago, it's too early to panic.
        freshness_in_face_db = (now_utc - newest_face).total_seconds()

        _logger.info(
            "Watchdog: newest face=%s, last_raw=%s, face_freshness=%.0fs, odoo_gap=%.0fs",
            newest_face, last_updated, freshness_in_face_db, gap_with_odoo
        )

        # Logic: 
        # Only trigger if Odoo is behind (gap > 60s) 
        # AND the record in FaceID is old enough that the listener SHOULD have finished (e.g., > 20s)
        
        GRACE_PERIOD = 20  # seconds to allow listener to work
        MAX_ALLOWED_GAP = 60 # seconds before we consider listener "down"
        
        if gap_with_odoo <= MAX_ALLOWED_GAP:
            _logger.info("Watchdog: Odoo is up to date (Gap <= 1 min). Skipping.")
            return
        
        if freshness_in_face_db < GRACE_PERIOD:
            _logger.info(
                "Watchdog: Gap is %.0fs, but newest FaceID record is only %.0fs old. "
                "Giving listener more time. Skipping.", 
                gap_with_odoo, freshness_in_face_db
            )
            return
        
        # ── Step 4: Gap > 1 min AND record isn't brand new → Sync + Notify
        _logger.warning(
            "Watchdog: Gap %.0f seconds — listener may be down! Running backup sync...",
            gap_with_odoo
        )
        
        # Notify admins via Talk
        if nc_url and nc_bot_user and nc_bot_pass and admin_logins:
            vn_face_time = (newest_face + timedelta(hours=7)).strftime("%d-%b-%Y %H:%M:%S")
            vn_last_time = (last_updated + timedelta(hours=7)).strftime("%d-%b-%Y %H:%M:%S")
            msg = (
                f"⚠️ Checkin listener may be down at server {odoo_url}!\n"
                f"Newest checkin in Face DB: {vn_face_time}\n"
                f"Last sync in Odoo: {vn_last_time}\n"
                f"Gap: {int(gap_with_odoo)}s — backup sync activated."
            )
            for login in admin_logins:
                try:
                    room = requests.post(
                        f"{nc_url}/ocs/v1.php/apps/spreed/api/v4/room",
                        auth=(nc_bot_user, nc_bot_pass),
                        headers={"OCS-APIRequest": "true", "Accept": "application/json"},
                        data={"roomType": 1, "invite": login},
                        timeout=10
                    )
                    token = room.json()["ocs"]["data"]["token"]
                    requests.post(
                        f"{nc_url}/ocs/v1.php/apps/spreed/api/v1/chat/{token}",
                        auth=(nc_bot_user, nc_bot_pass),
                        headers={"OCS-APIRequest": "true"},
                        data={"message": msg},
                        timeout=10
                    )
                    _logger.info("Watchdog: Notified %s via Talk", login)
                except Exception as e:
                    _logger.error("Watchdog: Failed to notify %s: %s", login, e)
        
        # Run backup sync
        # Get correct query duration to update other wise will use default 5 minutes
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) # correct way to get utc time
        manual_query_duration = ((now - newest_face).total_seconds() // 60) + 1
        _logger.info(f"Watchdog: Query new data for duration of {manual_query_duration} minutes!")
        try:
            self._get_raw_data(servers=['CMC'], continue_mode=True, manual_query_duration=manual_query_duration)
            _logger.info("Watchdog: Backup sync completed")
        except Exception as e:
            _logger.error("Watchdog: Backup sync failed: %s", e)
    
    # ===== API =====
    def write(self, values):
        # self.ensure_one()
        # r = self
        _super = super().write(values)
        if 'manual_mode' in values:  # !NOTE: manual_mode is Boolean
            if not self.manual_mode:
                self._get_raw_data(at_date=self.check_date, duration=0, employee_ids=[self.employee_id.id], force_sync=True)
            self._sync_attendance_record(at_date=self.check_date, duration=0, employee_ids=[self.employee_id.id])
        return _super

    @api.constrains('check_in', 'check_out', 'first_location_id', 'last_location_id')
    def validate_check_and_location(self):
        for r in self:
            if sum([bool(r.check_in), bool(r.first_location_id)]) == 1 or sum([bool(r.check_out), bool(r.last_location_id)]) == 1:
                raise ValidationError(_('Check and Location should both having data or both none!'))
    
    @api.model
    def auto_archive(self):
        today = fields.Date.context_today(self)
        date_to_archive = self.env['hr.attendance'].get_start_dt(today, for_month=True) - relativedelta(years=1, months=-1)
        # start_date = self.env['hr.attendance'].get_start_dt(a_date=today, for_month=True)
        # last_month_start_date = start_date - relativedelta(months=1)
        domain = [('check_date', '<', date_to_archive)]
        raw_ats = self.search(domain)
        raw_ats.write({'active': False})

    # ===== CONSTRAINS =====
    @api.constrains('check_in', 'check_out')
    def _check_validity(self):
        for raw_at in self:
            if raw_at.check_in and raw_at.check_out:
                if raw_at.check_in > raw_at.check_out:
                    # print('=====', raw_at.at_code, raw_at.check_in, raw_at.check_out)
                    raise ValidationError(_('check_out time must be after check_in time! REF: {} {} {}'.format(raw_at.at_code, raw_at.check_in, raw_at.check_out)))
                
    
    # ===== FOR TESTING =====
    @api.model
    def count_down(self, end, begin=0):
            from time import sleep
            print(f'===== BEGIN COUNT from {end} to {begin + 1}')
            while end > begin:
                print('=====', end)
                end -= 1
                sleep(1)
    
    @api.model
    def test_time_out(self, batchs):
        """
            - Keep the method running for [batchs] minutes
            - batchs: array of minutes
        """
        # batchs = [110, 40, 20]
        for i, batch in enumerate(batchs):
            end = sum(batchs[i:])
            begin = end - batchs[i]
            self.env['hr.attendance.raw'].with_delay().count_down(end, begin)



class KderpHRAttendanceRawDataStatus(models.Model):
    _name = 'hr.attendance.raw.data.status'
    _description = 'HR Attendance Raw Data Status'
    _order = 'at_date desc'

    name = fields.Char('Description', compute='compute_data_status', store=True)
    at_date = fields.Date(required=True)
    machine_location_id = fields.Many2one('hr.attendance.location', required=True, context={'active_test': False})
    data_status = fields.Boolean(compute='compute_data_status', store=True)
    active = fields.Boolean(default=True)
    last_updated_dt = fields.Datetime(compute='compute_data_status', store=True)

    _data_status_unique = models.Constraint('unique(at_date, machine_location_id)', 'Date, location unique!')

    # Generate data
    @api.model
    def _update_data_status(self, at_date=None, machine_location_ids=[]):
        """
            - Generate data_status for a time period
            - Run in server action
        """
        today = fields.Date.context_today(self)
        if not at_date or type(at_date) is not datetime.date:
            at_date = today
        if not machine_location_ids:
            machine_location_ids = self.env['hr.attendance.location'].search([]).mapped('id')

        for machine_location_id in  machine_location_ids:
            data_status_id = self.with_context(active_test=False).search([('at_date', '=', at_date), ('machine_location_id', '=', machine_location_id)])
            if not data_status_id:
                data_status_id = self.create({
                    'at_date': at_date,
                    'machine_location_id': machine_location_id
                })
            else:
                data_status_id.compute_data_status()

    # ===== API =====
    @api.depends('at_date', 'machine_location_id')
    def compute_data_status(self):
        """
            - Compute data status
            - Return string value:
                + True: having data
                + False: do not have data
        """
        Raw = self.env['hr.attendance.raw']
        for s in self:
            raw_domain = [('check_date', '=', s.at_date), '|', ('first_location_id', '=', s.machine_location_id.id), ('last_location_id', '=', s.machine_location_id.id)]
            raw_data = Raw.search(raw_domain)
            if not raw_data:
                s.data_status = False
                s.name = _('No data available for this machine')
            else:
                s.data_status = True
                s.name = _('Data avaiblable for this machine. Total records: {}'.format(len(raw_data)))
                s.last_updated_dt = max(raw_data.mapped('write_date'))

    @api.model
    def auto_archive(self):
        today = fields.Date.context_today(self)
        date_to_archive = self.env['hr.attendance'].get_start_dt(today, for_month=True) - relativedelta(years=1, months=-1)
        # start_date = self.env['hr.attendance'].get_start_dt(a_date=today, for_month=True)
        # last_month_start_date = start_date - relativedelta(months=1)
        domain = [('at_date', '<', date_to_archive)]
        records = self.search(domain)
        records.write({'active': False})

    # ===== ACTIONS =====
    def action_get_machine_data(self):
        for s in self:
            self.env['hr.attendance.raw']._get_raw_data(at_date=s.at_date, duration=0, location_name=s.machine_location_id.name)
            self.env['hr.attendance.raw']._sync_attendance_record(at_date=s.at_date, duration=0, location_name=s.machine_location_id.name)



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
try:
    import pyodbc  # SQL Server (bizone) link: stage E, not in the Odoo 19 image
except ImportError:
    pyodbc = None
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



class KderpHrAttendanceLocation(models.Model):
    _name = 'hr.attendance.location'
    _inherit = 'kderp.base.model'
    _description = 'HR Attendance location'

    name = fields.Char('Location', required=True)
    code = fields.Char('Location code', required=True, help="Use format L####")
    static_ip = fields.Char()
    note = fields.Text()
    active = fields.Boolean(default=True)
    inactive_date = fields.Date(help="The date the machine had not use anymore.")
    show_name = fields.Char()
    terminal_id = fields.Char()
    is_local = fields.Boolean(default=True, help='Wheather a face machine managed by the face server defined in the ATT local server')

    def name_get(self):
        result = []
        for l in self:
            show_name = l.show_name if l.show_name else l.name.replace(' Face', '')
            result.append((l.id, show_name))
        return result

    @api.model
    def next_code(self):
        # NOTE: temporary
        # NOTE: Check carefully
        if not self.search([]):
            last = 0
        else:
            last = max(self.search([]).mapped(lambda l: int(l.code[1:])))
        next = last + 1
        next_code = 'L' + '0' * (4 - len(str(next))) + str(next)
        return next_code

    # @api.multi
    # def name_get(self):
    #     result = []
    #     for l in self:
    #         result.append((l.id, l.name))
    #     return result



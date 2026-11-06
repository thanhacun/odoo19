"""Odoo 12 resource.calendar methods that the attendance code calls and Odoo 19 turned into *_batch methods.

Plus the public-holiday intervals of the OCA module hr_holidays_public (no 19.0 version): `_public_holidays_leave_intervals`
and the context flag `exclude_public_holidays` on leave intervals. Same names and results as Odoo 12.
"""
from datetime import datetime, time

from dateutil import rrule
from pytz import timezone

from odoo import models
from odoo.tools.intervals import Intervals


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    def _attendance_intervals(self, start_dt, end_dt, resource=None, domain=None, tz=None):
        """Odoo 12 signature. Intervals of the calendar attendance lines between two datetimes (lunch lines excluded)."""
        if resource is None:
            resource = self.env['resource.resource']
        return self._attendance_intervals_batch(start_dt, end_dt, resources=resource, domain=domain, tz=tz)[resource.id]

    def _public_holidays_leave_intervals(self, start_dt, end_dt, employee_id, tz):
        """Public holidays of the employee (or all, employee_id False) as intervals, one per holiday date.
        Copy of hr_holidays_public/models/resource_calendar.py (Odoo 12, OCA)."""
        HrHolidaysPublic = self.env['hr.holidays.public']
        leaves = []
        if start_dt.year != end_dt.year:
            # a leave over 2 years: rrule needs one more year to give both years
            end_dt = end_dt.replace(year=end_dt.year + 1)
        for day in rrule.rrule(rrule.YEARLY, dtstart=start_dt, until=end_dt):
            lines = HrHolidaysPublic.get_holidays_list(day.year, employee_id=employee_id)
            for line in lines:
                leaves.append((
                    datetime.combine(line.date, time.min).replace(tzinfo=tz),
                    datetime.combine(line.date, time.max).replace(tzinfo=tz),
                    self.env['resource.calendar.leaves'],
                ))
        return Intervals(leaves)

    def _leave_intervals(self, start_dt, end_dt, resource=None, domain=None, tz=None):
        res = super()._leave_intervals(start_dt, end_dt, resource=resource, domain=domain, tz=tz)
        if self.env.context.get('exclude_public_holidays'):
            tz = tz or timezone((resource or self).tz)
            public_holidays = self._public_holidays_leave_intervals(start_dt, end_dt, self.env.context.get('employee_id', False), tz)
            res = res | public_holidays
        return res

    def _work_intervals(self, start_dt, end_dt, resource=None, domain=None, tz=None):
        """Odoo 12: attendance intervals minus leave intervals (leaves = resource.calendar.leaves, plus public holidays when the
        context flag exclude_public_holidays is set)."""
        return self._attendance_intervals(start_dt, end_dt, resource, domain=None, tz=tz) - self._leave_intervals(start_dt, end_dt, resource, domain, tz=tz)

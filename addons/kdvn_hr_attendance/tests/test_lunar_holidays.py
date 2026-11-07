# -*- coding: utf-8 -*-
"""Vietnamese public holidays that follow the lunar calendar (Tet eve + 3 days, Hung Kings 10/3) come from the
`lunarcalendar` library (Odoo 12 does the same). Dates below are the official ones. Skipped if the library is not installed."""
import datetime
from odoo.tests import common, tagged

try:
    import lunarcalendar  # noqa: F401
except ImportError:
    lunarcalendar = None

# year: (Tet eve, Tet day 1, Hung Kings)
EXPECTED = {
    2026: (datetime.date(2026, 2, 16), datetime.date(2026, 2, 17), datetime.date(2026, 4, 26)),
    2027: (datetime.date(2027, 2, 5), datetime.date(2027, 2, 6), datetime.date(2027, 4, 16)),
    2028: (datetime.date(2028, 1, 25), datetime.date(2028, 1, 26), datetime.date(2028, 4, 4)),
}


@tagged('post_install', '-at_install', 'at_lunar')
class TestLunarHolidays(common.TransactionCase):

    def _generate(self, year):
        self.env['hr.holidays.public'].search([('year', '=', year)]).unlink()
        self.env['hr.attendance.admin.control.wizard'].create({'at_date': datetime.date(year, 6, 15)}).action_create_public_holidays()
        return self.env['hr.holidays.public'].search([('year', '=', year)]).line_ids

    def test_lunar_holidays_dates(self):
        if lunarcalendar is None:
            self.skipTest('lunarcalendar is not installed')
        for year, (eve, tet, hung) in EXPECTED.items():
            with self.subTest(year=year):
                lines = self._generate(year)
                by_name = {}
                for line in lines:
                    by_name.setdefault(line.name, []).append(line.date)
                self.assertEqual(by_name["Lunar New Year's Eva"], [eve])
                self.assertEqual(sorted(by_name['Lunar New Year']), [tet, tet + datetime.timedelta(days=1), tet + datetime.timedelta(days=2)])
                self.assertIn(hung, by_name["Hung King's commemoration day"])

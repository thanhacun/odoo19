import datetime
import time as _time
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrHolidaysPublic(models.Model):
    """Public holidays of a year (and country). Odoo 19 has no hr_holidays_public: the OCA model is defined here (same names),
    with the KDERP changes of kderp_hr_attendance: company day, substitute day, working-time calendar, per-transaction memo."""
    _name = 'hr.holidays.public'
    _description = 'Public Holidays'
    _rec_name = 'year'
    _order = 'year'

    year = fields.Integer('Calendar Year', required=True, default=lambda self: date.today().year)
    line_ids = fields.One2many('hr.holidays.public.line', 'year_id', 'Holiday Dates')
    country_id = fields.Many2one('res.country', 'Country')

    @api.constrains('year', 'country_id')
    def _check_year(self):
        for record in self:
            if self.search_count([('year', '=', record.year), ('country_id', '=', record.country_id.id), ('id', '!=', record.id)]):
                raise ValidationError(_("You can't create duplicate public holiday per year and/or country"))

    @api.depends('year', 'country_id')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s (%s)' % (record.year, record.country_id.name) if record.country_id else str(record.year)

    @api.model_create_multi
    def create(self, vals_list):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().create(vals_list)

    def write(self, vals):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().write(vals)

    def unlink(self):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().unlink()

    # @api.model
    # @api.returns('hr.holidays.public.line')
    def get_holidays_list(self, year, employee_id=None):
        """
        Override this method to get the list based on employee_id working on SAT or not
        Also note that the list may depend on the date that apply the no_sat_working rule

        Returns recordset of hr.holidays.public.line

        Memoised per cursor (60 s): one status recompute asks the same (year, employee) thousands of times, 4 queries each.
        The memo is dropped when a holiday, a holiday line or an attendance rule is written (clear_at_rules_memo).
        """
        # Try to get employee_id from context
        if not employee_id:
            active_model, active_id = self.env.context.get('active_model', False), self.env.context.get('active_id', False)
            if active_model and active_id:
                active_record = self.env[active_model].browse(active_id)
                if 'employee_id' in active_record:
                    employee_id = active_record.employee_id.id
        default_rc = self.env.company.resource_calendar_id
        addr = self.env['hr.employee'].browse(employee_id).address_id if employee_id else False
        key = (year, employee_id or 0, default_rc.id,
               addr.country_id.id if addr else 0, addr.state_id.id if addr else 0)
        memo = self.env.cr.cache.setdefault('kderp_holidays_list_memo', {})
        hit = memo.get(key)
        now = _time.monotonic()
        if hit is None or now - hit[0] > 60:
            hit = (now, self._get_holidays_list_compute(year, employee_id, default_rc).ids)
            memo[key] = hit
        return self.env['hr.holidays.public.line'].browse(hit[1])

    def _get_holidays_list_compute(self, year, employee_id, default_rc):
        holidays_filter = [('year', '=', year)]
        employee = False
        rc_ids = [default_rc.id]

        if employee_id:
            employee = self.env['hr.employee'].browse(employee_id)
            rc_rules_domain = [('state', '=', 'done'), ('resource_calendar_id', '!=', False), ('apply_mode', '=', 'by_employee'), ('employee_ids', '=', employee_id), 
                               ('valid_start', '>=', datetime.date(year, 1, 1)), ('valid_start', '<=', datetime.date(year, 12, 31))]
            rc_rules = self.env['hr.attendance.rule'].search(rc_rules_domain)
            rc_ids += rc_rules.mapped('resource_calendar_id.id')
            if employee.address_id and employee.address_id.country_id:
                holidays_filter.append('|')
                holidays_filter.append(('country_id', '=', False))
                holidays_filter.append(('country_id',
                                        '=',
                                        employee.address_id.country_id.id))
            else:
                holidays_filter.append(('country_id', '=', False))
        pholidays = self.search(holidays_filter)
        
        if not pholidays:
            return self.env['hr.holidays.public.line']

        states_filter = [('year_id', 'in', pholidays.ids)]
        if employee and employee.address_id and employee.address_id.state_id:
            states_filter += ['|',
                              ('state_ids', '=', False),
                              ('state_ids', '=',
                               employee.address_id.state_id.id)]
        else:
            states_filter.append(('state_ids', '=', False))
        hhplo = self.env['hr.holidays.public.line']
        holidays_lines = hhplo.search(states_filter).filtered(lambda h: h.resource_calendar_id.id in rc_ids)
        return holidays_lines
    
    def is_public_holiday(self, selected_date, employee_id=None):
        """
        Override
        Returns 0 if not public holiday
        Returns 1 if is public holiday
        Returns 2 if is public holiday marked as company day (like 29/07)
        Returns 3 if is subtitute for holiday
        ! NOTE: hopefully this is backward compartible with the original method
        method that only return True/False

        Args:
            selected_date ([datetime]): datetime object
            employee_id ([ID], optional): ID of the employee. Defaults to None.
        """
        holidays_lines = self.get_holidays_list(selected_date.year, employee_id=employee_id)
        if holidays_lines:
            hol_date = holidays_lines.filtered(lambda r: r.date == selected_date)
            if hol_date.ids:
                if hol_date.is_substitute:
                    return 3
                elif hol_date.is_company_day:
                    return 2
                else:
                    return 1
            else:
                return 0
        return 0   # kdvn deviation D1: Odoo 12 returned None when the year has no holiday lines (then `== 0` checks said "holiday")

    @api.model
    def get_year_holiday(self):
        today = fields.Date.context_today(self)
        year = today.year

        domain = [('year', '=', year)]
        holidays = self.env['hr.holidays.public'].sudo().search(domain)
        return holidays.line_ids.mapped(lambda h: {
            'date': h.date.strftime('%d-%h-%Y') if h.date else '', 
            'name': h.name, 
            'is_company_day': h.is_company_day, 
            'is_substitute': h.is_substitute,
            'note': ' (Company holiday)' if h.is_company_day else ' (Subsitute holiday)' if h.is_substitute else '',
            'is_past': h.date < today,
            'days_from_today': (h.date - today).days
            })



class HrHolidaysPublicLine(models.Model):
    _name = 'hr.holidays.public.line'
    _description = 'Public Holidays Lines'
    _order = 'date, name desc'

    name = fields.Char('Name', required=True)
    date = fields.Date('Date', required=True)
    year_id = fields.Many2one('hr.holidays.public', 'Calendar Year', required=True, ondelete='cascade')
    variable_date = fields.Boolean('Date may change', default=True)
    state_ids = fields.Many2many('res.country.state', 'hr_holiday_public_state_rel', 'line_id', 'state_id', 'Related States')
    is_company_day = fields.Boolean(default=False, string='Company day')
    is_substitute = fields.Boolean(default=False, string='Substitute day')
    # For different working hours scheme (no_sat_working for example)
    resource_calendar_id = fields.Many2one('resource.calendar', default=lambda self: self.env.company.resource_calendar_id)

    @api.constrains('date', 'state_ids')
    def _check_date_state(self):
        for line in self:
            if line.date.year != line.year_id.year:
                raise ValidationError(_('Dates of holidays should be the same year as the calendar year they are being assigned to'))
            if line.state_ids:
                for holiday in self.search([('date', '=', line.date), ('year_id', '=', line.year_id.id), ('state_ids', '!=', False), ('id', '!=', line.id)]):
                    if line.state_ids & holiday.state_ids:
                        raise ValidationError(_("You can't create duplicate public holiday per date %s and one of the country states.") % line.date)
            if self.search_count([('date', '=', line.date), ('year_id', '=', line.year_id.id), ('state_ids', '=', False)]) > 1:
                raise ValidationError(_("You can't create duplicate public holiday per date %s.") % line.date)

    @api.model_create_multi
    def create(self, vals_list):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().create(vals_list)

    def write(self, vals):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().write(vals)

    def unlink(self):
        self.env.cr.cache.pop('kderp_holidays_list_memo', None)
        return super().unlink()

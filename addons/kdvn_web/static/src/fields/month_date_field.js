/** @odoo-module **/
// Port of the Odoo 12 widget "month_date": pick a MONTH only; the day is filled in automatically.
//   options month_period: 'begin' = first month end of an attendance month (the stored date lies in the month BEFORE: 21/12/2025 = January 2026),
//                         'end'   = day 20 of the picked month, no period = day 21 of the picked month.
//   option month_day: another day than 21 (20 for 'end').
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { formatDate } from "@web/core/l10n/dates";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const { DateTime } = luxon;

export class MonthDateField extends Component {
    static template = "kdvn_web.MonthDateField";
    static props = {
        ...standardFieldProps,
        period: { type: String, optional: true },
        day: { type: Number, optional: true },
    };

    get value() {
        return this.props.record.data[this.props.name] || false;
    }

    /** The month the user sees and picks (an attendance month for 'begin'). */
    get monthValue() {
        const value = this.value;
        if (!value) {
            return "";
        }
        const month = this.props.period === "begin" ? value.plus({ months: 1 }) : value;
        return month.toFormat("yyyy-MM");
    }

    get formattedDate() {
        return this.value ? formatDate(this.value) : "";
    }

    onChange(ev) {
        const text = ev.target.value;   // "yyyy-MM" or ""
        if (!text) {
            this.props.record.update({ [this.props.name]: false });
            return;
        }
        let base = DateTime.fromFormat(text, "yyyy-MM");
        if (!base.isValid) {
            return;
        }
        if (this.props.period === "begin") {
            base = base.minus({ months: 1 });   // January 2026 -> December 2025
        }
        const defaultDay = this.props.period === "end" ? 20 : 21;
        const day = Math.min(this.props.day || defaultDay, base.daysInMonth);
        this.props.record.update({ [this.props.name]: base.set({ day }) });
    }
}

registry.category("fields").add("month_date", {
    component: MonthDateField,
    displayName: "Month picker (date)",
    supportedTypes: ["date"],
    extractProps: ({ options }) => ({
        period: options.month_period,
        day: options.month_day,
    }),
});

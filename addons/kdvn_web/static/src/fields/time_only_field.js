/** @odoo-module **/
// Odoo 12 showed the IN/OUT of the attendance lists as time only (06:49, option format HH:mm); Odoo 19 has no such option.
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class TimeOnlyField extends Component {
    static template = "kdvn_web.TimeOnlyField";
    static props = { ...standardFieldProps };

    get formattedValue() {
        const value = this.props.record.data[this.props.name];
        return value ? value.toFormat("HH:mm") : "";   // luxon DateTime in the user's time zone
    }
}

registry.category("fields").add("kdvn_time_only", {
    component: TimeOnlyField,
    displayName: "Time only (HH:mm)",
    supportedTypes: ["datetime"],
});

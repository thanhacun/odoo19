/** @odoo-module **/
// Odoo 12 showed dates as 21/04/2024 (the language format); Odoo 19 shows "Apr 21, 2024" or "Mar 21" unless the field has
// options="{'numeric': True}". Make numeric the default for every date / datetime field, like Odoo 12.
// (Editable widgets: a field can still ask for the short style with numeric False; read-only text always follows the language format.)
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";

// editable date widgets
patch(DateTimeField, {
    defaultProps: { ...DateTimeField.defaultProps, numeric: true },
});

// read-only text (list cells, groups): rendered by the formatters, not by the component
const formatters = registry.category("formatters");
for (const type of ["date", "datetime"]) {
    if (formatters.contains(type)) {
        const formatter = formatters.get(type);
        formatters.add(type, (value, options = {}) => formatter(value, { ...options, numeric: true }), { force: true });
    }
}

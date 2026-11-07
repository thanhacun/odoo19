/** @odoo-module **/
// Port of Odoo 12 graph_view.js: an action can limit the measures of its graph view, name and order them, with the context key
//   graph_measures = {'field_name': {'description': '01.1 abc'}, ...}
// Only the fields listed are offered in the Measures dropdown (plus Count), sorted by description.
import { patch } from "@web/core/utils/patch";
import { GraphModel } from "@web/views/graph/graph_model";

patch(GraphModel.prototype, {
    _buildMetaData(params) {
        const metaData = super._buildMetaData(params);
        const custom = metaData.context && metaData.context.graph_measures;
        if (custom) {
            const measures = { __count: metaData.measures.__count };
            const names = Object.keys(custom).sort((a, b) => String(custom[a].description).localeCompare(String(custom[b].description)));
            for (const name of names) {
                const field = metaData.measures[name] || metaData.fields[name];
                if (field && ["integer", "float", "monetary"].includes(field.type)) {
                    measures[name] = { ...field, name, string: custom[name].description };
                }
            }
            metaData.measures = measures;
        }
        return metaData;
    },
});

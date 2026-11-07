/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/** User menu > User Guides: the guide root. Opened as a client action (not a URL), so the web client keeps debug mode. */
function guidesItem(env) {
    return {
        type: "item",
        id: "kdvn_guides",
        description: _t("User Guides"),
        callback: async () => {
            const action = await env.services.orm.call("document.page", "kderp_action_open_guide", ["user-guides"]);
            env.services.action.doAction(action);
        },
        sequence: 5,
    };
}

registry.category("user_menuitems").add("kdvn_guides", guidesItem);

/** @odoo-module **/
// Open Positions list (/jobs): choosing a location reloads the list with it.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnJobsFilter extends Interaction {
    static selector = ".kdvn-jobs-filter";
    dynamicContent = {
        "[data-kdvn-jobs-location]": { "t-on-change": () => this.el.requestSubmit() },
    };
}

registry.category("public.interactions").add("kdvn_website.jobs_filter", KdvnJobsFilter);

/** @odoo-module **/
// Port of Odoo 12 org_chart_tabs.js: Employee form > Organization Chart. The core widget only shows the Functional line (parent_id).
// Our staff have two lines (Functional and Administrative): both are shown as tabs. The Administrative data (`admin`) comes from
// controllers/hr_org_chart.py, in the same shape as the Functional one, and is drawn with the core chart template.
import { useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { HrOrgChart } from "@hr_org_chart/fields/hr_org_chart";

export class KdvnHrOrgChart extends HrOrgChart {
    static template = "kdvn_hr_attendance.HrOrgChartTabs";

    setup() {
        super.setup();
        this.tabs = useState({ active: "func" });
        this.admin = null;
    }

    // same as the core method, plus the Administrative line
    async fetchEmployeeData(employeeId, newParentId = null, force = false) {
        if (!employeeId) {
            this.admin = null;
            return super.fetchEmployeeData(employeeId, newParentId, force);
        }
        if (employeeId !== this.view_employee_id || force) {
            this.view_employee_id = employeeId;
            let orgData = await rpc("/hr/get_org_chart", {
                employee_id: employeeId,
                new_parent_id: newParentId,
                context: { ...user.context, max_level: this.max_level },
            });
            if (Object.keys(orgData).length === 0) {
                orgData = { managers: [], children: [] };
            }
            this.managers = orgData.managers;
            this.children = orgData.children;
            this.managers_more = orgData.managers_more;
            this.self = orgData.self;
            this.admin = orgData.admin || null;
            this.render(true);
        }
    }

    get funcCount() {
        return (this.managers || []).length + (this.children || []).length;
    }

    get adminCount() {
        return this.admin ? this.admin.managers.length + this.admin.children.length : 0;
    }

    get activeData() {
        if (this.tabs.active === "admin" && this.admin) {
            return this.admin;
        }
        return { managers: this.managers, managers_more: this.managers_more, children: this.children, self: this.self };
    }

    // the sub-count popover lists the Functional reports: not shown on the Administrative tab (Odoo 12 did the same)
    _onOpenPopover(event, employee) {
        if (this.tabs.active === "admin") {
            return;
        }
        return super._onOpenPopover(event, employee);
    }
}

registry.category("fields").add("hr_org_chart", { component: KdvnHrOrgChart }, { force: true });

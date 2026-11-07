/** @odoo-module **/
// Port of Odoo 12 fields.js (widget `ot_holiday`): the "Schedule OT on holidays" table of the OT holidays manager form.
// The table comes from hr.attendance.ot.holiday.manager.generate_ot_holiday_values; every button calls one action_click_* method and reloads.
// Refreshes by itself when another user changes a line (bus message `ot_holiday_line_changed`) or when the server asks this user to
// refresh / download the Excel file (bus message `kdvn_ui_event`, see models/res_users.py).
import { Component, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { downloadFile } from "@web/core/network/download";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const MODEL = "hr.attendance.ot.holiday.manager";
const BUS_CHANNEL = "ot_holiday_manager_ui_refesh";

export class OTHolidayRefuseDialog extends Component {
    static template = "kdvn_hr_attendance.OTHolidayRefuseDialog";
    static components = { Dialog };
    static props = { close: Function, staffName: String, otDetail: String, atDate: String, onConfirm: Function };

    setup() {
        this.state = useState({ comment: "" });
    }

    async confirm() {
        if (!this.state.comment.trim()) {
            return;   // the reason is required, like in Odoo 12
        }
        await this.props.onConfirm(this.state.comment.trim());
        this.props.close();
    }
}

export class OTHolidayField extends Component {
    static template = "kdvn_hr_attendance.OTHolidayField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        this.state = useState({ data: null });
        this.onLineChanged = () => this.load();
        this.onUiEvent = (payload) => {
            if (payload.event === "ot_holiday_refresh") {
                this.load();
            } else if (payload.event === "ot_holiday_download_excel_file") {
                this.downloadExcel();
            }
        };
        onWillStart(() => this.load());
        onWillUpdateProps((nextProps) => {
            if (this.idsOf(nextProps).join() !== this.ids.join()) {
                return this.load(this.idsOf(nextProps));
            }
        });
        onMounted(() => {
            this.busService.addChannel(BUS_CHANNEL);
            this.busService.subscribe("ot_holiday_line_changed", this.onLineChanged);
            this.busService.subscribe("kdvn_ui_event", this.onUiEvent);
        });
        onWillUnmount(() => {
            this.busService.unsubscribe("ot_holiday_line_changed", this.onLineChanged);
            this.busService.unsubscribe("kdvn_ui_event", this.onUiEvent);
        });
    }

    idsOf(props) {
        const list = props.record.data[props.name];
        return ((list && list.currentIds) || []).filter((id) => Number.isInteger(id));
    }

    get ids() {
        return this.idsOf(this.props);
    }

    async load(ids = this.ids) {
        this.state.data = await this.orm.call(MODEL, "generate_ot_holiday_values", [[], ids]);
    }

    // ---- data helpers for the template
    get data() {
        return this.state.data;
    }

    get hasData() {
        return !!(this.data && this.data.ot_holiday && this.data.headers);
    }

    get headers() {
        return this.data.headers;
    }

    get dates() {
        return this.data.headers[5].at_dates;
    }

    get month() {
        return this.data.headers[5].month;
    }

    get sections() {
        return Object.keys(this.data.ot_holiday);
    }

    get userRole() {
        const user = this.data.user || {};
        return user.is_section_manager ? "SM" : user.is_gm ? "GM" : "";
    }

    dayClass(dateText) {
        const day = dateText.slice(-3);
        return day === "Sun" ? "text-danger" : day === "Sat" ? "text-success" : "text-warning";
    }

    sectionYearMonth(section) {
        const first = this.data.ot_holiday[section].section_ot[0];
        return { atYear: first.at_year, atMonth: first.at_month };
    }

    // ---- actions: call the server, then reload
    async call(method, args) {
        const result = await this.orm.call(MODEL, method, [[], ...args]);
        await this.load();
        return result;
    }

    approve(staffCode, atDate) {
        return this.call("action_click_ok_button", [staffCode, atDate]);
    }

    refuse(o, d) {
        this.dialog.add(OTHolidayRefuseDialog, {
            staffName: o.name,
            otDetail: d.ot_detail || "",
            atDate: d.at_date,
            onConfirm: (comment) => this.call("action_click_ok_refuse_form", [o.staff_no, d.at_date, comment]),
        });
    }

    remove(staffCode, atDate) {
        return this.call("action_click_delete", [staffCode, atDate]);
    }

    revise(staffCode, atDate) {
        return this.call("action_click_revise", [staffCode, atDate]);
    }

    approveEmployee(o) {
        return this.call("action_click_approve_employee", [o.staff_no, o.at_year, o.at_month]);
    }

    approveSection(section) {
        const { atYear, atMonth } = this.sectionYearMonth(section);
        return this.call("action_click_approve_section", [section, atYear, atMonth]);
    }

    // Odoo 12 kept the schedule dialog open under these two (flag doNotClosePrevDialog); a doAction with target "new" would close it in
    // Odoo 19, so the records open in a form dialog stacked on top.
    async openAttendance(staffCode, atDate) {
        const result = await this.orm.call(MODEL, "action_click_info", [[], atDate, staffCode]);
        if (result) {
            this.dialog.add(FormViewDialog, { resModel: "hr.attendance", resId: result.recordId, title: result.title, mode: "readonly", size: "xl" });
        }
    }

    async openSummary(o) {
        const result = await this.orm.call(MODEL, "action_click_at_info", [[], o.staff_no, o.at_year, o.at_month]);
        if (result) {
            this.dialog.add(FormViewDialog, { resModel: "hr.attendance.summary", resId: result.id, title: result.title, mode: "readonly", size: "xl" });
        }
    }

    async downloadExcel() {
        const result = await this.orm.call(MODEL, "generate_complex_report_xlsx", [[], this.month, this.ids]);
        const bytes = Uint8Array.from(atob(result.file), (c) => c.charCodeAt(0));
        downloadFile(new Blob([bytes], { type: result.mimetype }), result.filename, result.mimetype);
        this.notification.add("Excel report has been generated and downloaded.", { type: "success" });
    }
}

registry.category("fields").add("ot_holiday", {
    component: OTHolidayField,
    displayName: "OT holidays schedule",
    supportedTypes: ["one2many", "many2many"],
});

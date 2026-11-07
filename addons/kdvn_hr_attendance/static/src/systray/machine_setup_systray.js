/** @odoo-module **/
// Port of Odoo 12 machine_setup_systray.js: a warning in the top bar (any screen) for HR Admin when face-id machines have no location name / area.
// The server answers 0 for everybody else, so the item stays hidden for them.
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class MachineSetupSystray extends Component {
    static template = "kdvn_hr_attendance.MachineSetupSystray";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ count: 0 });
        onWillStart(async () => {
            try {
                // silent: a failure (no access, server busy) must not open an error dialog
                this.state.count = (await this.orm.silent.call("hr.attendance.location", "get_setup_warning", [])) || 0;
            } catch {
                this.state.count = 0;
            }
        });
    }

    onClick() {
        this.action.doAction("kdvn_hr_attendance.hr_attendance_location_to_complete_action");
    }
}

registry.category("systray").add("kdvn_hr_attendance.machine_setup", { Component: MachineSetupSystray }, { sequence: 5 });

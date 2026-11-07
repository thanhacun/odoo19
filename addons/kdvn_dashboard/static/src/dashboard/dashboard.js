/** @odoo-module **/
/**
 * KDVN Dashboard (client action tag 'kderp_dashboard', kept from Odoo 12 so saved home actions keep working).
 * Data: kderp.dashboard.get_dashboard_data (models/dashboard.py). Port of the Odoo 12 AbstractAction widget to Owl.
 *
 * Quick actions call what the other apps already offer to their own buttons:
 *  - attendance requests / leave: kderp.dashboard.approve_attendance and the record's own action_refuse dialog;
 *  - e-approval: validate_tier / reject_tier of the request (comment dialog when needed);
 *  - "Today" buttons: the attendance day's own action_ot_request / action_wt_request / action_leave_request,
 *    or the My Requests menu actions.
 */
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const OVERDUE_DAYS = 7;     // red badge + "needs attention" strip from this many days waiting
const SWIPE_MIN = 90;       // px to swipe a row on a phone to approve (right) / reject (left)
const PAGE_SIZE = 50;
const TABS = [
    { key: "eapproval", label: _t("E-approval") },
    { key: "wt", label: _t("Working time") },
    { key: "ot", label: _t("Overtime") },
    { key: "leave", label: _t("Leave") },
];

class SkippedDialog extends Dialog {
    static template = "kdvn_dashboard.SkippedDialog";
    static props = { ...Dialog.props, skipped: Array };
}

export class KdvnDashboard extends Component {
    static template = "kdvn_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.root = useRef("root");
        this.state = useState({
            ready: false,
            data: { inbox: [], mine: [], counts: {}, window: { months: [] }, inbox_lists: [] },
            tab: null,
            search: "",
            page: 0,
            selected: {},     // "model:id" -> true
            collapsed: {},    // group key -> true (section / employee header folded)
            onlyOld: false,   // show only requests waiting OVERDUE_DAYS+
        });
        onWillStart(() => this._fetch());
        onMounted(() => this._bindSwipe());
    }

    // ------------------------------------------------------------------ data
    get tabs() {
        const withApproval = this.state.data.has_eapproval !== false;
        return TABS.filter((t) => withApproval || t.key !== "eapproval");
    }

    _ctx(extra) {
        return Object.assign({}, user.context, extra || {});
    }

    async _fetch() {
        const data = await this.orm.call("kderp.dashboard", "get_dashboard_data", [], { context: this._ctx() });
        this.state.data = data;
        this.state.ready = true;
        if (!this.state.tab || !data.counts[this.state.tab]) {
            const first = this.tabs.find((t) => data.counts[t.key]);
            this.state.tab = first ? first.key : this.state.tab || this.tabs[0].key;
        }
        // keep only selections that are still waiting
        const still = new Set((data.inbox || []).map((r) => this._key(r)));
        for (const k of Object.keys(this.state.selected)) {
            if (!still.has(k)) {
                delete this.state.selected[k];
            }
        }
    }

    _key(row) {
        return `${row.model}:${row.res_id}`;
    }

    /** Rows of the current tab, filtered by the search box, sorted section > employee > date, cut into pages and grouped.
     *  Section headers only when rows span 2+ sections; an employee header only when that employee has 2+ rows on the page. */
    getView() {
        const st = this.state;
        const q = st.search.trim().toLowerCase();
        const max = st.data.bulk_max || 50;
        const inbox = st.data.inbox || [];
        const old = inbox.filter((r) => r.days >= OVERDUE_DAYS);
        const onlyOld = st.onlyOld && old.length > 0;      // nothing left to show: back to the full list
        const base = onlyOld ? old : inbox;
        let rows = base.filter((r) => r.tab === st.tab);
        if (q) {
            rows = rows.filter((r) =>
                [r.applicant, r.ref, r.subject, r.section, r.step].join(" ").toLowerCase().includes(q));
        }
        rows = rows.slice().sort((a, b) => {
            const ka = [a.section || "~", a.applicant || "", a.sort_key || ""].join("|");
            const kb = [b.section || "~", b.applicant || "", b.sort_key || ""].join("|");
            return ka < kb ? -1 : ka > kb ? 1 : 0;
        });
        const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
        const page = Math.min(st.page, pages - 1);
        const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
        const sections = new Set(rows.map((r) => r.section));
        const showSections = sections.size > 1;
        const isAttendance = st.tab !== "eapproval";
        const groups = [];
        for (const r of pageRows) {
            let g = groups[groups.length - 1];
            if (!g || g.section !== r.section) {
                g = { section: r.section, label: r.section || _t("No section"), keys: [], employees: [], gkey: "s:" + (r.section || "") };
                groups.push(g);
            }
            let e = g.employees[g.employees.length - 1];
            if (!e || e.employee_id !== r.employee_id || e.name !== r.applicant) {
                e = { employee_id: r.employee_id, name: r.applicant, rows: [], keys: [],
                      gkey: "e:" + (r.section || "") + "|" + r.employee_id + "|" + r.applicant };
                g.employees.push(e);
            }
            const key = this._key(r);
            e.rows.push({ ...r, key, checkbox: isAttendance && r.can_approve, checked: !!st.selected[key] });
            if (r.can_approve) {
                e.keys.push(key);
                g.keys.push(key);
            }
        }
        const allSelected = (keys) => keys.length > 0 && keys.every((k) => st.selected[k]);
        const headerKeys = [];
        for (const g of groups) {
            g.collapsed = showSections && !!st.collapsed[g.gkey];
            g.caret = g.collapsed ? "fa-caret-right" : "fa-caret-down";
            if (showSections) {
                headerKeys.push(g.gkey);
            }
            g.checkbox = isAttendance && g.keys.length > 0;
            g.checked = allSelected(g.keys);
            for (const e of g.employees) {
                e.multi = e.rows.length > 1;
                e.collapsed = e.multi && !!st.collapsed[e.gkey];
                e.caret = e.collapsed ? "fa-caret-right" : "fa-caret-down";
                e.approve_group = isAttendance && e.keys.length > 1;
                e.approve_count = Math.min(e.keys.length, max);
                if (e.multi) {
                    headerKeys.push(e.gkey);
                }
                e.checkbox = isAttendance && e.keys.length > 0;
                e.checked = allSelected(e.keys);
                for (const r of e.rows) {
                    r.show_name = !e.multi;
                }
            }
        }
        // "Select all": the first `max` approvable rows of the whole filtered tab (all pages)
        const allKeys = isAttendance ? rows.filter((r) => r.can_approve).map((r) => this._key(r)) : [];
        const selAllKeys = allKeys.slice(0, max);
        const selectedCount = Object.keys(st.selected).length;
        return {
            selAllKeys,
            selAllTotal: allKeys.length,
            selAllCount: selAllKeys.length,
            selAllCapped: allKeys.length > max,
            selAllChecked: allSelected(selAllKeys),
            headerKeys,
            hasHeaders: headerKeys.length > 0,
            allCollapsed: headerKeys.length > 0 && headerKeys.every((k) => st.collapsed[k]),
            tabs: this.tabs.map((t) => ({
                key: t.key, label: t.label, active: t.key === st.tab,
                count: base.filter((r) => r.tab === t.key).length,
            })),
            attention: old.length ? { count: old.length, oldest: Math.max(...old.map((r) => r.days)), active: onlyOld } : null,
            groups,
            showSections,
            total: rows.length,
            page,
            pages,
            from: rows.length ? page * PAGE_SIZE + 1 : 0,
            to: page * PAGE_SIZE + pageRows.length,
            bulk: isAttendance,
            selectedCount,
        };
    }

    get overdueDays() {
        return OVERDUE_DAYS;
    }

    _rowOf(model, id) {
        return this.state.data.inbox.find((r) => r.model === model && r.res_id === id) || { model, res_id: id };
    }

    _actionOptions() {
        return { onClose: () => this._reload() };
    }

    async _reload() {
        await this._fetch();
    }

    // -------------------------------------------------------------- handlers
    openRecord(model, resId) {
        this.actionService.doAction({
            type: "ir.actions.act_window", res_model: model, res_id: resId, views: [[false, "form"]], target: "current",
        });
    }

    showAll(index, older) {
        const list = this.state.data.inbox_lists[index];
        if (!list) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: older ? list.name + _t(" (older months)") : list.name,
            res_model: list.model,
            domain: older ? list.older_domain : list.domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    async refresh(ev) {
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
            await this._reload();
        } finally {
            btn.disabled = false;
        }
    }

    setTab(key) {
        this.state.tab = key;
        this.state.page = 0;
        this.state.selected = {};
    }

    onSearch(ev) {
        this.state.search = ev.target.value || "";
        this.state.page = 0;
    }

    step(delta) {
        this.state.page = Math.max(0, this.state.page + delta);
    }

    toggleKeys(keys, checked) {
        for (const k of keys) {
            if (checked) {
                this.state.selected[k] = true;
            } else {
                delete this.state.selected[k];
            }
        }
    }

    toggleAttention() {
        const st = this.state;
        st.onlyOld = !st.onlyOld;
        st.page = 0;
        if (st.onlyOld) {
            const has = (tab) => st.data.inbox.some((r) => r.tab === tab && r.days >= OVERDUE_DAYS);
            if (!has(st.tab)) {
                const first = this.tabs.find((t) => has(t.key));
                if (first) {
                    st.tab = first.key;
                }
            }
        }
    }

    toggleGroup(gkey) {
        if (this.state.collapsed[gkey]) {
            delete this.state.collapsed[gkey];
        } else {
            this.state.collapsed[gkey] = true;
        }
    }

    collapseAll(keys, expand) {
        for (const k of keys) {
            if (expand) {
                delete this.state.collapsed[k];
            } else {
                this.state.collapsed[k] = true;
            }
        }
    }

    /** One employee's rows (e.g. a month of overtime) approved in one click, with a confirmation. */
    approveGroup(keys, name) {
        const rows = this.state.data.inbox.filter((r) => keys.slice(0, this.state.data.bulk_max || 50).includes(this._key(r)));
        if (!rows.length) {
            return;
        }
        this._confirm(_t("Approve %(n)s request(s) of %(name)s?", { n: rows.length, name }), () => this._approveAttendance(rows));
    }

    bulkApprove() {
        const rows = this.state.data.inbox.filter((r) => this.state.selected[this._key(r)] && r.tab !== "eapproval");
        if (!rows.length) {
            return;
        }
        const max = this.state.data.bulk_max || 50;
        if (rows.length > max) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Too many requests"),
                body: _t("Please select at most %s requests at a time.", max),
                confirm: () => {},
            });
            return;
        }
        this._confirm(_t("Approve %s selected request(s)?", rows.length), () => this._approveAttendance(rows));
    }

    _confirm(body, onConfirm) {
        this.dialog.add(ConfirmationDialog, { title: _t("Confirmation"), body, confirm: onConfirm, cancel: () => {} });
    }

    async approve(row) {
        if (row.tab === "eapproval") {
            // The request's own Approve: opens the comment dialog when the step needs one
            const action = await this.orm.call(row.model, "validate_tier", [[row.res_id]], { context: this._ctx() });
            if (action && action.type) {
                return this.actionService.doAction(action, this._actionOptions());
            }
            this.notification.add(row.ref, { title: _t("Approved"), type: "success" });
            return this._reload();
        }
        return this._approveAttendance([row]);
    }

    async refuse(row) {
        const method = row.tab === "eapproval" ? "reject_tier" : "action_refuse";
        // The record's own Reject / Refuse: both open their reason dialog
        const action = await this.orm.call(row.model, method, [[row.res_id]], { context: this._ctx() });
        if (action && action.type) {
            return this.actionService.doAction(action, this._actionOptions());
        }
        return this._reload();
    }

    async _approveAttendance(rows) {
        const items = rows.map((r) => ({ model: r.model, id: r.res_id }));
        const res = await this.orm.call("kderp.dashboard", "approve_attendance", [items], { context: this._ctx() });
        for (const r of rows) {
            delete this.state.selected[this._key(r)];
        }
        if (res.skipped && res.skipped.length) {
            this.dialog.add(SkippedDialog, {
                title: _t("%(done)s approved, %(skipped)s not approved", { done: res.done, skipped: res.skipped.length }),
                skipped: res.skipped,
            });
        } else {
            this.notification.add(_t("%s request(s) approved.", res.done), { title: _t("Approved"), type: "success" });
        }
        return this._reload();
    }

    /** Today card: the attendance day's own request buttons. */
    async attendanceButton(method, id, atDate) {
        const action = await this.orm.call("hr.attendance", method, [[id]], { context: this._ctx({ at_date: atDate }) });
        if (action && action.type) {
            return this.actionService.doAction(action, this._actionOptions());
        }
    }

    /** Today card: My Requests menu actions (OT / WT / Leave). */
    menuAction(id) {
        if (id) {
            this.actionService.doAction(id, this._actionOptions());
        }
    }

    // ----------------------------------------------------------------- swipe
    /** Phone: swipe a row right to approve, left to reject. Approve asks to confirm (one gesture must not approve by
     *  accident); reject opens the reason dialog like the button. */
    _bindSwipe() {
        const el = this.root.el;
        const phone = () => window.matchMedia && window.matchMedia("(max-width: 767.98px)").matches;
        let st = null;
        el.addEventListener("touchstart", (e) => {
            const tr = e.target.closest ? e.target.closest(".o_kd_row") : null;
            if (!tr || e.touches.length !== 1 || !phone() || e.target.closest("input, button, a")) {
                st = null;
                return;
            }
            st = { tr, x: e.touches[0].clientX, y: e.touches[0].clientY, dx: 0, lock: null };
        }, { passive: true });
        el.addEventListener("touchmove", (e) => {
            if (!st) {
                return;
            }
            const dx = e.touches[0].clientX - st.x;
            const dy = e.touches[0].clientY - st.y;
            if (!st.lock && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
                st.lock = Math.abs(dx) > Math.abs(dy) * 1.5 ? "h" : "v";
            }
            if (st.lock === "v") {
                st = null;
                return;
            }
            if (st.lock === "h") {
                e.preventDefault();
                st.dx = Math.max(-140, Math.min(140, dx));
                st.tr.style.transform = `translateX(${st.dx}px)`;
                st.tr.classList.toggle("o_kd_swipe_ok", st.dx >= SWIPE_MIN);
                st.tr.classList.toggle("o_kd_swipe_no", st.dx <= -SWIPE_MIN);
                st.tr.classList.toggle("o_kd_swipe_pull", Math.abs(st.dx) > 12);
            }
        }, { passive: false });
        const end = () => {
            if (!st) {
                return;
            }
            const { tr, dx, lock } = st;
            st = null;
            if (lock !== "h") {
                return;
            }
            tr.style.transform = "";
            tr.classList.remove("o_kd_swipe_ok", "o_kd_swipe_no", "o_kd_swipe_pull");
            if (Math.abs(dx) < SWIPE_MIN) {
                return;
            }
            const row = this._rowOf(tr.dataset.model, parseInt(tr.dataset.id, 10));
            if (dx > 0 && row.can_approve) {
                this._confirm(_t("Approve %s?", row.ref + (row.applicant ? " · " + row.applicant : "")), () => this.approve(row));
            } else if (dx < 0 && row.can_refuse) {
                this.refuse(row);
            }
        };
        el.addEventListener("touchend", end, { passive: true });
        el.addEventListener("touchcancel", end, { passive: true });
    }
}

registry.category("actions").add("kderp_dashboard", KdvnDashboard);

/** @odoo-module **/
// Inquiry form (/contactus): after sending, the controller redirects to
// /contactus?sent=1 and this opens the "Got it!" popup. Closed with the X,
// the Close button, a click on the dark background or Escape. The ?sent=1 is
// removed from the address so a reload does not open the popup again.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnInquiryModal extends Interaction {
    static selector = "#kdvn_inquiry_sent";
    dynamicContent = {
        "[data-kdvn-close]": { "t-on-click": this.close },
        _document: { "t-on-keydown": this.onKeydown },
    };

    start() {
        const url = new URL(window.location.href);
        if (url.searchParams.get("sent") !== "1") {
            return;
        }
        url.searchParams.delete("sent");
        window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
        this.open();
    }

    open() {
        this.el.hidden = false;
        document.body.classList.add("kdvn-modal-open");
        this.el.querySelector(".kdvn-modal-close")?.focus();
    }

    close() {
        if (this.el.hidden) {
            return;
        }
        this.el.hidden = true;
        document.body.classList.remove("kdvn-modal-open");
    }

    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.close();
        }
    }

    destroy() {
        document.body.classList.remove("kdvn-modal-open");
    }
}

registry.category("public.interactions").add("kdvn_website.inquiry_modal", KdvnInquiryModal);

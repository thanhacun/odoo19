/** @odoo-module **/
// Header panels: Search and Language (frames/search-*, languages-*).
// A button with data-kdvn-open="<panel id>" opens the panel; the X, the back
// arrow (mobile), a click on the dark background or Escape close it. Focus
// goes to the search field / current language and back to the button.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnPanels extends Interaction {
    static selector = "#wrapwrap";
    dynamicContent = {
        "[data-kdvn-open]": { "t-on-click": this.open },
        ".kdvn-panel [data-kdvn-close]": { "t-on-click": this.close },
        _document: { "t-on-keydown": this.onKeydown },
    };

    open(ev) {
        const panel = document.getElementById(ev.currentTarget.dataset.kdvnOpen);
        if (!panel) {
            return;
        }
        ev.preventDefault();
        this.closeAll();
        this.opener = ev.currentTarget;
        panel.hidden = false;
        document.body.classList.add("kdvn-modal-open");
        const target =
            panel.querySelector(".kdvn-search-input") ||
            panel.querySelector(".is-active > .kdvn-lang") ||
            panel.querySelector(".kdvn-modal-x");
        target?.focus();
    }

    closeAll() {
        for (const panel of document.querySelectorAll(".kdvn-panel:not([hidden])")) {
            panel.hidden = true;
        }
    }

    close() {
        if (!document.querySelector(".kdvn-panel:not([hidden])")) {
            return;
        }
        this.closeAll();
        document.body.classList.remove("kdvn-modal-open");
        this.opener?.focus();
    }

    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.close();
        }
    }

    destroy() {
        this.closeAll();
        document.body.classList.remove("kdvn-modal-open");
    }
}

registry.category("public.interactions").add("kdvn_website.panels", KdvnPanels);

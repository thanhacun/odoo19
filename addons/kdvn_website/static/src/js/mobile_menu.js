/** @odoo-module **/
// Mobile menu (below 1200px): full-screen list. Tapping a section opens it (Bootstrap
// dropdown, styled as a second screen in theme.scss); the "back" row closes it again.
// Closing the menu also closes the open section, so it opens on the main list next time.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnMobileMenu extends Interaction {
    static selector = ".kdvn-header";
    dynamicContent = {
        ".kdvn-mobile-back": { "t-on-click": this.back },
    };

    start() {
        const menu = this.el.querySelector("#kdvnTopHeaderNav");
        if (menu) {
            this.addListener(menu, "hidden.bs.collapse", this.closeSection);
            this.addListener(menu, "show.bs.collapse", this.setBarHeight);
        }
    }

    // The open menu fills the screen under the bar: CSS needs the bar's height
    setBarHeight() {
        document.documentElement.style.setProperty("--kdvn-header-h", `${this.el.offsetHeight}px`);
    }

    back(ev) {
        this.openToggle(ev.currentTarget.closest(".kdvn-mega-dropdown"))?.click();
    }

    closeSection() {
        for (const item of this.el.querySelectorAll(".kdvn-mega-dropdown")) {
            this.openToggle(item)?.click();
        }
    }

    openToggle(item) {
        return item?.querySelector(":scope > .dropdown-toggle.show");
    }
}

registry.category("public.interactions").add("kdvn_website.mobile_menu", KdvnMobileMenu);

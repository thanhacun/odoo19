/** @odoo-module **/
// Appearance panel: Light / Dark / System. The choice is stored in localStorage
// ("kdvn_theme") and set on <html data-kdvn-theme>; css/theme_colors.scss does the rest.
// The inline script in views/layout_theme.xml applies it before first paint.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

const KEY = "kdvn_theme";

export class KdvnThemeSwitch extends Interaction {
    static selector = "#wrapwrap";
    dynamicContent = {
        "[data-kdvn-theme-choice]": { "t-on-click": this.choose },
    };

    start() {
        this.mark(this.stored());
    }

    stored() {
        try {
            const value = localStorage.getItem(KEY);
            return value === "dark" || value === "system" ? value : "light";
        } catch {
            return "light";
        }
    }

    choose(ev) {
        const value = ev.currentTarget.dataset.kdvnThemeChoice;
        try {
            localStorage.setItem(KEY, value);
        } catch {
            // private mode: the choice lasts until the page is left
        }
        if (value === "light") {
            document.documentElement.removeAttribute("data-kdvn-theme");
        } else {
            document.documentElement.setAttribute("data-kdvn-theme", value);
        }
        this.mark(value);
    }

    mark(value) {
        for (const item of this.el.querySelectorAll("[data-kdvn-theme-item]")) {
            const active = item.dataset.kdvnThemeItem === value;
            item.classList.toggle("is-active", active);
            item.querySelector("button")?.setAttribute("aria-pressed", active);
        }
    }
}

registry.category("public.interactions").add("kdvn_website.theme_switch", KdvnThemeSwitch);

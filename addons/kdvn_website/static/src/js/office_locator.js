/** @odoo-module **/
// Office Location & Map page: search filters the office cards,
// "Location" shows the chosen office on the map.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnOfficeLocator extends Interaction {
    static selector = ".kdvn-office-locator";
    dynamicContent = {
        ".kdvn-office-search": { "t-on-input": this.onSearch },
        ".kdvn-office-locate": { "t-on-click": this.onLocate },
    };

    setup() {
        this.mapEl = this.el.querySelector(".kdvn-office-map-frame");
    }

    onSearch(ev) {
        const term = ev.currentTarget.value.trim().toLowerCase();
        let visible = 0;
        for (const card of this.el.querySelectorAll(".kdvn-office-card")) {
            const match = !term || (card.dataset.search || "").includes(term);
            card.classList.toggle("d-none", !match);
            visible += match ? 1 : 0;
        }
        this.el.querySelector(".kdvn-office-empty")?.classList.toggle("d-none", visible > 0);
    }

    onLocate(ev) {
        const card = ev.currentTarget.closest(".kdvn-office-card");
        if (!card || !this.mapEl) {
            return;
        }
        for (const other of this.el.querySelectorAll(".kdvn-office-card.active")) {
            other.classList.remove("active");
        }
        card.classList.add("active");
        if (card.dataset.embedUrl && this.mapEl.src !== card.dataset.embedUrl) {
            this.mapEl.src = card.dataset.embedUrl;
            this.mapEl.title = `Map: ${card.dataset.name || ""}`;
        }
        // On small screens the map is below the list: bring it into view
        if (window.matchMedia("(max-width: 991.98px)").matches) {
            this.mapEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }
}

registry.category("public.interactions").add("kdvn_website.office_locator", KdvnOfficeLocator);

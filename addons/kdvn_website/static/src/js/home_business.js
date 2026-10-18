/** @odoo-module **/
// Homepage > Business Information: the hovered / focused / tapped item becomes
// active (black, arrow button) and its photo is shown (right on desktop,
// under the item on mobile). Tapping an inactive item opens it; tapping the
// active one follows its link.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnHomeBusiness extends Interaction {
    static selector = ".kdvn-biz";
    dynamicContent = {
        ".kdvn-biz-item": {
            "t-on-mouseenter": this.onEnter,
            "t-on-focusin": this.onEnter,
        },
        ".kdvn-biz-name": { "t-on-click": this.onNameClick },
    };

    setup() {
        this.figureImg = this.el.querySelector(".kdvn-biz-figure img");
    }

    activate(item) {
        if (!item || item.classList.contains("active")) {
            return;
        }
        for (const other of this.el.querySelectorAll(".kdvn-biz-item.active")) {
            other.classList.remove("active");
        }
        item.classList.add("active");
        const name = item.querySelector(".kdvn-biz-name");
        if (this.figureImg && item.dataset.img) {
            this.figureImg.src = item.dataset.img;
            this.figureImg.alt = name ? name.textContent.trim() : "";
        }
    }

    onEnter(ev) {
        // hover only where a mouse is used (on touch screens mouseenter fires on tap)
        if (ev.type === "mouseenter" && !window.matchMedia("(hover: hover)").matches) {
            return;
        }
        this.activate(ev.currentTarget);
    }

    onNameClick(ev) {
        const item = ev.currentTarget.closest(".kdvn-biz-item");
        if (item && !item.classList.contains("active")) {
            ev.preventDefault();
            this.activate(item);
        }
    }
}

registry.category("public.interactions").add("kdvn_website.home_business", KdvnHomeBusiness);

/** @odoo-module **/
// Information and Communication page: the arrows scroll the Feature tiles
// one screen at a time and switch off at either end.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnBizpageTiles extends Interaction {
    static selector = ".kdvn-bizpage-tiles-section";
    dynamicContent = {
        ".kdvn-bizpage-tiles-prev": {
            "t-on-click": () => this.scrollBy(-1),
            "t-att-disabled": () => this.atStart,
        },
        ".kdvn-bizpage-tiles-next": {
            "t-on-click": () => this.scrollBy(1),
            "t-att-disabled": () => this.atEnd,
        },
        ".kdvn-bizpage-tiles": { "t-on-scroll": this.onScroll },
    };

    setup() {
        this.track = this.el.querySelector(".kdvn-bizpage-tiles");
        this.atStart = true;
        this.atEnd = false;
        this.onScroll();
    }

    scrollBy(direction) {
        this.track.scrollBy({ left: direction * this.track.clientWidth * 0.8, behavior: "smooth" });
    }

    onScroll() {
        const { scrollLeft, scrollWidth, clientWidth } = this.track;
        this.atStart = scrollLeft <= 1;
        this.atEnd = scrollLeft + clientWidth >= scrollWidth - 1;
    }
}

registry.category("public.interactions").add("kdvn_website.bizpage_tiles", KdvnBizpageTiles);

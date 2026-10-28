/** @odoo-module **/
// Past Prominent Projects: the arrows under a year slide that year's row of
// cards. They show only when the row has more cards than fit, and switch off
// at either end.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnProjectRow extends Interaction {
    static selector = ".kdvn-proj-group";
    dynamicContent = {
        ".kdvn-proj-prev": {
            "t-on-click": () => this.scrollBy(-1),
            "t-att-disabled": () => this.atStart,
        },
        ".kdvn-proj-next": {
            "t-on-click": () => this.scrollBy(1),
            "t-att-disabled": () => this.atEnd,
        },
        ".kdvn-proj-nav": { "t-att-hidden": () => !this.overflows },
        ".kdvn-proj-row": { "t-on-scroll": this.update },
        _window: { "t-on-resize": this.update },
    };

    setup() {
        this.track = this.el.querySelector(".kdvn-proj-row");
        this.update();
    }

    scrollBy(direction) {
        this.track.scrollBy({ left: direction * this.track.clientWidth * 0.8, behavior: "smooth" });
    }

    update() {
        const { scrollLeft, scrollWidth, clientWidth } = this.track;
        this.overflows = scrollWidth > clientWidth + 1;
        this.atStart = scrollLeft <= 1;
        this.atEnd = scrollLeft + clientWidth >= scrollWidth - 1;
    }
}

registry.category("public.interactions").add("kdvn_website_project.project_row", KdvnProjectRow);

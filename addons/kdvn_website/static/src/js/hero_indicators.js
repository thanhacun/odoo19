/** @odoo-module **/
// Homepage hero slider: keep the (hidden) indicators in step with the slides.
// Bootstrap's carousel moves the "active" class along the indicators; when a
// slide has no indicator (e.g. a slide duplicated in the website editor) the
// active one disappears and the next slide crashes ("reading 'classList'").
// Here: one indicator per slide, numbered, the active slide's one marked.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnHeroIndicators extends Interaction {
    static selector = ".kdvn-hero.carousel";

    setup() {
        const items = [...this.el.querySelectorAll(".carousel-item")];
        const box = this.el.querySelector(".carousel-indicators");
        if (!box || !items.length) {
            return;
        }
        let activeIndex = items.findIndex((item) => item.classList.contains("active"));
        if (activeIndex < 0) {
            activeIndex = 0;
            items[0].classList.add("active");
        }
        const buttons = [...box.children];
        for (let i = buttons.length; i < items.length; i++) {
            const button = document.createElement("button");
            button.type = "button";
            box.appendChild(button);
            buttons.push(button);
        }
        buttons.slice(items.length).forEach((button) => button.remove());
        buttons.slice(0, items.length).forEach((button, i) => {
            button.setAttribute("data-bs-target", `#${this.el.id}`);
            button.setAttribute("data-bs-slide-to", String(i));
            button.setAttribute("aria-label", `Slide ${i + 1}`);
            button.classList.toggle("active", i === activeIndex);
            if (i === activeIndex) {
                button.setAttribute("aria-current", "true");
            } else {
                button.removeAttribute("aria-current");
            }
        });
    }
}

registry.category("public.interactions").add("kdvn_website.hero_indicators", KdvnHeroIndicators);

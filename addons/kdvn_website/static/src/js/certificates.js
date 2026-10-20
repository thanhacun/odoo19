/** @odoo-module **/
// Licenses & Certifications: slider + full-size view.
// - The current certificate is large, the others small; the arrows (or a
//   swipe on touch screens) move to the previous / next one. The track is
//   shifted so the current certificate starts at the left of the content.
// - Clicking a certificate opens it full size; closed with the X, a click on
//   the dark background or Escape.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class KdvnCertificates extends Interaction {
    static selector = ".kdvn-certs";
    dynamicContent = {
        ".kdvn-certs-prev": {
            "t-on-click": () => this.go(this.index - 1),
            "t-att-disabled": () => this.index <= 0,
        },
        ".kdvn-certs-next": {
            "t-on-click": () => this.go(this.index + 1),
            "t-att-disabled": () => this.index >= this.items.length - 1,
        },
        ".kdvn-cert-open": { "t-on-click": this.open },
        ".kdvn-certs-track": {
            "t-on-pointerdown": this.onPointerDown,
            "t-on-pointerup": this.onPointerUp,
        },
        _document: { "t-on-keydown": this.onKeydown },
    };

    setup() {
        this.track = this.el.querySelector(".kdvn-certs-track");
        this.items = [...this.el.querySelectorAll(".kdvn-cert")];
        this.index = Math.max(0, this.items.findIndex((item) => item.classList.contains("is-active")));
        this.lightbox = document.querySelector(".kdvn-lightbox");
        this.startX = null;
    }

    go(index) {
        if (index < 0 || index >= this.items.length) {
            return;
        }
        this.index = index;
        this.items.forEach((item, i) => item.classList.toggle("is-active", i === index));
        this.track.style.setProperty("--kdvn-cert-index", index);
    }

    onPointerDown(ev) {
        this.startX = ev.pointerType === "mouse" ? null : ev.clientX;
    }

    onPointerUp(ev) {
        if (this.startX === null) {
            return;
        }
        const dx = ev.clientX - this.startX;
        this.startX = null;
        if (Math.abs(dx) > 40) {
            this.go(this.index + (dx < 0 ? 1 : -1));
            this.swiped = true;
        }
    }

    open(ev) {
        if (this.swiped) {
            this.swiped = false;
            return;
        }
        if (!this.lightbox) {
            return;
        }
        const button = ev.currentTarget;
        const img = this.lightbox.querySelector(".kdvn-lightbox-img");
        img.loading = "eager";   // Odoo marks page images lazy; this one is loaded on demand
        img.src = button.dataset.full;
        img.alt = button.getAttribute("aria-label") || "";
        this.lightbox.hidden = false;
        document.body.classList.add("kdvn-modal-open");
        this.opener = button;
        this.lightbox.querySelector(".kdvn-lightbox-close")?.focus();
        for (const el of this.lightbox.querySelectorAll("[data-kdvn-close]")) {
            el.onclick = () => this.close();
        }
    }

    close() {
        if (!this.lightbox || this.lightbox.hidden) {
            return;
        }
        this.lightbox.hidden = true;
        document.body.classList.remove("kdvn-modal-open");
        this.opener?.focus();
    }

    onKeydown(ev) {
        if (this.lightbox && !this.lightbox.hidden) {
            if (ev.key === "Escape") {
                this.close();
            }
            return;
        }
        if (ev.key === "ArrowLeft" && this.el.contains(document.activeElement)) {
            this.go(this.index - 1);
        } else if (ev.key === "ArrowRight" && this.el.contains(document.activeElement)) {
            this.go(this.index + 1);
        }
    }

    destroy() {
        document.body.classList.remove("kdvn-modal-open");
    }
}

registry.category("public.interactions").add("kdvn_website.certificates", KdvnCertificates);

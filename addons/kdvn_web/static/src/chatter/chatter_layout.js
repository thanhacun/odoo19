/** @odoo-module **/
// Where the form chatter sits. Odoo 19 puts it on the right from 1400px wide (SIZES.XXL); Odoo 12 always had it at the bottom.
// KDVN: on the right only on a really large screen, at the bottom on anything narrower.
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";
import "@mail/chatter/web/form_renderer";   // load the core patch first: ours wraps it

// Window width (px) from which the chatter goes to the right side. Full HD (1920) stays below it, 2560 wide screens are above.
export const KDVN_CHATTER_ASIDE_MIN_WIDTH = 2560;

patch(FormRenderer.prototype, {
    mailLayout(hasAttachmentContainer) {
        const layout = super.mailLayout(hasAttachmentContainer);
        if (window.innerWidth < KDVN_CHATTER_ASIDE_MIN_WIDTH) {
            if (layout === "SIDE_CHATTER") {
                return "BOTTOM_CHATTER";
            }
            if (layout === "EXTERNAL_COMBO_XXL") {
                return "EXTERNAL_COMBO";
            }
        }
        return layout;
    },
});

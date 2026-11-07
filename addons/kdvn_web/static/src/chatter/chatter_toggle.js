/** @odoo-module **/
// Port of Odoo 12 chatter_toggle.js: the messages of the chatter are hidden until the user clicks "Show Chatter" (button in the top bar,
// next to Send message / Log note), to keep forms neat. Works the same when the chatter is at the bottom or on the right.
import { patch } from "@web/core/utils/patch";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import "@mail/chatter/web/chatter_patch";   // load the core patch first: ours wraps it

patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.state.kdvnHidden = true;    // like Odoo 12: collapsed every time a form opens
    },
    kdvnToggleChatter() {
        this.state.kdvnHidden = !this.state.kdvnHidden;
    },
});

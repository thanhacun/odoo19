/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MediaDialog } from "@web_editor/components/media_dialog/media_dialog";

// Patching Odoo 19's media builder selection drawer
patch(MediaDialog.prototype, {
    setup() {
        super.setup();
        
        // Append your designer's Remix Icon collection search tags right into the system options array
        if (this.iconFonts) {
            this.iconFonts.push({
                baseClass: 'ri',
                prefix: 'ri-',
                name: 'Remix Icon Pack',
                // A quick structural seed list of your designer's top core architectural icons
                icons: [
                    'home-line', 'home-fill', 'building-line', 'building-fill',
                    'settings-line', 'settings-fill', 'phone-line', 'mail-line',
                    'arrow-right-line', 'arrow-left-line', 'search-line', 'globe-line',
                    'facebook-box-line', 'linkedin-box-line', 'map-pin-line'
                ]
            });
        }
    }
});

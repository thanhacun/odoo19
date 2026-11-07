odoo.define('kdvn_knowledge.UserMenu', function (require) {
    "use strict";

    var UserMenu = require('web.UserMenu');

    UserMenu.include({
        /**
         * User menu > User Guides: the guide root. Opened as a client action (not a URL),
         * so the web client keeps debug mode.
         */
        _onMenuKderpGuides: function () {
            var self = this;
            this._rpc({
                model: 'document.page',
                method: 'kderp_action_open_guide',
                args: ['user-guides'],
            }).then(function (action) {
                self.do_action(action);
            });
        },
    });
});

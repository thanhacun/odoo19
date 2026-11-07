odoo.define('kdvn_knowledge.guide_links', function (require) {
'use strict';

// Links inside the guide reader stay in the menu the reader was opened from.
$(document).on('click', '.kderp_guide_reader a[href^="/web#"]', function (ev) {
    var current = /[#&]menu_id=(\d+)/.exec(window.location.hash);
    if (!current) {
        return;  // no menu in the current URL: keep the server's choice
    }
    var target = $(this).attr('href').split('#')[1].replace(/(^|&)menu_id=\d+/, '');
    target = target.replace(/^&/, '') + '&menu_id=' + current[1];
    ev.preventDefault();
    window.location.hash = target;
});

});
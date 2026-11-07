/** @odoo-module **/
// Links inside the guide reader stay in the menu the reader was opened from (legacy /web# links of guide pages).
document.addEventListener("click", (ev) => {
    const link = ev.target.closest && ev.target.closest('.kderp_guide_reader a[href^="/web#"]');
    if (!link) {
        return;
    }
    const current = /[#&?]menu_id=(\d+)/.exec(window.location.href);
    if (!current) {
        return; // no menu in the current URL: keep the server's choice
    }
    const target = link.getAttribute("href").split("#")[1].replace(/(^|&)menu_id=\d+/, "").replace(/^&/, "") + "&menu_id=" + current[1];
    ev.preventDefault();
    window.location.hash = target;
});

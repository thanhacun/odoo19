/** @odoo-module **/
// Odoo 12 showed a Text field built from <span>/<br/> markup (attendance "request marks") through widget="html". Odoo 19's html widget only
// supports Html fields (text shows the tags as plain text), so this read-only widget renders the markup, keeping only a small allowlist of tags
// and attributes (the text inside is user input and is not escaped on the server).
import { Component, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const ALLOWED_TAGS = new Set(["SPAN", "BR", "B", "STRONG", "I", "EM", "U", "SMALL", "P", "DIV", "UL", "OL", "LI"]);
const SAFE_CLASS = /^[\w\s-]*$/;

function cleanNode(node, out) {
    for (const child of node.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
            out.append(document.createTextNode(child.textContent));
        } else if (child.nodeType === Node.ELEMENT_NODE) {
            if (ALLOWED_TAGS.has(child.tagName)) {
                const copy = document.createElement(child.tagName.toLowerCase());
                const cls = child.getAttribute("class");
                if (cls && SAFE_CLASS.test(cls)) {
                    copy.setAttribute("class", cls);
                }
                cleanNode(child, copy);
                out.append(copy);
            } else if (!["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED"].includes(child.tagName)) {
                cleanNode(child, out);   // unknown tag: keep its text only
            }
        }
    }
}

export function sanitizeMarkup(text) {
    const doc = new DOMParser().parseFromString(`<body>${text || ""}</body>`, "text/html");
    const box = document.createElement("div");
    cleanNode(doc.body, box);
    return markup(box.innerHTML);
}

export class HtmlTextField extends Component {
    static template = "kdvn_web.HtmlTextField";
    static props = { ...standardFieldProps };

    get html() {
        return sanitizeMarkup(this.props.record.data[this.props.name]);
    }
}

registry.category("fields").add("kdvn_html_text", {
    component: HtmlTextField,
    displayName: "Markup text (read only)",
    supportedTypes: ["text", "char", "html"],
});

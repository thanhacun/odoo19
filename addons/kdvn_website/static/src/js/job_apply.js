/** @odoo-module **/
// Job page (/jobs/<job>): application form. Checks the fields, asks for
// confirmation in a popup, posts the form (answer: {ok, errors}) and shows the
// "Application submitted!" or "Something went wrong!" popup. Messages come from
// data-msg-* on the form, so they are translated with the page.
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

const MAX_RESUME_SIZE = 10 * 1024 * 1024;
const RESUME_EXTENSIONS = [".pdf", ".doc", ".docx"];
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export class KdvnJobApply extends Interaction {
    static selector = ".kdvn-job-apply";
    dynamicContent = {
        "form": { "t-on-submit.prevent": this.onSubmit },
        ".kdvn-input": { "t-on-input": this.onInput },
        "input[type=file]": { "t-on-change": this.onFileChange },
        "[data-kdvn-remove-file]": { "t-on-click": this.removeFile },
        ".kdvn-dropzone": {
            "t-on-dragover.prevent": () => this.dropzone.classList.add("is-dragover"),
            "t-on-dragleave": () => this.dropzone.classList.remove("is-dragover"),
            "t-on-drop.prevent": this.onDrop,
        },
        "[data-kdvn-close]": { "t-on-click": this.onClose },
        "[data-kdvn-confirm]": { "t-on-click": this.send },
        _document: { "t-on-keydown": this.onKeydown },
    };

    setup() {
        this.form = this.el.querySelector("form");
        this.dropzone = this.el.querySelector(".kdvn-dropzone");
        this.fileInput = this.el.querySelector("input[type=file]");
        this.fileBox = this.el.querySelector(".kdvn-resume-file");
        this.submitButton = this.el.querySelector(".kdvn-apply-submit");
    }

    // --- fields
    fieldBox(input) {
        return input.closest(".kdvn-field");
    }

    setError(input, message) {
        const box = this.fieldBox(input);
        const error = box.querySelector(".kdvn-field-error");
        box.classList.toggle("has-error", !!message);
        if (error) {
            error.textContent = message || "";
            error.hidden = !message;
        }
    }

    onInput(ev) {
        this.setError(ev.target, "");
    }

    validate() {
        const msg = this.form.dataset;
        let first = null;
        const fail = (input, message) => {
            this.setError(input, message);
            first = first || input;
        };
        for (const input of this.form.querySelectorAll(".kdvn-input[required]")) {
            const value = input.value.trim();
            if (!value) {
                fail(input, msg.msgRequired);
            } else if (input.type === "email" && !EMAIL_RE.test(value)) {
                fail(input, msg.msgEmail);
            } else {
                this.setError(input, "");
            }
        }
        const file = this.fileInput.files[0];
        if (!file) {
            fail(this.fileInput, msg.msgRequired);
        } else if (!this.isValidResume(file)) {
            fail(this.fileInput, msg.msgResume);
        } else {
            this.setError(this.fileInput, "");
        }
        if (first) {
            first.focus();
        }
        return !first;
    }

    // --- resume
    isValidResume(file) {
        const name = file.name.toLowerCase();
        return file.size <= MAX_RESUME_SIZE && RESUME_EXTENSIONS.some((ext) => name.endsWith(ext));
    }

    onFileChange() {
        this.showFile(this.fileInput.files[0]);
    }

    onDrop(ev) {
        this.dropzone.classList.remove("is-dragover");
        const file = ev.dataTransfer.files[0];
        if (file) {
            const transfer = new DataTransfer();
            transfer.items.add(file);
            this.fileInput.files = transfer.files;
            this.showFile(file);
        }
    }

    showFile(file) {
        this.setError(this.fileInput, "");
        this.dropzone.hidden = !!file;
        this.fileBox.hidden = !file;
        if (file) {
            this.fileBox.querySelector(".kdvn-resume-name").textContent = file.name;
            this.fileBox.querySelector(".kdvn-resume-size").textContent =
                (file.size / (1024 * 1024)).toFixed(1) + " MB";
        }
    }

    removeFile() {
        this.fileInput.value = "";
        this.showFile(null);
    }

    // --- popups
    modal(id) {
        return this.el.querySelector("#" + id);
    }

    openModal(id) {
        this.closeModals();
        const modal = this.modal(id);
        modal.hidden = false;
        document.body.classList.add("kdvn-modal-open");
        modal.querySelector(".kdvn-modal-close")?.focus();
    }

    closeModals() {
        for (const modal of this.el.querySelectorAll(".kdvn-modal")) {
            modal.hidden = true;
        }
        document.body.classList.remove("kdvn-modal-open");
    }

    onClose() {
        this.closeModals();
    }

    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.closeModals();
        }
    }

    // --- send
    onSubmit() {
        if (this.validate()) {
            this.openModal("kdvn_apply_confirm");
        }
    }

    async send() {
        this.closeModals();
        this.submitButton.disabled = true;
        let result;
        try {
            const response = await this.waitFor(
                fetch(this.form.action, { method: "POST", body: new FormData(this.form) })
            );
            result = response.ok ? await this.waitFor(response.json()) : { ok: false };
        } catch {
            result = { ok: false };
        }
        this.submitButton.disabled = false;
        if (result.ok) {
            this.form.reset();
            this.showFile(null);
            this.openModal("kdvn_apply_success");
            return;
        }
        for (const [name, message] of Object.entries(result.errors || {})) {
            const input = this.form.elements[name];
            if (input) {
                this.setError(input, message);
            }
        }
        this.openModal("kdvn_apply_error");
    }

    destroy() {
        document.body.classList.remove("kdvn-modal-open");
    }
}

registry.category("public.interactions").add("kdvn_website.job_apply", KdvnJobApply);

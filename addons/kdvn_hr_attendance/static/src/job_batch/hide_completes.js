/** @odoo-module **/
// Port of Odoo 12 job_batch_systray.js: a "Hide Completes" button in the job batches menu of the top bar: one click marks every finished
// batch as read (hides it), instead of clicking the check mark of each batch.
import { patch } from "@web/core/utils/patch";
import { QueueJobBatchMenu } from "@queue_job_batch/components/QueueJobBatchMenu.esm";

patch(QueueJobBatchMenu.prototype, {
    get finishedBatches() {
        return Object.values(this.store["queue.job.batch"].records).filter((batch) => batch.state === "finished");
    },

    async hideCompleted(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        await Promise.all(this.finishedBatches.map((batch) => batch.markAsRead()));
    },
});

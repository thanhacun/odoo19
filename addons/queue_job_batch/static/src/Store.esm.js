/*
    Copyright 2025 Camptocamp SA (https://www.camptocamp.com).
    License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
    Port to Odoo 19.0 by Kinden Vietnam: the store is initialised with fetchStoreData(name), see controllers/webclient.py.
*/
import {Store} from "@mail/core/common/store_service";
import {patch} from "@web/core/utils/patch";

patch(Store.prototype, {
    setup() {
        super.setup(...arguments);
        this.hasQueueJobBatchUserGroup = false;
        this.queueJobBatchCounterBusId = 0;
        this.queueJobBatchCounter = 0;
    },

    /** @override */
    async initialize() {
        await Promise.all([
            super.initialize(...arguments),
            this.fetchStoreData("systray_get_queue_job_batches"),
        ]);
    },
});

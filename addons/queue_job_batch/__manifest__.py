# Port of OCA/queue queue_job_batch 18.0 to Odoo 19.0 by Kinden Vietnam: the 19.0 branch of OCA/queue still has this module disabled
# (installable False). Same technical name and model names: remove this copy and use the OCA one when it is migrated upstream.
# Copyright 2019 Creu Blanca
# Copyright 2023 ForgeFlow S.L. (http://www.forgeflow.com)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

{
    "name": "Job Queue Batch",
    "version": "19.0.1.0.0",
    "author": "Creu Blanca,Odoo Community Association (OCA),Kinden Vietnam (port to 19.0)",
    "website": "https://github.com/OCA/queue",
    "license": "AGPL-3",
    "category": "Generic Modules",
    "depends": [
        "queue_job",
    ],
    "data": [
        # data
        "data/queue_job_channel_data.xml",
        "data/queue_job_function_data.xml",
        # security
        "security/security.xml",
        "security/ir.model.access.csv",
        # views
        "views/queue_job_views.xml",
        "views/queue_job_batch_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "queue_job_batch/static/src/**/*.js",
            "queue_job_batch/static/src/**/*.xml",
            "queue_job_batch/static/src/**/*.scss",
        ],
    },
    "installable": True,
}

/** @odoo-module **/
// Port of Odoo 12 review_colors.js + tier_review_table.xml: the "Reviews" panel of a request (OCA widget form.tier_validation) with the columns
// of the tier.review list view (#, Step, Reviewers, Status, By, Date, Comment) and one colour per status (review_colors.css).
// The step the flow is waiting for right now (lowest pending sequence) gets the extra class kderp_review_current.
import { registry } from "@web/core/registry";
import { reviewsTableComponent, ReviewsTable } from "@base_tier_validation/components/tier_review_widget/tier_review_widget.esm";

export class KdvnReviewsTable extends ReviewsTable {
    static template = "kdvn_e_approval.ReviewsTable";

    setup() {
        super.setup();
        this.state.open = true;   // OCA 19.0 hard-codes the collapse id "collapse1", so two panels on one screen fought each other: own state per panel
    }

    toggleOpen(ev) {
        ev.preventDefault();
        this.state.open = !this.state.open;
    }

    get reviews() {
        return this._getReviewData();
    }

    get currentSequence() {
        const pending = this.reviews.filter((r) => r.status === "pending").map((r) => r.sequence);
        return pending.length ? Math.min(...pending) : null;
    }

    rowClass(review) {
        let cls = "kderp_review_" + review.status;
        if (review.status === "pending" && review.sequence === this.currentSequence) {
            cls += " kderp_review_current";
        }
        return cls;
    }
}

registry.category("fields").add(
    "form.tier_validation",
    {
        ...reviewsTableComponent,
        component: KdvnReviewsTable,
        relatedFields: [...reviewsTableComponent.relatedFields, { name: "frontend_step_name", type: "char" }],
    },
    { force: true }
);

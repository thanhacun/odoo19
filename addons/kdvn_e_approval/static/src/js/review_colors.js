odoo.define('kdvn_e_approval.ReviewFieldColors', function (require) {
    "use strict";

    var core = require('web.core');
    var ReviewField = require('base_tier_validation.ReviewField');
    var QWeb = core.qweb;

    ReviewField.include({
        /**
         * OCA's template hard-codes the collapse id "collapse1", so two panels on one
         * screen would open and close each other. Give each panel its own id.
         */
        start: function () {
            var collapseId = _.uniqueId('o_kderp_review_collapse_');
            this.$('.panel-collapse').attr('id', collapseId);
            this.$('.o_info_btn').attr('data-target', '#' + collapseId);
            return this._super.apply(this, arguments);
        },

        /**
         * Render our table (same columns as the tier.review list view) instead of OCA's.
         */
        _renderDropdown: function () {
            var self = this;
            return this._getReviewData(this.value).then(function () {
                self.$('.o_review').html(QWeb.render('kderp.tier.review.ReviewsTable', {
                    reviews: self.reviews,
                }));
                self._colorReviewRows();
            });
        },

        /**
         * One class per status on each <tr>. Rows are in the same order as
         * self.reviews, so we match them by index.
         * The pending reviews with the lowest sequence are marked "current":
         * they are the ones the flow is waiting for.
         */
        _colorReviewRows: function () {
            var reviews = this.reviews || [];
            var pendingSeqs = reviews
                .filter(function (r) { return r.status === 'pending'; })
                .map(function (r) { return r.sequence; });
            var currentSeq = pendingSeqs.length ? Math.min.apply(null, pendingSeqs) : null;

            this.$('.o_review tbody tr').each(function (i, tr) {
                var review = reviews[i];
                if (!review) {
                    return;
                }
                var $tr = $(tr);
                // the original alert-* classes would fight with ours
                $tr.removeClass('alert-success alert-danger');
                $tr.addClass('kderp_review_' + review.status);
                if (review.status === 'pending' && review.sequence === currentSeq) {
                    $tr.addClass('kderp_review_current');
                }
            });
        }
    });
});
# n8n workflows: E-Approval Decision Center (legacy)

Since 19.0.0.2.7 Odoo serves these pages itself (`/ea/<code>`, setting "Approve/Reject pages in Odoo"). Keep these files only until every site has switched and old links have expired.


The pages behind the Approve / Reject links in e-approval emails and Talk messages.
One workflow per site; import the file into that site's n8n (Workflows > Import from file),
or copy the changed Code nodes.

| File | Site | Webhook paths (long / short) |
|---|---|---|
| `e_approval_decision_center_dev.json` | dev (demo-atthn) | `e-approval-mobile-gateway` / `ea` |
| `e_approval_decision_center_hn_production.json` | HN production | `e-approval-mobile-gateway-hn-product` / `ea-hn` |

- "Site settings" node holds the Odoo URL (HN: set the real one before importing).
- All pages call Odoo `POST /api/v1/mobile_review_action` (`kderp_e_approval/controllers/main.py`).
- Opening a link never approves: approve asks for confirmation (and a comment when the
  approval rule has Comment ticked); reject asks for a reason.
- Result pages follow Odoo's answer: approved / rejected / already decided / error.
- When both change, deploy n8n first, then upgrade `kderp_e_approval`.
- Keep these files in sync with what is deployed in n8n (export after editing there).

# kdvn_website_project: Past Prominent Projects
Page /prominent-projects (year tabs, grid or list, category filter) plus a homepage section.
Depends only on kdvn_website; follow its rules (addons/kdvn_website/CLAUDE.md) for templates, SCSS and translations.
Details and decisions: docs/kdvn_website_project.md. Page spec: design/kdvn_website/specs/prominent-projects.md.
Import notes and the old n8n workflow: design/kdvn_website_project/. Relay workflow: design/kdvn_remote_integration/n8n/.

- Model kdvn.website.project: website fields are editable; imported kderp_* fields are read-only.
  Re-imports refresh only the kderp_* fields (website edits are kept). New projects start unpublished.
- Data: a nightly cron (and Settings > Website Projects > Import now) READS the finished big jobs from KDERP with
  kdvn_remote_integration (models/project_pull.py): direct on a server that reaches KDERP, through the relay (one plain
  n8n webhook, Settings > Remote Server Connection > Relay) on beta / the public site. No logic in n8n.
  Grouped by name, kept from the minimum USD amount. The older push POST /api/v1/website_projects (X-API-Key) still works.
- No link to kdvn_remote_sync (decision 2026-10-20): closed jobs do not go into its cache.
- The Odoo 12 module of the same name is reference only (~/odoo12/addons/kdvn_website_project).
- Open (see docs): Odoo 12 data migration, designer questions, n8n credentials and HCMC server.

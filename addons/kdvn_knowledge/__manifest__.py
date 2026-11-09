{
    'name': 'KDERP Knowledge',
    'summary': 'User guides and company knowledge pages inside Odoo (on OCA document_page)',
    'description': """
Knowledge base for KDERP, in the spirit of Odoo Enterprise Knowledge, built on the OCA
knowledge modules:

* everyone can write pages; a new page or a change stays pending until a
  "Knowledge reviewer" approves it (OCA document_page_approval);
* pages and blocks inside pages can be limited to roles (applicant, manager, admin),
  matched to Odoo groups;
* user guides are written as Markdown in git (documentation/guides) and published with
  documentation/guides/tools/publish.py: a publish never overwrites a page, it adds a
  change request for review;
* fixed links /kderp/guide/<key>, used by the user menu and by each module's Help menu.
""",
    'author': 'KDVN IT-Dev',
    'website': 'http://www.kinden.com.vn',
    'category': 'Knowledge Management',
    'version': '19.0.0.1.1',
    'license': 'AGPL-3',
    'depends': [
        'kdvn_base',
        'document_knowledge',
        'document_page',
        'document_page_approval',
        'mail',
        'web',
    ],
    'data': [
        'security/knowledge_security.xml',
        'security/ir.model.access.csv',
        'data/knowledge_role_data.xml',
        'data/knowledge_page_data.xml',
        'views/knowledge_role_views.xml',
        'views/document_page_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kdvn_knowledge/static/src/scss/guide.scss',
            'kdvn_knowledge/static/src/user_menu/guides_menu.js',
            'kdvn_knowledge/static/src/user_menu/guide_links.js',
        ],
    },
    'installable': True,
    'application': False,
}

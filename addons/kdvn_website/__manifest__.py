# kderp_website/__manifest__.py
{
    'name': 'KDERP Official Enterprise Website',
    'description': 'Production-grade enterprise website built matching Figma layout tokens.',
    'category': 'Website/Theme',
    'version': '19.0.1.15.1',
    'author': 'KDERP',
    'license': 'LGPL-3',
    'depends': ['website', 'website_hr_recruitment'],
    'data': [
        'security/ir.model.access.csv',
        'views/kdvn_website_media_views.xml',
        'views/website_menu_views.xml',
        'views/company_views.xml',
        'views/website_inquiry_views.xml',
        'data/website_inquiry_data.xml',
        'data/website_media.xml',
        'views/assets.xml',
        'views/snippets.xml',
        'views/components/company_info.xml',
        'views/components/home_business.xml',
        'views/layout_header.xml',
        'views/layout_footer.xml',
        'views/homepage.xml',
        'views/components/page_layout.xml',
        'views/pages/company_profile_pages.xml',
        'views/pages/business_information_pages.xml',
        'views/pages/contact_pages.xml',
        'views/pages/recruitment_pages.xml',
        'views/pages/office_locations_pages.xml',
        'data/menus.xml',
    ],
    'assets': {
        # Core layout design variables loaded before Bootstrap compiles
        'web._assets_primary_variables': [
            'kdvn_website/static/src/scss/primary_variables.scss',
        ],
        # Main consumer-facing stylesheet layer
        'web.assets_frontend': [
            'kdvn_website/static/src/scss/theme_utilities.scss',
            'kdvn_website/static/src/scss/theme.scss',
            'kdvn_website/static/src/js/office_locator.js',
            'kdvn_website/static/src/js/home_business.js',
            'kdvn_website/static/src/js/inquiry_modal.js',
        ],
        'web_editor.assets_media_dialog': [
            'kdvn_website/static/src/js/options/remix_icons_options.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

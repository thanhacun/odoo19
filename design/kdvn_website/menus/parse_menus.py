import csv
import html
import os

HERE = os.path.dirname(os.path.abspath(__file__))
menus_csv = os.path.join(HERE, 'menus.csv')
unlink_csv = os.path.join(HERE, 'unlink_menus.csv')
# design/kdvn_website/menus/ -> addons/kdvn_website/data/menus.xml
xml_output_path = os.path.normpath(os.path.join(HERE, '../../../addons/kdvn_website/data/menus.xml'))

os.makedirs(os.path.dirname(xml_output_path), exist_ok=True)

xml_content = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- ======================================================================== -->
    <!-- AUTOMATED SYSTEM MENUS CLEANUP                                           -->
    <!-- ======================================================================== -->
"""

# 1. Dynamically read and append delete rules from unlink_menus.csv
if os.path.exists(unlink_csv):
    with open(unlink_csv, mode='r', encoding='utf-8') as u_file:
        u_reader = csv.DictReader(u_file)
        for row in u_reader:
            safe_url = html.escape(row['url'].strip())
            xml_content += f"    <!-- Clear default system menu: {row['name']} -->\n"
            xml_content += f"    <delete model=\"website.menu\" search=\"[('url', '=', '{safe_url}'), ('website_id', '=', ref('website.default_website'))]\"/>\n"

xml_content += """
    <!-- ======================================================================== -->
    <!-- CUSTOM DESIGN NAVIGATION MATRIX                                          -->
    <!-- ======================================================================== -->
    <!-- noupdate="0" during development: every module update resets the menus to
         menus.csv (menu edits made in the website are overwritten).
         Switch to noupdate="1" before go-live so editors' menu changes are kept. -->
    <data noupdate="0">
"""

# 2. Directly write records following the CSV definitions exactly
with open(menus_csv, mode='r', encoding='utf-8') as file:
    reader = csv.DictReader(file)
    for row in reader:
        safe_name = html.escape(row['name'].strip())
        safe_url = html.escape(row['url'].strip())
        
        xml_content += f"        <!-- Menu: {safe_name} -->\n"
        xml_content += f"        <record id=\"{row['xml_id'].strip()}\" model=\"website.menu\">\n"
        xml_content += f"            <field name=\"name\">{safe_name}</field>\n"
        xml_content += f"            <field name=\"url\">{safe_url}</field>\n"
        xml_content += "            <field name=\"website_id\" ref=\"website.default_website\"/>\n"
        # The root menu gets neither is_mega_menu nor parent_id: writing either
        # one re-runs Odoo 19's menu check (_validate_parent_menu) on the root,
        # which fails once it has grandchildren ("Menus with child menus cannot
        # be added as a submenu"). Both default to empty/False on creation anyway.
        if row['parent_xml_id'].strip():
            xml_content += "            <field name=\"is_mega_menu\">False</field>\n"
            xml_content += f"            <field name=\"parent_id\" ref=\"{row['parent_xml_id'].strip()}\"/>\n"

        xml_content += f"            <field name=\"sequence\" type=\"int\">{row['sequence'].strip()}</field>\n"
        # Overview page for menus with sub-items (Odoo 19 forces their url to '#')
        overview_url = (row.get('overview_url') or '').strip()
        if overview_url:
            xml_content += f"            <field name=\"overview_url\">{html.escape(overview_url)}</field>\n"
        # Optional dropdown description (custom field kdvn_website adds to website.menu)
        description = (row.get('description') or '').strip()
        if description:
            xml_content += f"            <field name=\"description\">{html.escape(description)}</field>\n"
        xml_content += "        </record>\n\n"

xml_content += """    </data>
</odoo>
"""

with open(xml_output_path, 'w', encoding='utf-8') as xml_file:
    xml_file.write(xml_content)

print(f"✅ Success! Your direct-mapping menus file has been compiled to: {xml_output_path}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os

# design/kdvn_website/tokens/ -> addons/kdvn_website/
ADDON_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../addons/kdvn_website'))

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Updated to your designated clean file coordinate mapping targets
    json_path = os.path.join(current_dir, 'tokens.json')
    
    variables_output_path = os.path.join(ADDON_DIR, 'static/src/scss/primary_variables.scss')
    utilities_output_path = os.path.join(ADDON_DIR, 'static/src/scss/theme_utilities.scss')

    if not os.path.exists(json_path):
        print(f"[-] Error: Could not locate figma tokens target file at {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        schema_data = json.load(f)

    if isinstance(schema_data, dict):
        collections = schema_data.get("collections", [])
    elif isinstance(schema_data, list):
        collections = schema_data
    else:
        collections = []

    # Unpack unique variable tokens registry reference paths
    id_registry = {}
    for collection in collections:
        if isinstance(collection, dict):
            for variable in collection.get("variables", []):
                if isinstance(variable, dict) and "id" in variable:
                    id_registry[variable["id"]] = variable

    def _unwrap_token_value(var_node, depth=0):
        if depth > 12 or not isinstance(var_node, dict):
            return var_node
        values_by_mode = var_node.get("valuesByMode", {})
        if not values_by_mode:
            return None
        mode_payload = next(iter(values_by_mode.values()), None)
        if isinstance(mode_payload, dict) and mode_payload.get("type") == "VARIABLE_ALIAS":
            alias_id = mode_payload.get("id")
            if alias_id in id_registry:
                return _unwrap_token_value(id_registry[alias_id], depth + 1)
        return mode_payload

    def _to_css_format(primitive, name_slug):
        if isinstance(primitive, dict) and 'r' in primitive:
            r = int(round(primitive.get('r', 0) * 255))
            g = int(round(primitive.get('g', 0) * 255))
            b = int(round(primitive.get('b', 0) * 255))
            a = primitive.get('a', 1.0)
            if float(a) < 1.0:
                return f"rgba({r}, {g}, {b}, {round(float(a), 3)})"
            return f"#{r:02x}{g:02x}{b:02x}"
        if isinstance(primitive, (int, float)):
            if any(x in name_slug for x in ["size", "padding", "margin", "gutter", "gap", "radius", "dm-"]):
                if "weight" in name_slug:
                    return str(int(primitive))
                return f"{float(primitive) / 16.0}rem" if primitive > 0 else "0"
            return str(primitive)
        return f"'{str(primitive)}'" if primitive else "transparent"

    # Compile the active values dictionary matrix configuration blocks
    variables_dict = {}
    for var_id, var_node in id_registry.items():
        raw_name = var_node.get("name", "")
        clean_key = raw_name.lower().replace("/", "-").replace(" ", "-").replace("_", "-")
        resolved_primitive = _unwrap_token_value(var_node)
        if resolved_primitive is not None:
            variables_dict[clean_key] = _to_css_format(resolved_primitive, clean_key)

    # --- ODOO 19 SCHEMA COLOR LOOKUPS ---
    # Safe lookups to fall back on if tokens are slightly offset
    brand_primary = variables_dict.get('color-background-neutral-brand-default', '#009942')
    brand_hover = variables_dict.get('color-background-neutral-brand-hover', '#008439')
    neutral_strongest = variables_dict.get('color-content-neutral-strongest', '#0d0d0d')
    bg_canvas = variables_dict.get('color-background-canvas-default', '#ffffff')
    bg_page = variables_dict.get('color-background-canvas-alt', '#ffffff')

    # --- FORMAT 1: primary_variables.scss (OFFICIAL ODOO 19 COMPLIANT SPECIFICATION) ---
    variables_content = f"""// ============================================================================
// AUTOMATED COMPILATION TARGET: SCSS VARIABLES ONLY (DO NOT EDIT)
// ============================================================================
$google-fonts: ('Oswald:300,400,500,600,700', 'Inter+Tight:300,400,500,600,700,800');
$font-family-base: 'Inter Tight', sans-serif;
$headings-font-family: 'Oswald', sans-serif;

// --- DYNAMIC REGISTERED DESIGN CORES
"""
    for k, v in sorted(variables_dict.items()):
        variables_content += f"${k}: {v};\n"

    variables_content += f"""
// Register Oswald with Odoo's font list so it is actually loaded from Google Fonts
// (Odoo 19 only loads fonts listed in $o-theme-font-configs).
$o-theme-font-configs: map-merge($o-theme-font-configs, (
    'Oswald': (
        'family': ('Oswald', sans-serif),
        'url': 'Oswald:400,500,600,700',
    ),
));

// --- ODOO 19 THEME SYSTEM PALETTE SPECIFICATION HOOKS ---
$o-color-palettes: map-merge($o-color-palettes, (
    'kdvn_palette': (
        'o-color-1': {brand_primary}, // Primary Website Accent
        'o-color-2': {brand_hover},   // Secondary Accent Action
        'o-color-3': #efefef,         // Extra Light
        'o-color-4': {bg_page},     // Page background (white; canvas-default is for cards)
        'o-color-5': {neutral_strongest} // Blackish Content
    )
));

// Inject into selection registers array vectors
$o-selected-color-palettes-names: append($o-selected-color-palettes-names, 'kdvn_palette');

// Map layout values to our active corporate configuration profiles
$o-website-values-palettes: (
    (
        'color-palettes-name': 'kdvn_palette',
        'font': 'Inter Tight',
        'headings-font': 'Oswald'
    ),
);
"""

    # --- FORMAT 2: theme_utilities.scss (REUSABLE CLASS MAP TRANSLATIONS) ---
    utilities_content = f"""// ============================================================================
// AUTOMATED COMPILATION TARGET: DESIGN SYSTEM SEMANTIC CLASSES (DO NOT EDIT)
// ============================================================================

// --- 1. TEXT TRANSLATION HOOKS
.kdvn-text-strong {{
    color: {neutral_strongest} !important;
    font-family: $font-family-base;
}}
.kdvn-brand-heading {{
    font-family: $headings-font-family;
    text-transform: uppercase;
}}

// --- 2. THEME COMPONENT SURFACE CLASSES
.kdvn-surface-brand {{
    background-color: {brand_primary} !important;
    color: #ffffff !important;
    
    &:hover {{
        background-color: {brand_hover} !important;
    }}
}}

.kdvn-surface-canvas {{
    background-color: {bg_canvas} !important;
}}
"""

    os.makedirs(os.path.dirname(variables_output_path), exist_ok=True)

    with open(variables_output_path, 'w', encoding='utf-8') as var_f:
        var_f.write(variables_content)
        
    with open(utilities_output_path, 'w', encoding='utf-8') as util_f:
        util_f.write(utilities_content)

    print(f"[+] Odoo 19 Spec Sync: Compiled {len(variables_dict)} values cleanly.")

if __name__ == '__main__':
    main()

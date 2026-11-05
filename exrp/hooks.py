"""
EXRP Frappe Application Hooks
Defines app metadata, Desk assets, and supported Document lifecycle integration hooks.
"""

app_name = "exrp"
app_title = "EXRP"
app_publisher = "EXRP Team"
app_description = "AI-Native Configuration Control Plane for Frappe/ERPNext"
app_email = "developers@exrp.local"
app_license = "MIT"

# Desk assets: Injects the EXRP AI Sidecar into Frappe Desk (cache-busted)
app_include_js = [
    "/assets/exrp/js/ai_sidecar.bundle.js?v=2.2.0"
]

app_include_css = [
    "/assets/exrp/css/ai_sidecar.css?v=2.2.0"
]

# Web / Portal assets (Ensures brand styles and theme persistence on portal pages)
web_include_js = [
    "/assets/exrp/js/ai_sidecar.bundle.js?v=2.2.0"
]

web_include_css = [
    "/assets/exrp/css/ai_sidecar.css?v=2.2.0"
]

# Route root '/' directly to ERP Desk for authenticated users
website_user_home_page = "app"
role_home_page = {
    "System Manager": "app",
    "Desk User": "app",
    "All": "app",
}

# EXRP Official Brand Assets & Logos
app_logo_url = "/assets/exrp/images/exrp-logo.svg"
favicon = "/assets/exrp/images/favicon.svg"

website_context = {
    "favicon": "/assets/exrp/images/favicon.svg",
    "splash_image": "/assets/exrp/images/exrp-logo.svg",
}

# Supported Document Lifecycle hooks for Runtime Policy Enforcement (§4.2)
# Applies to supported application write paths (Desk, REST Document API, and background jobs)
doc_events = {
    "*": {
        "validate": "exrp.api.control_plane.enforce_runtime_policies_on_validate",
        "before_submit": "exrp.api.control_plane.enforce_runtime_policies_on_submit",
        "before_update_after_submit": "exrp.api.control_plane.enforce_runtime_policies_on_update_after_submit",
    }
}

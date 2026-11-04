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

# Desk assets: Injects the EXRP AI Sidecar into Frappe Desk
app_include_js = [
    "/assets/exrp/js/ai_sidecar.bundle.js"
]

app_include_css = [
    "/assets/exrp/css/ai_sidecar.css"
]

# Supported Document Lifecycle hooks for Runtime Policy Enforcement (§4.2)
# Applies to supported application write paths (Desk, REST Document API, and background jobs)
doc_events = {
    "*": {
        "validate": "exrp.api.control_plane.enforce_runtime_policies_on_validate",
        "before_submit": "exrp.api.control_plane.enforce_runtime_policies_on_submit",
        "before_update_after_submit": "exrp.api.control_plane.enforce_runtime_policies_on_update_after_submit",
    }
}

import os
import sys

sites_path = "/home/frappe/frappe-bench/sites"
os.chdir(sites_path)
if sites_path not in sys.path:
    sys.path.insert(0, sites_path)

import frappe.app

frappe.app._site = os.environ.get("FRAPPE_SITE", "exrp.localhost")

application = frappe.app.application_with_statics()

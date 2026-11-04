import os
import sys

sites_path = "/home/frappe/frappe-bench/sites"
os.chdir(sites_path)
if sites_path not in sys.path:
    sys.path.insert(0, sites_path)

import frappe.app

application = frappe.app.application_with_statics()

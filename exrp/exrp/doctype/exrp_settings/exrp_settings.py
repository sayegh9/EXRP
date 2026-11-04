# Copyright (c) 2026, EXRP Team and contributors
# For license information, please see license.txt

try:
    import frappe
    from frappe.model.document import Document
except ImportError:
    frappe = None
    class Document:
        pass


class EXRPSettings(Document):
    def validate(self):
        # Strict Tier 0 Lock is an immutable invariant
        self.strict_tier0_lock = 1

        if self.lock_wait_timeout is not None and self.lock_wait_timeout < 1:
            self.lock_wait_timeout = 1

        if self.max_retries is not None and self.max_retries < 0:
            self.max_retries = 0

        if self.temperature is not None:
            if self.temperature < 0.0:
                self.temperature = 0.0
            elif self.temperature > 2.0:
                self.temperature = 2.0

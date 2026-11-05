// Copyright (c) 2026, EXRP Team and contributors
// For license information, please see license.txt

frappe.ui.form.on("EXRP Settings", {
	refresh: function (frm) {
		frm.add_custom_button(__("Test Connection"), function () {
			let rawKey = (frm.doc.api_key || "").trim();
			let isMasked = !rawKey || /^[\*•]+$/.test(rawKey);
			let callArgs = {
				provider: frm.doc.llm_provider,
				model_name: frm.doc.model_name,
				api_base_url: frm.doc.api_base_url
			};
			if (!isMasked) {
				callArgs.api_key = rawKey;
			}
			frappe.call({
				method: "exrp.api.control_plane.test_llm_connection",
				args: callArgs,
				freeze: true,
				freeze_message: __("Testing LLM Connection..."),
				callback: function (r) {
					if (r && r.message && r.message.success) {
						frappe.msgprint({
							title: __("Connection Successful"),
							indicator: "green",
							message: r.message.message || __("Connection verified successfully!")
						});
					} else {
						let msg = (r && r.message && r.message.message) || __("Connection test failed.");
						frappe.msgprint({
							title: __("Connection Failed"),
							indicator: "red",
							message: msg
						});
					}
				}
			});
		});
	}
});

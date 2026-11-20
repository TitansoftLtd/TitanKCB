frappe.ui.form.on("KCB Funds Transfer", {
	refresh(frm) {
		frm.disable_save();
		frm.add_custom_button(__("Check status"), () => frm.call("check_status"));
	},
});

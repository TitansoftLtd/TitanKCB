const KCB_SANDBOX = {
	token_url: "https://uat.buni.kcbgroup.com/token?grant_type=client_credentials",
	funds_transfer_url: "https://uat.buni.kcbgroup.com/fundstransfer/1.0.0/api/v1/transfer",
};

frappe.ui.form.on("KCB Settings", {
	environment(frm) {
		if (frm.doc.environment === "Sandbox (UAT)") {
			frm.set_value(KCB_SANDBOX);
		}
	},
	test_connection(frm) {
		frm.call("test_connection").then((r) => {
			frappe.msgprint({
				title: __("Test connection"),
				message: r.message,
				indicator: (r.message || "").startsWith("Success") ? "green" : "red",
			});
		});
	},
});

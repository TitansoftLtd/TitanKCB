"""Calls consuming apps' ``titan_kcb_funds_transfer_update`` hooks."""

from __future__ import annotations

import frappe

from titan_kcb.constants import HOOK_NAME


def dispatch_transfer_update(transfer_name: str) -> None:
	"""Background job: call every registered hook with the KCB Funds Transfer doc.

	An error in one consumer is logged and never stops the others.
	"""
	transfer = frappe.get_doc("KCB Funds Transfer", transfer_name)
	for method in frappe.get_hooks(HOOK_NAME) or []:
		try:
			frappe.get_attr(method)(transfer)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=f"titan_kcb hook failed: {method}",
				message=frappe.get_traceback(),
				reference_doctype="KCB Funds Transfer",
				reference_name=transfer_name,
			)

"""Applying a KCB result (callback or status check) to a KCB Funds Transfer."""

from __future__ import annotations

import frappe

from titan_kcb import constants as c


def apply_final_status(
	transfer, status: str, ft_reference: str | None, message: str | None, transaction_date
) -> bool:
	"""Set a final status on ``transfer`` and save. Returns True if the status changed.

	Does nothing (returns False) if the transfer is already final.
	"""
	if transfer.status in c.FINAL_STATUSES:
		return False
	transfer.status = status
	if ft_reference:
		transfer.ft_reference = ft_reference
	transfer.transaction_message = message
	if transaction_date:
		transfer.transaction_date = transaction_date
	transfer.save(ignore_permissions=True)
	return True


def enqueue_hook_dispatch(transfer_name: str) -> None:
	"""Notify consuming apps in a background job, after the current transaction commits."""
	frappe.enqueue(
		"titan_kcb.hook_dispatch.dispatch_transfer_update",
		queue="default",
		transfer_name=transfer_name,
		enqueue_after_commit=True,
	)

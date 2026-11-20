"""Receiving KCB's callbacks."""

from __future__ import annotations

import json
from typing import Any

import frappe
from werkzeug.wrappers import Response

from titan_kcb import callback_fields as cf
from titan_kcb import constants as c
from titan_kcb.processing import apply_final_status, enqueue_hook_dispatch
from titan_kcb.utils import to_masked_json


def _json(body: dict, status: int = 200) -> Response:
	return Response(json.dumps(body), status=status, mimetype="application/json")


def _ip_allowed() -> bool:
	"""Optional allow-list. TODO(verify): P3. Check KCB's spec for how callbacks are authenticated."""
	raw = frappe.db.get_single_value("KCB Settings", "callback_allowed_ips") or ""
	allowed = {ip.strip() for ip in raw.replace(",", "\n").splitlines() if ip.strip()}
	if not allowed:
		return True
	return (frappe.local.request_ip or "") in allowed


@frappe.whitelist(allow_guest=True, methods=["POST"])
def funds_transfer() -> Response:
	"""FT callback endpoint. Always answers HTTP 200 quickly; the work runs in a background job."""
	if not _ip_allowed():
		return _json({"statusCode": "1", "statusMessage": "Forbidden"}, 403)
	payload = frappe.request.get_json(silent=True)
	if not isinstance(payload, dict):
		frappe.log_error(title="KCB callback: invalid body", message=frappe.request.get_data(as_text=True)[:2000])
		return _json(c_ack())
	frappe.enqueue(
		"titan_kcb.api.callbacks.process_callback",
		queue="default",
		payload=payload,
		enqueue_after_commit=True,
	)
	return _json(c_ack())


def c_ack() -> dict:
	return dict(cf.CALLBACK_ACK)


def process_callback(payload: dict[str, Any]) -> str | None:
	"""Apply a callback to its KCB Funds Transfer. Idempotent. Returns the new status or None."""
	fields = cf.CALLBACK_FIELDS
	reference = payload.get(fields["transaction_reference"])
	name = frappe.db.get_value("KCB Funds Transfer", {"transaction_reference": reference}) if reference else None
	if not name:
		frappe.log_error(
			title="KCB callback: unknown transaction reference",
			message=to_masked_json(payload),
		)
		return None

	transfer = frappe.get_doc("KCB Funds Transfer", name, for_update=True)
	transfer.callback_count = (transfer.callback_count or 0) + 1
	transfer.callback_payload = to_masked_json(payload)

	new_status = cf.CALLBACK_STATUS_MAP.get(str(payload.get(fields["status"]) or "").upper())
	changed = False
	if transfer.status in c.FINAL_STATUSES:
		transfer.save(ignore_permissions=True)  # count + store only
	elif not new_status:
		transfer.save(ignore_permissions=True)
		frappe.log_error(title="KCB callback: unknown transactionStatus", message=to_masked_json(payload))
	else:
		changed = apply_final_status(
			transfer,
			new_status,
			payload.get(fields["ft_reference"]),
			payload.get(fields["message"]),
			_parse_date(payload.get(fields["date"])),
		)
	if changed:
		enqueue_hook_dispatch(transfer.name)
	frappe.db.commit()
	return transfer.status


def _parse_date(value):
	if not value:
		return None
	try:
		return frappe.utils.get_datetime(value)
	except Exception:
		return None

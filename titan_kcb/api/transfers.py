"""Public Python API of titan_kcb. Other apps import from here, never from the internals."""

from __future__ import annotations

import json
import secrets
import string
from typing import Any

import frappe

from titan_kcb import callback_fields as cf
from titan_kcb import constants as c
from titan_kcb.client import KCBConnectionError, get_settings, post_funds_transfer
from titan_kcb.utils import normalize_msisdn, to_masked_json

__all__ = ["check_status", "generate_transaction_reference", "initiate_transfer"]

_REF_ALPHABET = string.ascii_uppercase + string.digits


def generate_transaction_reference() -> str:
	"""A unique 12-character reference (uppercase letters and digits)."""
	for _ in range(10):
		ref = "".join(secrets.choice(_REF_ALPHABET) for _ in range(c.MAX_LENGTHS["transaction_reference"]))
		if not frappe.db.exists("KCB Funds Transfer", {"transaction_reference": ref}):
			return ref
	frappe.throw(frappe._("Could not generate a unique KCB transaction reference."))


def _check_length(field: str, value: str, limit: int | None = None) -> None:
	limit = limit or c.MAX_LENGTHS[field]
	if len(value) > limit:
		frappe.throw(
			frappe._("{0} is {1} characters; KCB allows at most {2}.").format(
				field.replace("_", " ").title(), len(value), limit
			),
			frappe.ValidationError,
		)


def _require(field: str, value: Any) -> None:
	if value in (None, ""):
		frappe.throw(frappe._("{0} is required.").format(field.replace("_", " ").title()), frappe.ValidationError)


def build_request_payload(transfer) -> dict[str, Any]:
	"""KCB request body (field names from KCB's OpenAPI definition [CONFIRMED])."""
	payload: dict[str, Any] = {
		"companyCode": transfer.company_code,
		"transactionType": transfer.transaction_type,
		"debitAccountNumber": transfer.debit_account_number,
		"creditAccountNumber": transfer.credit_account_number,
		"debitAmount": float(transfer.amount),
		"paymentDetails": transfer.payment_details,
		"transactionReference": transfer.transaction_reference,
		"currency": transfer.currency,
		"beneficiaryDetails": transfer.beneficiary_details,
	}
	if transfer.beneficiary_bank_code:
		payload["beneficiaryBankCode"] = transfer.beneficiary_bank_code
	return payload


def initiate_transfer(
	transaction_type: str,
	credit_account_number: str,
	amount: float,
	beneficiary_details: str,
	payment_details: str,
	beneficiary_bank_code: str | None = None,
	debit_account_number: str | None = None,
	currency: str = "KES",
	transaction_reference: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""Send a funds transfer to KCB and return the name of the KCB Funds Transfer log.

	Validates against KCB's limits (``frappe.ValidationError``), creates the log, sends the request
	and records the synchronous result: ``Accepted`` if ``header.statusCode == "0"``, otherwise
	``Rejected`` (the reason is in ``status_description``). The final outcome arrives later via the
	callback and is announced through the ``titan_kcb_funds_transfer_update`` hook.

	The log is committed before the HTTP call, so it survives a failure. If KCB cannot be reached
	(timeout, HTTP 5xx) the log stays ``Queued`` and ``KCBConnectionError`` is raised: the outcome
	is unknown, so do not blindly retry.
	"""
	settings = get_settings()
	if not settings.enabled:
		frappe.throw(frappe._("KCB integration is disabled in KCB Settings."), frappe.ValidationError)

	transaction_type = (transaction_type or "").strip().upper()
	if transaction_type not in c.TRANSACTION_TYPES:
		frappe.throw(
			frappe._("Unknown transaction type {0}. Use one of: {1}.").format(
				transaction_type, ", ".join(c.TRANSACTION_TYPES)
			),
			frappe.ValidationError,
		)
	is_mpesa = transaction_type == c.MPESA_TRANSACTION_TYPE
	if is_mpesa:
		credit_account_number = normalize_msisdn(credit_account_number)
		beneficiary_bank_code = beneficiary_bank_code or c.MPESA_BANK_CODE
	credit_account_number = (credit_account_number or "").strip()
	debit_account_number = (debit_account_number or settings.default_debit_account or "").strip()
	company_code = (settings.company_code or "").strip()
	currency = (currency or "").strip().upper()

	try:
		amount = float(amount)
	except (TypeError, ValueError):
		frappe.throw(frappe._("Amount must be a number."), frappe.ValidationError)
	if amount <= 0:
		frappe.throw(frappe._("Amount must be greater than zero."), frappe.ValidationError)

	for field, value in {
		"company_code": company_code,
		"debit_account_number": debit_account_number,
		"credit_account_number": credit_account_number,
		"beneficiary_details": beneficiary_details,
		"payment_details": payment_details,
		"currency": currency,
	}.items():
		_require(field, value)
		if field != "credit_account_number":
			_check_length(field, value)
	_check_length(
		"credit_account_number",
		credit_account_number,
		c.MPESA_CREDIT_ACCOUNT_MAX_LENGTH if is_mpesa else None,
	)
	if is_mpesa and len(credit_account_number) > c.MAX_LENGTHS["credit_account_number"]:
		# TODO(verify): P4. KCB's spec caps this field at 10 characters.
		frappe.logger("titan_kcb").warning(
			"creditAccountNumber has %s characters; KCB's spec says max %s (unresolved for M-PESA).",
			len(credit_account_number),
			c.MAX_LENGTHS["credit_account_number"],
		)
	if beneficiary_bank_code:
		_check_length("beneficiary_bank_code", beneficiary_bank_code)
	if is_mpesa and beneficiary_bank_code != c.MPESA_BANK_CODE:
		frappe.throw(
			frappe._("beneficiary_bank_code must be {0} for M-PESA transfers.").format(c.MPESA_BANK_CODE),
			frappe.ValidationError,
		)

	if transaction_reference:
		_check_length("transaction_reference", transaction_reference)
		if frappe.db.exists("KCB Funds Transfer", {"transaction_reference": transaction_reference}):
			frappe.throw(
				frappe._("Transaction reference {0} was already used.").format(transaction_reference),
				frappe.ValidationError,
			)
	else:
		transaction_reference = generate_transaction_reference()

	transfer = frappe.get_doc(
		{
			"doctype": "KCB Funds Transfer",
			"transaction_type": transaction_type,
			"company_code": company_code,
			"debit_account_number": debit_account_number,
			"credit_account_number": credit_account_number,
			"beneficiary_bank_code": beneficiary_bank_code,
			"beneficiary_details": beneficiary_details,
			"payment_details": payment_details,
			"currency": currency,
			"amount": amount,
			"transaction_reference": transaction_reference,
			"status": c.STATUS_QUEUED,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	payload = build_request_payload(transfer)
	transfer.request_payload = to_masked_json(payload)
	transfer.insert(ignore_permissions=True)
	frappe.db.commit()  # keep the log even if the caller rolls back after a failure

	try:
		result = post_funds_transfer(payload)
	except KCBConnectionError as e:
		transfer.db_set("status_description", str(e)[:140], commit=True)
		raise

	header = (result.body or {}).get(cf.RESPONSE_HEADER)
	transfer.response_payload = to_masked_json(result.body if result.body is not None else {"raw": result.text})
	if isinstance(header, dict) and cf.RESPONSE_FIELDS["status_code"] in header:
		f = cf.RESPONSE_FIELDS
		transfer.message_id = header.get(f["message_id"])
		transfer.retrieval_ref_number = header.get(f["retrieval_ref_number"])
		transfer.merchant_id = header.get(f["merchant_id"])
		transfer.status_description = (
			header.get(f["status_description"]) or header.get(f["status_message"]) or ""
		)[:140]
		ok = str(header.get(f["status_code"])) == c.SYNC_SUCCESS_CODE
		transfer.status = c.STATUS_ACCEPTED if ok else c.STATUS_REJECTED
	elif 400 <= result.status_code < 500:
		# Gateway-level refusal (e.g. bad credentials): KCB definitely did not accept it.
		transfer.status = c.STATUS_REJECTED
		transfer.status_description = f"HTTP {result.status_code}: {result.text}"[:140]
	else:
		transfer.status_description = f"Unusable KCB response (HTTP {result.status_code})"
		transfer.save(ignore_permissions=True)
		frappe.db.commit()
		raise KCBConnectionError(transfer.status_description)
	transfer.save(ignore_permissions=True)
	frappe.db.commit()
	return transfer.name


def check_status(transfer_name: str) -> None:
	"""Query KCB for the status of a transfer.

	TODO(verify): P5. KCB's transaction status query API is not documented in the material we
	have. Implement it here (and feed the result through ``processing.apply_final_status``).
	"""
	raise NotImplementedError(
		"KCB's transaction status query API is not known yet (TODO(verify) P5). "
		"Ask KCB for the endpoint, then implement titan_kcb.api.transfers.check_status."
	)

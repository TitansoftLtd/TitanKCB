"""Helpers usable by any consuming app: MSISDN handling and secret masking."""

from __future__ import annotations

import json
import re
from typing import Any

import frappe

_MSISDN_RE = re.compile(r"^254[17]\d{8}$")
_SECRET_KEY_RE = re.compile(r"secret|password|token|authorization|api_?key|consumer_?key", re.I)
MASK = "********"


def normalize_msisdn(number: str) -> str:
	"""Normalize a Kenyan mobile number to ``254XXXXXXXXX``.

	Accepts ``07XXXXXXXX``, ``01XXXXXXXX``, ``7XXXXXXXX``, ``+2547XXXXXXXX`` and ``2547XXXXXXXX``
	(spaces, dashes and brackets are ignored). Raises ``frappe.ValidationError`` if invalid.
	"""
	digits = re.sub(r"[\s\-()]", "", str(number or ""))
	if digits.startswith("+"):
		digits = digits[1:]
	if re.fullmatch(r"0[17]\d{8}", digits):
		digits = "254" + digits[1:]
	elif re.fullmatch(r"[17]\d{8}", digits):
		digits = "254" + digits
	if not _MSISDN_RE.match(digits):
		frappe.throw(
			frappe._("Invalid M-PESA number {0}. Use 07XXXXXXXX, 01XXXXXXXX, +254XXXXXXXXX or 254XXXXXXXXX.").format(
				frappe.bold(number)
			),
			frappe.ValidationError,
		)
	return digits


def is_valid_msisdn(number: str) -> bool:
	"""True if ``number`` can be normalized to a valid ``254XXXXXXXXX`` number."""
	try:
		normalize_msisdn(number)
	except frappe.ValidationError:
		return False
	return True


def mask_secrets(data: Any) -> Any:
	"""Return a copy of ``data`` with values of secret-looking keys replaced by ``********``."""
	if isinstance(data, dict):
		return {k: (MASK if _SECRET_KEY_RE.search(str(k)) else mask_secrets(v)) for k, v in data.items()}
	if isinstance(data, list):
		return [mask_secrets(v) for v in data]
	return data


def to_masked_json(data: Any) -> str:
	return json.dumps(mask_secrets(data), indent=1, default=str)

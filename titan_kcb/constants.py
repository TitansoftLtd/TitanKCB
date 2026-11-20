"""Constants for the KCB Buni Funds Transfer API.

Anything not confirmed by KCB's own documents is marked ``TODO(verify)`` and is listed in the
README under "Open questions for KCB".
"""

from __future__ import annotations

# KCB's Postman collection [CONFIRMED]
SANDBOX_TOKEN_URL = "https://uat.buni.kcbgroup.com/token?grant_type=client_credentials"
SANDBOX_FUNDS_TRANSFER_URL = "https://uat.buni.kcbgroup.com/fundstransfer/1.0.0/api/v1/transfer"
# Production host is not published. TODO(verify): enter the URLs KCB supplies on onboarding.

ENV_SANDBOX = "Sandbox (UAT)"
ENV_PRODUCTION = "Production"
ENV_CUSTOM = "Custom"

# TODO(verify): the codes are from third-party write-ups; the portal confirms the capabilities only.
TRANSACTION_TYPES: dict[str, str] = {
	"IF": "Internal funds transfer (KCB account to KCB account)",
	"RT": "RTGS (interbank, high value)",
	"EF": "EFT (interbank)",
	"PL": "Pesalink (interbank instant)",
	"MO": "KCB account to M-PESA wallet",
}
MPESA_TRANSACTION_TYPE = "MO"
MPESA_BANK_CODE = "MPESA"  # TODO(verify): P4

# Max lengths from KCB's OpenAPI definition [CONFIRMED]
MAX_LENGTHS: dict[str, int] = {
	"company_code": 15,
	"transaction_type": 2,
	"debit_account_number": 10,
	"credit_account_number": 10,
	"payment_details": 35,
	"transaction_reference": 12,
	"currency": 3,
	"beneficiary_details": 35,
	"beneficiary_bank_code": 20,
}
# The spec caps creditAccountNumber at 10, but M-PESA numbers have 12 digits (254XXXXXXXXX).
# Unresolved with KCB. We allow 12 for MO only and log a warning. TODO(verify): P4.
MPESA_CREDIT_ACCOUNT_MAX_LENGTH = 12

# KCB Funds Transfer statuses
STATUS_QUEUED = "Queued"
STATUS_SUBMITTED = "Submitted"
STATUS_ACCEPTED = "Accepted"
STATUS_REJECTED = "Rejected"
STATUS_SUCCESS = "Success"
STATUS_FAILED = "Failed"
# Once final, later callbacks are counted and stored but never change the status.
FINAL_STATUSES = frozenset({STATUS_SUCCESS, STATUS_FAILED, STATUS_REJECTED})

# Synchronous response: header.statusCode "0" = submitted successfully (not yet paid) [CONFIRMED]
SYNC_SUCCESS_CODE = "0"

HOOK_NAME = "titan_kcb_funds_transfer_update"
TOKEN_CACHE_KEY = "titan_kcb:access_token"
TOKEN_EXPIRY_MARGIN_SECONDS = 60

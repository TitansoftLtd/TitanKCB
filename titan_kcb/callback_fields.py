"""Field names for KCB's responses and callbacks, kept in ONE place.

TODO(verify): P3. The callback layout below comes from third-party write-ups, not KCB's spec.
Change the names here once the official Callback specification is confirmed.
"""

from __future__ import annotations

# Synchronous response [CONFIRMED]: {"header": {...}}
RESPONSE_HEADER = "header"
RESPONSE_FIELDS = {
	"message_id": "messageID",
	"status_code": "statusCode",
	"status_message": "statusMessage",
	"status_description": "statusDescription",
	"retrieval_ref_number": "retrievalRefNumber",
	"merchant_id": "merchantID",
}

# FT callback [UNVERIFIED]
CALLBACK_FIELDS = {
	"transaction_reference": "transactionReference",
	"ft_reference": "ftReference",
	"status": "transactionStatus",
	"message": "transactionMessage",
	"date": "transactionDate",
	"amount": "amount",
	"merchant_id": "merchantId",
}
# transactionStatus value -> KCB Funds Transfer status
CALLBACK_STATUS_MAP = {"SUCCESS": "Success", "FAILED": "Failed"}

# TODO(verify): the acknowledgement KCB expects is unknown.
CALLBACK_ACK = {"statusCode": "0", "statusMessage": "Received"}

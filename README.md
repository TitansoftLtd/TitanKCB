# titan_kcb: KCB Buni Funds Transfer connector for Frappe

A reusable Frappe app that speaks KCB Buni's **Funds Transfer API**: OAuth2 token handling,
funds-transfer requests, the FT callback endpoint, a transfer log, and a hook that tells your own
apps what happened. It depends on `frappe` only. It has no ERPNext, supplier or invoice knowledge.

License: GPL-3.0 (see `license.txt`). Publisher: Titansoft Ltd.

## Install

```bash
bench get-app <repo-url> --branch version-16
bench --site <site> install-app titan_kcb
bench --site <site> migrate
```

## Configure (KCB Settings)

| Field | Notes |
|---|---|
| Enabled | Must be ticked or `initiate_transfer` refuses. |
| Environment | **Sandbox (UAT)** pre-fills `https://uat.buni.kcbgroup.com/token?grant_type=client_credentials` and `…/fundstransfer/1.0.0/api/v1/transfer`. **Production** and **Custom** leave the URLs editable (the production host is not published; use what KCB gives you). |
| Consumer key / secret | From your Buni application. The secret is a Password field and is never logged. |
| Company code | e.g. `KE0010001` (sandbox sample). |
| Default debit account | Used when a request names none. |
| Request timeout | Seconds, default 30. |
| Callback URL | Read-only. Copy it and register it with KCB. |
| Callback allowed IPs | Optional allow-list (one per line or comma separated). Empty = accept any. |

**Test connection** fetches a token and reports success or failure (the token itself is never shown).

### Onboarding with KCB
- **Sandbox:** send KCB your Buni username (for whitelisting) and your FT callback URL. KCB then supplies test account numbers.
- **Production:** KCB account number, signed Indemnity Letter and FT Request Letter. Support: buni@kcbgroup.com.
- The callback URL is **registered with KCB, not sent per request**. For the real sandbox it must be public HTTPS.

## Public Python API

Import from `titan_kcb.api.transfers` and `titan_kcb.utils`. Everything else is internal.

### `initiate_transfer(transaction_type, credit_account_number, amount, beneficiary_details, payment_details, beneficiary_bank_code=None, debit_account_number=None, currency="KES", transaction_reference=None, reference_doctype=None, reference_name=None) -> str`
Validates, creates a **KCB Funds Transfer**, sends the request and returns the log's name.
- Raises `frappe.ValidationError` for bad input (lengths per KCB's spec, unknown type, amount <= 0, duplicate reference, integration disabled). Nothing is sent and nothing is stored.
- `transaction_type`: `IF`, `RT`, `EF`, `PL`, `MO` (M-PESA). For `MO` the number is normalized and `beneficiary_bank_code` defaults to `MPESA`.
- `transaction_reference`: auto-generated (12 chars, unique) if omitted.
- `reference_doctype` / `reference_name`: link any document of your app to the transfer.
- Result: status **Accepted** if KCB answers `header.statusCode == "0"` (submitted, **not** paid), otherwise **Rejected** (reason in `status_description`, no exception).
- If KCB cannot be reached (timeout, HTTP 5xx) the log stays **Queued** and `titan_kcb.client.KCBConnectionError` is raised. The outcome is unknown, so check KCB before retrying.
- The log is committed before the HTTP call.

### `generate_transaction_reference() -> str`
A unique 12-character uppercase reference.

### `check_status(transfer_name)`
Stub raising `NotImplementedError` until KCB's status-query API is known (see open questions). The *Check status* button on the transfer calls it.

### `titan_kcb.utils`
- `normalize_msisdn(number) -> str`: `07…`, `01…`, `+254…`, `254…` become `254XXXXXXXXX`; raises `frappe.ValidationError` if invalid.
- `is_valid_msisdn(number) -> bool`
- `mask_secrets(data)` / `to_masked_json(data)`: masks secret-looking keys (used for stored payloads).

## The hook for consuming apps

```python
# your app's hooks.py
titan_kcb_funds_transfer_update = ["my_app.kcb.on_funds_transfer_update"]
```
```python
def on_funds_transfer_update(transfer):   # transfer is the KCB Funds Transfer doc
    if transfer.reference_doctype != "My Doctype":
        return
    if transfer.status == "Success": ...
```
- Called after a callback (or status check) **changes** a transfer to `Success` / `Failed`, in a background job after the commit.
- It runs as **Guest**/system context (the callback is unauthenticated). Elevate yourself if your code needs permissions.
- An exception in one consumer is logged with `frappe.log_error` and does not stop the others.
- Duplicate callbacks do not fire the hook again, but your handler should still be idempotent.

## Callback endpoint

`POST /api/method/titan_kcb.api.callbacks.funds_transfer` (guest allowed).
- Returns HTTP 200 immediately with `{"statusCode":"0","statusMessage":"Received"}`; processing is in a background job.
- Unknown `transactionReference`: logged with `frappe.log_error`, still 200.
- Idempotent: for a transfer already `Success`/`Failed`/`Rejected` the callback is counted and its payload stored, but the status is unchanged and hooks are not fired again.
- Field names live in one file, `titan_kcb/callback_fields.py`.
- Authentication: only the optional IP allow-list for now (see open questions).

## Tests
```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app titan_kcb
```

## Open questions for KCB (all marked `TODO(verify)` in the code)
1. **Callback payload**: exact field names and layout. Current shape is from third-party write-ups. (`callback_fields.py`)
2. **Callback acknowledgement**: what body/status KCB expects. We return `{"statusCode":"0","statusMessage":"Received"}`.
3. **Callback authentication**: IP list, signature, none?
4. **M-PESA transfer**: is it `transactionType "MO"` with `beneficiaryBankCode "MPESA"`? The Postman collection only shows `IF`.
5. **`creditAccountNumber` length**: the spec caps it at 10 but M-PESA numbers have 12 digits. We allow 12 for `MO` only and log a warning.
6. **Transaction type codes** `IF/RT/EF/PL/MO` (only `IF` is seen in KCB's Postman collection).
7. **Status query endpoint** for a transfer (needed by `check_status`).
8. **Production hosts** for the token and funds-transfer URLs.
9. Whether HTTP status for business errors is always 200 (we always read `header.statusCode`).

KCB's IPN API (incoming credits) is a separate product and is not implemented. The layout leaves room for a module.

## Confirmed from KCB's Postman collection
Token `POST https://uat.buni.kcbgroup.com/token?grant_type=client_credentials` (Basic auth); funds transfer
`POST https://uat.buni.kcbgroup.com/fundstransfer/1.0.0/api/v1/transfer` (Bearer, JSON) with the ten request fields.
The (redacted) collection is in `docs/kcb/`.

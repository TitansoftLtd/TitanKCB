# Changelog

## 0.1.0 (unreleased)
- KCB Settings (sandbox/production/custom, test connection, callback URL, optional IP allow-list).
- KCB Funds Transfer log DocType (read-only).
- Token client with Redis caching and refresh-on-401.
- Public API: `initiate_transfer`, `generate_transaction_reference`, `check_status` (stub), MSISDN helpers.
- FT callback endpoint (idempotent, background processing) and `titan_kcb_funds_transfer_update` hook.

"""HTTP client for KCB Buni: OAuth2 token handling and the Funds Transfer call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
import requests

from titan_kcb.constants import TOKEN_CACHE_KEY, TOKEN_EXPIRY_MARGIN_SECONDS


class KCBConnectionError(frappe.ValidationError):
	"""KCB could not be reached or gave an unusable answer."""


@dataclass
class KCBHttpResult:
	status_code: int
	body: dict[str, Any] | None
	text: str


def get_settings():
	return frappe.get_cached_doc("KCB Settings")


def clear_token_cache() -> None:
	frappe.cache.delete_value(TOKEN_CACHE_KEY)


def get_token(force_refresh: bool = False) -> str:
	"""Return a valid access token, fetching and caching one if needed.

	Cached in Redis until ``TOKEN_EXPIRY_MARGIN_SECONDS`` before ``expires_in`` runs out.
	"""
	if not force_refresh:
		cached = frappe.cache.get_value(TOKEN_CACHE_KEY)
		if cached:
			return cached
	token, _ = _fetch_token()
	return token


def _fetch_token() -> tuple[str, int]:
	settings = get_settings()
	if not settings.token_url or not settings.consumer_key:
		frappe.throw(frappe._("KCB Settings: token URL and consumer key/secret are required."))
	data = None if "grant_type" in settings.token_url else {"grant_type": "client_credentials"}
	try:
		resp = requests.post(
			settings.token_url,
			auth=(settings.consumer_key, settings.get_password("consumer_secret") or ""),
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			data=data,
			timeout=settings.request_timeout_seconds or 30,
		)
	except requests.RequestException as e:
		raise KCBConnectionError(f"Could not reach KCB token endpoint: {e}") from e
	if resp.status_code != 200:
		raise KCBConnectionError(f"KCB token request failed (HTTP {resp.status_code}).")
	try:
		body = resp.json()
		token = body["access_token"]
	except (ValueError, KeyError) as e:
		raise KCBConnectionError("KCB token response had no access_token.") from e
	expires_in = int(body.get("expires_in") or 3600)
	frappe.cache.set_value(
		TOKEN_CACHE_KEY, token, expires_in_sec=max(expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, 1)
	)
	return token, expires_in


def test_token() -> int:
	"""Force a token fetch. Returns ``expires_in`` seconds. Never exposes the token."""
	clear_token_cache()
	return _fetch_token()[1]


def post_funds_transfer(payload: dict[str, Any]) -> KCBHttpResult:
	"""POST the funds transfer. On HTTP 401 clear the cached token, get a new one and retry once."""
	settings = get_settings()
	for attempt in (1, 2):
		token = get_token(force_refresh=attempt == 2)
		try:
			resp = requests.post(
				settings.funds_transfer_url,
				json=payload,
				headers={
					"Authorization": f"Bearer {token}",
					"accept": "application/json",
					"Content-Type": "application/json",
				},
				timeout=settings.request_timeout_seconds or 30,
			)
		except requests.RequestException as e:
			raise KCBConnectionError(f"Could not reach KCB funds transfer endpoint: {e}") from e
		if resp.status_code == 401 and attempt == 1:
			clear_token_cache()
			continue
		try:
			body = resp.json()
		except ValueError:
			body = None
		return KCBHttpResult(resp.status_code, body if isinstance(body, dict) else None, resp.text[:2000])
	raise AssertionError("unreachable")

import frappe
from frappe.model.document import Document

from titan_kcb import constants as c
from titan_kcb.client import clear_token_cache, test_token

CALLBACK_PATH = "/api/method/titan_kcb.api.callbacks.funds_transfer"


class KCBSettings(Document):
	def onload(self):
		self.callback_url = get_callback_url()

	def validate(self):
		if self.environment == c.ENV_SANDBOX:
			self.token_url = c.SANDBOX_TOKEN_URL
			self.funds_transfer_url = c.SANDBOX_FUNDS_TRANSFER_URL
		self.callback_url = get_callback_url()

	def on_update(self):
		clear_token_cache()  # credentials or URLs may have changed

	@frappe.whitelist()
	def test_connection(self) -> str:
		frappe.only_for("System Manager")
		try:
			expires_in = test_token()
		except frappe.ValidationError as e:
			return f"Failed: {e}"
		return f"Success: token obtained (valid for {expires_in} seconds)."


def get_callback_url() -> str:
	return frappe.utils.get_url().rstrip("/") + CALLBACK_PATH

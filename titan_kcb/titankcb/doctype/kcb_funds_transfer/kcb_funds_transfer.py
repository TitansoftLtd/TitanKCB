import frappe
from frappe.model.document import Document


class KCBFundsTransfer(Document):
	@frappe.whitelist()
	def check_status(self):
		"""Admin action: ask KCB for the current status (not implemented yet, see P5)."""
		frappe.only_for("System Manager")
		from titan_kcb.api.transfers import check_status

		try:
			check_status(self.name)
		except NotImplementedError as e:
			frappe.throw(str(e))

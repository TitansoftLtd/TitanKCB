import json
import pathlib
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from titan_kcb import client, hook_dispatch
from titan_kcb.api import callbacks, transfers
from titan_kcb.constants import HOOK_NAME, TOKEN_CACHE_KEY
from titan_kcb.utils import is_valid_msisdn, mask_secrets, normalize_msisdn

CALLS: list[str] = []


def good_hook(transfer):
	CALLS.append(f"good:{transfer.name}")


def bad_hook(transfer):
	CALLS.append("bad")
	raise RuntimeError("consumer exploded")


class FakeSettings(SimpleNamespace):
	def get_password(self, field):
		return "secret"


def fake_settings(**over):
	base = {
		"enabled": 1,
		"token_url": "https://kcb.test/token?grant_type=client_credentials",
		"funds_transfer_url": "https://kcb.test/transfer",
		"consumer_key": "key",
		"company_code": "KE0010001",
		"default_debit_account": "1234567890",
		"request_timeout_seconds": 5,
	}
	base.update(over)
	return FakeSettings(**base)


def resp(status=200, body=None, text=""):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = body
	if body is None:
		r.json.side_effect = ValueError
	r.text = text or json.dumps(body)
	return r


TOKEN_OK = {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 3600}
ACCEPTED = {"header": {"messageID": "m1", "statusCode": "0", "statusMessage": "Success",
	"statusDescription": "Success", "retrievalRefNumber": "FT22006670X0", "merchantID": "mer-1"}}


class KCBTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.cache.delete_value(TOKEN_CACHE_KEY)
		for target in (client, transfers):
			p = patch.object(target, "get_settings", lambda: fake_settings())
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self):
		frappe.db.delete("KCB Funds Transfer")
		frappe.db.commit()
		frappe.cache.delete_value(TOKEN_CACHE_KEY)

	def mo(self, **over):
		args = dict(
			transaction_type="MO",
			credit_account_number="0712345678",
			amount=25000,
			beneficiary_details="JOHN DOE",
			payment_details="Invoice payment",
		)
		args.update(over)
		return args

	def make_transfer(self, status="Accepted", ref="REFTEST00001"):
		return frappe.get_doc(
			{"doctype": "KCB Funds Transfer", "transaction_type": "MO", "transaction_reference": ref,
			 "status": status, "amount": 100, "credit_account_number": "254712345678"}
		).insert(ignore_permissions=True)


class TestMsisdn(IntegrationTestCase):
	def test_normalization(self):
		for raw in ("0712345678", "0112345678", "+254712345678", "254712345678", "712345678", "0712 345 678"):
			self.assertTrue(normalize_msisdn(raw).startswith("254"))
		self.assertEqual(normalize_msisdn("0712345678"), "254712345678")
		self.assertEqual(normalize_msisdn("+254112345678"), "254112345678")

	def test_invalid(self):
		for raw in ("", "12345", "0212345678", "25471234567", "abc"):
			self.assertFalse(is_valid_msisdn(raw), raw)
			with self.assertRaises(frappe.ValidationError):
				normalize_msisdn(raw)

	def test_mask_secrets(self):
		masked = mask_secrets({"a": 1, "consumer_secret": "x", "nested": {"access_token": "y", "ok": 2}})
		self.assertEqual(masked["consumer_secret"], "********")
		self.assertEqual(masked["nested"], {"access_token": "********", "ok": 2})


class TestInitiateTransfer(KCBTestCase):
	def run_transfer(self, post_responses=None, **over):
		post_responses = post_responses or [resp(200, TOKEN_OK), resp(200, ACCEPTED)]
		with patch.object(client.requests, "post", side_effect=post_responses) as post:
			name = transfers.initiate_transfer(**self.mo(**over))
		return name, post

	def test_payload_and_accepted(self):
		name, post = self.run_transfer()
		doc = frappe.get_doc("KCB Funds Transfer", name)
		self.assertEqual(doc.status, "Accepted")
		self.assertEqual(doc.retrieval_ref_number, "FT22006670X0")
		sent = post.call_args.kwargs["json"]
		self.assertEqual(sent["creditAccountNumber"], "254712345678")
		self.assertEqual(sent["beneficiaryBankCode"], "MPESA")
		self.assertEqual(sent["transactionType"], "MO")
		self.assertEqual(sent["debitAmount"], 25000.0)
		self.assertEqual(sent["debitAccountNumber"], "1234567890")
		self.assertLessEqual(len(sent["transactionReference"]), 12)
		self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer tok-1")
		self.assertNotIn("tok-1", doc.request_payload or "")

	def test_rejected_when_status_code_not_zero(self):
		bad = {"header": {"messageID": "m", "statusCode": "1", "statusMessage": "Failed", "statusDescription": "Bad account"}}
		name, _ = self.run_transfer([resp(200, TOKEN_OK), resp(200, bad)])
		doc = frappe.get_doc("KCB Funds Transfer", name)
		self.assertEqual((doc.status, doc.status_description), ("Rejected", "Bad account"))

	def test_length_limits(self):
		for over in ({"beneficiary_details": "x" * 36}, {"payment_details": "x" * 36},
			{"transaction_reference": "x" * 13}, {"currency": "KESS"}):
			with self.assertRaises(frappe.ValidationError, msg=str(over)):
				transfers.initiate_transfer(**self.mo(**over))
		with self.assertRaises(frappe.ValidationError):  # non-MO credit account max 10
			transfers.initiate_transfer(**self.mo(transaction_type="IF", credit_account_number="12345678901"))
		with self.assertRaises(frappe.ValidationError):
			transfers.initiate_transfer(**self.mo(amount=0))
		with self.assertRaises(frappe.ValidationError):
			transfers.initiate_transfer(**self.mo(credit_account_number="12345"))
		with self.assertRaises(frappe.ValidationError):
			transfers.initiate_transfer(**self.mo(transaction_type="XX"))
		self.assertEqual(frappe.db.count("KCB Funds Transfer"), 0)

	def test_mpesa_12_chars_allowed(self):
		name, _ = self.run_transfer(credit_account_number="254712345678")
		self.assertEqual(frappe.db.get_value("KCB Funds Transfer", name, "credit_account_number"), "254712345678")

	def test_reference_generation_and_uniqueness(self):
		refs = {transfers.generate_transaction_reference() for _ in range(50)}
		self.assertEqual(len(refs), 50)
		self.assertTrue(all(re.fullmatch(r"[A-Z0-9]{12}", r) for r in refs))
		self.run_transfer(transaction_reference="MYREF0000001")
		with self.assertRaises(frappe.ValidationError):
			self.run_transfer(transaction_reference="MYREF0000001")

	def test_disabled(self):
		with patch.object(transfers, "get_settings", lambda: fake_settings(enabled=0)):
			with self.assertRaises(frappe.ValidationError):
				transfers.initiate_transfer(**self.mo())

	def test_unreachable_keeps_queued_and_raises(self):
		with patch.object(client.requests, "post", side_effect=[resp(200, TOKEN_OK), resp(502, None, "bad gateway")]):
			with self.assertRaises(client.KCBConnectionError):
				transfers.initiate_transfer(**self.mo(transaction_reference="QREF00000001"))
		self.assertEqual(frappe.db.get_value("KCB Funds Transfer", {"transaction_reference": "QREF00000001"}, "status"), "Queued")

	def test_reference_link_stored(self):
		name, _ = self.run_transfer(reference_doctype="User", reference_name="Administrator")
		doc = frappe.get_doc("KCB Funds Transfer", name)
		self.assertEqual((doc.reference_doctype, doc.reference_name), ("User", "Administrator"))

	def test_check_status_not_implemented(self):
		with self.assertRaises(NotImplementedError):
			transfers.check_status("x")


class TestToken(KCBTestCase):
	def test_token_cached(self):
		with patch.object(client.requests, "post", return_value=resp(200, TOKEN_OK)) as post:
			self.assertEqual(client.get_token(), "tok-1")
			self.assertEqual(client.get_token(), "tok-1")
		self.assertEqual(post.call_count, 1)
		kwargs = post.call_args.kwargs
		self.assertEqual(kwargs["auth"], ("key", "secret"))
		self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")

	def test_refresh_on_401_and_retry_once(self):
		tok2 = dict(TOKEN_OK, access_token="tok-2")
		seq = [resp(200, TOKEN_OK), resp(401, {"fault": {"code": 900901}}), resp(200, tok2), resp(200, ACCEPTED)]
		with patch.object(client.requests, "post", side_effect=seq) as post:
			result = client.post_funds_transfer({"x": 1})
		self.assertEqual(result.status_code, 200)
		self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer tok-2")
		self.assertEqual(post.call_count, 4)

	def test_401_twice_is_returned_not_looped(self):
		seq = [resp(200, TOKEN_OK), resp(401, {"fault": {}}), resp(200, TOKEN_OK), resp(401, {"fault": {}})]
		with patch.object(client.requests, "post", side_effect=seq) as post:
			result = client.post_funds_transfer({})
		self.assertEqual(result.status_code, 401)
		self.assertEqual(post.call_count, 4)

	def test_token_failure(self):
		with patch.object(client.requests, "post", return_value=resp(401, {"error": "invalid_client"})):
			with self.assertRaises(client.KCBConnectionError):
				client.get_token()


def callback_payload(ref="REFTEST00001", status="SUCCESS", **over):
	p = {"ftReference": "FT2232598HFG", "transactionDate": "2026-11-21T10:15:00", "amount": 100,
		"transactionStatus": status, "transactionMessage": "Transaction processed successfully",
		"transactionReference": ref, "merchantId": "mer-1"}
	p.update(over)
	return p


class TestCallbacks(KCBTestCase):
	def test_success_callback_updates_and_dispatches(self):
		t = self.make_transfer()
		with patch("frappe.enqueue") as enq:
			self.assertEqual(callbacks.process_callback(callback_payload()), "Success")
		t.reload()
		self.assertEqual((t.status, t.ft_reference, t.callback_count), ("Success", "FT2232598HFG", 1))
		self.assertEqual(str(t.transaction_date)[:10], "2026-11-21")
		enq.assert_called_once()
		self.assertEqual(enq.call_args.args[0], "titan_kcb.hook_dispatch.dispatch_transfer_update")

	def test_failed_callback(self):
		t = self.make_transfer()
		with patch("frappe.enqueue"):
			callbacks.process_callback(callback_payload(status="FAILED", transactionMessage="M-PESA wallet not registered"))
		t.reload()
		self.assertEqual((t.status, t.transaction_message), ("Failed", "M-PESA wallet not registered"))

	def test_idempotent_duplicate(self):
		t = self.make_transfer()
		with patch("frappe.enqueue") as enq:
			callbacks.process_callback(callback_payload())
			callbacks.process_callback(callback_payload())
			callbacks.process_callback(callback_payload(status="FAILED"))  # late contradiction ignored
		t.reload()
		self.assertEqual((t.status, t.callback_count), ("Success", 3))
		self.assertEqual(enq.call_count, 1)  # hooks fired once

	def test_unknown_reference_logged_not_raised(self):
		with patch("frappe.log_error") as log:
			self.assertIsNone(callbacks.process_callback(callback_payload(ref="NOPE00000000")))
		log.assert_called_once()

	def test_endpoint_returns_200_and_enqueues(self):
		frappe.local.request = SimpleNamespace(get_json=lambda silent=True: callback_payload(), get_data=lambda **k: "")
		frappe.local.request_ip = "1.2.3.4"
		with patch("frappe.enqueue") as enq:
			response = callbacks.funds_transfer()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(json.loads(response.get_data())["statusCode"], "0")
		enq.assert_called_once()

	def test_endpoint_unknown_reference_still_200(self):
		frappe.local.request = SimpleNamespace(get_json=lambda silent=True: {"foo": "bar"}, get_data=lambda **k: "")
		frappe.local.request_ip = "1.2.3.4"
		with patch("frappe.enqueue"):
			self.assertEqual(callbacks.funds_transfer().status_code, 200)

	def test_ip_allow_list(self):
		frappe.local.request = SimpleNamespace(get_json=lambda silent=True: callback_payload(), get_data=lambda **k: "")
		frappe.local.request_ip = "9.9.9.9"
		with patch.object(callbacks.frappe.db, "get_single_value", return_value="1.1.1.1, 2.2.2.2"), patch("frappe.enqueue") as enq:
			self.assertEqual(callbacks.funds_transfer().status_code, 403)
		enq.assert_not_called()


class TestHookDispatch(KCBTestCase):
	def test_failing_consumer_does_not_stop_others(self):
		t = self.make_transfer(status="Success")
		CALLS.clear()
		real = frappe.get_hooks
		hooks = ["titan_kcb.tests.test_titan_kcb.bad_hook", "titan_kcb.tests.test_titan_kcb.good_hook"]
		with patch("frappe.get_hooks", lambda name=None, *a, **k: hooks if name == HOOK_NAME else real(name, *a, **k)), \
			patch("frappe.log_error") as log:
			hook_dispatch.dispatch_transfer_update(t.name)
		self.assertEqual(CALLS, ["bad", f"good:{t.name}"])
		log.assert_called_once()


class TestImportBoundary(IntegrationTestCase):
	FORBIDDEN = re.compile(r"^\s*(import|from)\s+(erpnext|titan_pay|titan_kcb_mock_server)\b", re.M)

	def test_no_forbidden_imports(self):
		root = pathlib.Path(__file__).resolve().parents[1]
		offenders = [str(p) for p in root.rglob("*.py") if "tests" not in p.parts and self.FORBIDDEN.search(p.read_text())]
		self.assertEqual(offenders, [])

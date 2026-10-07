import frappe
from frappe.utils.password import get_decrypted_password

from lift_log.api import auth, today
from lift_log.permissions import NOT_SET_UP
from lift_log.tests.helpers import PASSWORD, USER_A, USER_NO_ROLE, LiftLogTestCase


class TestAuth(LiftLogTestCase):
	def test_sign_in_returns_token_and_profile_flag(self):
		frappe.set_user("Guest")
		out = auth.sign_in(USER_A, PASSWORD)
		self.assertEqual(out["user"], USER_A)
		self.assertTrue(out["api_key"])
		self.assertEqual(get_decrypted_password("User", USER_A, "api_secret"), out["api_secret"])
		self.assertFalse(out["has_profile"])

	def test_sign_in_again_rotates_secret_keeps_key(self):
		frappe.set_user("Guest")
		first = auth.sign_in(USER_A, PASSWORD)
		second = auth.sign_in(USER_A, PASSWORD)
		self.assertEqual(first["api_key"], second["api_key"])
		self.assertNotEqual(first["api_secret"], second["api_secret"])

	def test_has_profile_after_setup(self):
		self.make_profile()
		frappe.set_user("Guest")
		self.assertTrue(auth.sign_in(USER_A, PASSWORD)["has_profile"])

	def test_wrong_password_is_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			auth.sign_in(USER_A, "not-the-password")

	def test_user_without_role_gets_role_message(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			auth.sign_in(USER_NO_ROLE, PASSWORD)
		self.assertIn(NOT_SET_UP, str(frappe.local.message_log))

	def test_sign_out_invalidates_secret(self):
		frappe.set_user("Guest")
		secret = auth.sign_in(USER_A, PASSWORD)["api_secret"]
		frappe.set_user(USER_A)
		self.assertEqual(auth.sign_out(), {"ok": True})
		self.assertNotEqual(get_decrypted_password("User", USER_A, "api_secret"), secret)

	def test_guest_and_role_less_users_cannot_call_endpoints(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			today.get("2026-10-07")
		frappe.set_user(USER_NO_ROLE)
		with self.assertRaises(frappe.PermissionError):
			today.get("2026-10-07")

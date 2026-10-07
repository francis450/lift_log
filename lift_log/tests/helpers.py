"""Shared fixtures for lift_log tests. Not a test module itself."""

import frappe
from frappe.tests.utils import FrappeTestCase

from lift_log.permissions import ROLE
from lift_log.setup.seed import load

USER_A = "ll-test-a@example.com"
USER_B = "ll-test-b@example.com"
USER_NO_ROLE = "ll-test-norole@example.com"
PASSWORD = "Lift-Log-Test-Pass-9"

USER_DOCTYPES = ("LL Workout Session", "LL Food Day", "LL Check In", "LL Weekly Review", "LL Profile")

# The 6 Oct 2026 session from the web-log export (docs/06).
SESSION_6_OCT = {
	"session_date": "2026-10-06",
	"week": 1,
	"routine_key": "lower",
	"routine_name": "Lower + Walk",
	"status": "done",
	"started_at": "2026-10-06T15:02:00Z",
	"finished_at": "2026-10-06T16:14:39.133Z",
	"note": "Tired",
	"client_updated_at": "2026-10-06T16:14:39.133Z",
	"sets": [
		{"exercise": ex, "set_no": i + 1, "kg": kg, "amount": amt, "effort": "", "done": True}
		for ex, rows in (
			("Barbell back squat", ((40, 8), (40, 7), (40, 7))),
			("Barbell Romanian deadlift", ((30, 10), (40, 10), (40, 10))),
			("Hip thrust", ((50, 10), (50, 8), (50, 8))),
			("Standing calf raise", ((40, 10), (40, 10), (40, 10))),
		)
		for i, (kg, amt) in enumerate(rows)
	],
}

# The 6 Oct 2026 food day from the export: 6 entries, 1,645 kcal, 125 g protein.
FOOD_6_OCT = {
	"food_date": "2026-10-06",
	"client_updated_at": "2026-10-06T16:22:25.766Z",
	"entries": [
		{"client_id": cid, "meal": meal, "food_name": n, "portion": portion, "qty": qty, "kcal_per_portion": k, "protein_per_portion": p, "source": "migrated"}
		for cid, meal, n, portion, qty, k, p in (
			("muwvrnngznij", "lunch", "Beef stew", "fist-size meat (~100 g)", 1, 250, 25),
			("muwvtuyasq3c", "breakfast", "Mandazi", "1", 1.5, 250, 4),
			("muwvzxs9skp7", "dinner", "Grilled chicken breast (skinless)", "250 g", 1, 410, 77),
			("muwvzxs9smw0", "dinner", "Ugali", "2 cups (~300 g)", 1, 440, 8),
			("muwvzxs9rxgp", "dinner", "Sukuma wiki", "1 cup cooked", 1, 100, 3),
			("muwvzxs9sgnc", "dinner", "Boiled egg", "1 egg", 1, 70, 6),
		)
	],
}


def make_user(email: str, with_role: bool = True) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"new_password": PASSWORD,
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	has_role = ROLE in [r.role for r in user.roles]
	if with_role and not has_role:
		user.add_roles(ROLE)
	elif not with_role and has_role:
		user.remove_roles(ROLE)
	return email


def clear_user_data(user: str):
	for doctype in USER_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"user": user}, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	for name in frappe.get_all("LL Food Item", filters={"is_seed": 0, "user": user}, pluck="name"):
		frappe.delete_doc("LL Food Item", name, force=True, ignore_permissions=True)


class LiftLogTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		load()
		make_user(USER_A)
		make_user(USER_B)
		make_user(USER_NO_ROLE, with_role=False)

	def setUp(self):
		frappe.set_user("Administrator")
		for user in (USER_A, USER_B):
			clear_user_data(user)
		self.reset_response()

	def tearDown(self):
		frappe.set_user("Administrator")

	def reset_response(self):
		frappe.local.response = frappe._dict()
		frappe.local.message_log = []
		# Set by real requests; the login attempt tracker keys on it.
		frappe.local.request_ip = "127.0.0.1"

	def status_code(self):
		return frappe.local.response.get("http_status_code")

	def make_profile(self, user: str = USER_A, **values) -> dict:
		from lift_log.api import profile

		frappe.set_user(user)
		return profile.save(**{"weight_kg": 72, "age": 25, **values})

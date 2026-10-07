import json
import tempfile
from pathlib import Path

import frappe

from lift_log.api import food, sessions, today
from lift_log.setup.migrate_web_log import migrate
from lift_log.tests.helpers import USER_A, LiftLogTestCase

# The shape of data/export (7 Oct 2026), trimmed to what the mapping uses.
SESSION = {
	"date": "2026-10-06",
	"note": "Tired",
	"routine": "Lower + Walk",
	"savedAt": "2026-10-06T16:14:39.133Z",
	"week": 1,
	"sets": {
		"Barbell Romanian deadlift": [{"amt": 10, "kg": 30}, {"amt": 10, "kg": 40}, {"amt": 10, "kg": 40}],
		"Barbell back squat": [{"amt": 8, "kg": 40}, {"amt": 7, "kg": 40}, {"amt": 7, "kg": 40}],
		"Hip thrust": [{"amt": 10, "kg": 50}, {"amt": 8, "kg": 50}, {"amt": 8, "kg": 50}],
		"Standing calf raise": [{"amt": 10, "kg": 40}, {"amt": 10, "kg": 40}, {"amt": 10, "kg": 40}],
	},
}
MEALS_6 = {
	"date": "2026-10-06",
	"savedAt": "2026-10-06T16:22:25.766Z",
	"items": [
		{"id": "muwvrnngznij", "k": 250, "meal": "Lunch", "n": "Beef stew", "p": 25, "portion": "fist-size meat (~100 g)", "qty": 1, "src": "list"},
		{"id": "muwvtuyasq3c", "k": 250, "meal": "Breakfast", "n": "Mandazi", "p": 4, "portion": "1", "qty": 1.5, "src": "list"},
		{"id": "muwvzxs9skp7", "k": 410, "meal": "Dinner", "n": "Grilled chicken breast (skinless)", "p": 77, "portion": "250 g", "qty": 1, "src": "suggestion"},
		{"id": "muwvzxs9smw0", "k": 440, "meal": "Dinner", "n": "Ugali", "p": 8, "portion": "2 cups (~300 g)", "qty": 1, "src": "suggestion"},
		{"id": "muwvzxs9rxgp", "k": 100, "meal": "Dinner", "n": "Sukuma wiki", "p": 3, "portion": "1 cup cooked", "qty": 1, "src": "suggestion"},
		{"id": "muwvzxs9sgnc", "k": 70, "meal": "Dinner", "n": "Boiled egg", "p": 6, "portion": "1 egg", "qty": 1, "src": "suggestion"},
	],
}
MEALS_7 = {
	"date": "2026-10-07",
	"savedAt": "2026-10-07T08:33:46.094Z",
	"items": [
		{"id": "muxumr03k6d4", "k": 250, "meal": "Breakfast", "n": "Mandazi", "p": 4, "portion": "1", "qty": 2, "src": "list"},
		{"id": "muxumwk3ncxa", "k": 70, "meal": "Breakfast", "n": "Boiled egg", "p": 6, "portion": "1 egg", "qty": 1, "src": "list"},
		{"id": "muxup5ke0s2q", "k": 150, "meal": "Breakfast", "n": "Beef Samosa", "p": 5, "portion": "1 samosa (~50g)", "qty": 1, "src": "custom"},
	],
}
MYFOODS = {
	"items": [
		{"k": 0, "n": "1 samosa, 1 beef sausage, 1 egg, 2 mandazi and a cup of instant coffee", "p": 0, "portion": ""},
		{"k": 150, "n": "Beef Samosa", "p": 5, "portion": "1 samosa (~50g)"},
	]
}


class TestMigrateWebLog(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.tmp = tempfile.TemporaryDirectory()
		root = Path(self.tmp.name)
		self.write(root / "sessions" / "2026-10-06.json", SESSION)
		self.write(root / "meals" / "2026-10-06.json", MEALS_6)
		# One file wrapped as docs/06 describes, to cover both shapes.
		self.write(root / "meals" / "2026-10-07.json", {"id": "x", "data": MEALS_7, "version": 1, "updatedAt": 0})
		self.write(root / "settings" / "myfoods.json", MYFOODS)
		self.folder = str(root)

	def tearDown(self):
		self.tmp.cleanup()
		super().tearDown()

	@staticmethod
	def write(path: Path, data: dict):
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(data))

	def test_totals_match_the_export(self):
		frappe.set_user("Administrator")
		summary = migrate(self.folder, USER_A)
		self.assertEqual(summary["profile"], "created")
		self.assertEqual(summary["sessions"], {"saved": 1, "skipped_newer_in_app": 0})
		self.assertEqual(summary["sets"], 12)
		self.assertEqual((summary["food_days"], summary["entries"]), (2, 9))
		self.assertEqual(summary["custom_foods"]["saved"], 1)
		self.assertEqual(len(summary["custom_foods"]["skipped"]), 1)

		frappe.set_user(USER_A)
		self.assertEqual(today.get("2026-10-06")["food"], {"kcal": 1645, "protein_g": 125, "entries": 6})
		self.assertEqual(today.get("2026-10-07")["food"], {"kcal": 720, "protein_g": 19, "entries": 3})
		session = sessions.get("2026-10-06")
		self.assertEqual((session["routine_key"], session["status"], len(session["sets"])), ("lower", "done", 12))
		self.assertEqual(session["finished_at"], "2026-10-06T16:14:39.133Z")
		self.assertEqual(food.get_day("2026-10-06")["entries"][1]["meal"], "breakfast")
		self.assertEqual(food.get_day("2026-10-06")["entries"][0]["source"], "migrated")
		profile = frappe.get_doc("LL Profile", USER_A)
		self.assertEqual((profile.weight_kg, profile.kcal_target, profile.protein_target_g), (72, 2200, 130))

	def test_running_twice_changes_nothing(self):
		frappe.set_user("Administrator")
		migrate(self.folder, USER_A)
		migrate(self.folder, USER_A)
		self.assertEqual(frappe.db.count("LL Workout Session", {"user": USER_A}), 1)
		self.assertEqual(frappe.db.count("LL Food Day", {"user": USER_A}), 2)
		frappe.set_user(USER_A)
		self.assertEqual(today.get("2026-10-06")["food"]["entries"], 6)
		self.assertEqual(frappe.db.count("LL Food Item", {"user": USER_A, "is_seed": 0}), 1)

	def test_keeps_food_added_in_the_app(self):
		self.make_profile()
		food.save_day(
			food_date="2026-10-07",
			client_updated_at="2026-10-07T12:00:00Z",
			entries=[{"client_id": "app1", "meal": "lunch", "food_name": "Chapati", "qty": 1, "kcal_per_portion": 180, "protein_per_portion": 4}],
		)
		frappe.set_user("Administrator")
		migrate(self.folder, USER_A)
		frappe.set_user(USER_A)
		day = food.get_day("2026-10-07")
		self.assertEqual(len(day["entries"]), 4)
		self.assertEqual(day["client_updated_at"], "2026-10-07T12:00:00.000Z")

	def test_never_replaces_a_newer_session_from_the_app(self):
		self.make_profile()
		sessions.save(
			session_date="2026-10-06",
			client_updated_at="2026-10-06T18:00:00Z",
			status="done",
			sets=[{"exercise": "Barbell back squat", "kg": 40, "amount": 8, "effort": "easy", "done": True}],
		)
		frappe.set_user("Administrator")
		summary = migrate(self.folder, USER_A)
		self.assertEqual(summary["sessions"]["skipped_newer_in_app"], 1)
		frappe.set_user(USER_A)
		self.assertEqual(len(sessions.get("2026-10-06")["sets"]), 1)

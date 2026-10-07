import frappe

from lift_log.api import checkins, export, food, sessions
from lift_log.tests.helpers import FOOD_6_OCT, SESSION_6_OCT, USER_A, USER_B, LiftLogTestCase


class TestExport(LiftLogTestCase):
	def test_export_contains_only_own_data(self):
		self.make_profile()
		sessions.save(**SESSION_6_OCT)
		food.save_day(**FOOD_6_OCT)
		food.save_item(food_name="Beef Samosa", portion="1", kcal=150, protein_g=5)
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=72)

		out = export.all()
		self.assertEqual(out["user"], USER_A)
		self.assertEqual(out["profile"]["weight_kg"], 72)
		self.assertNotIn("program", out["profile"])
		self.assertEqual(len(out["sessions"]), 1)
		self.assertEqual(len(out["sessions"][0]["sets"]), 12)
		self.assertEqual(len(out["food_days"][0]["entries"]), 6)
		self.assertEqual([f["food_name"] for f in out["custom_foods"]], ["Beef Samosa"])
		self.assertEqual(len(out["checkins"]), 1)
		self.assertEqual(out["reviews"], [])

		frappe.set_user(USER_B)
		other = export.all()
		self.assertIsNone(other["profile"])
		for key in ("sessions", "food_days", "custom_foods", "checkins", "reviews"):
			self.assertEqual(other[key], [], key)

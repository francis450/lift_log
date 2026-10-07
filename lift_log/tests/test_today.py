import frappe

from lift_log.api import food, sessions, today
from lift_log.tests.helpers import FOOD_6_OCT, SESSION_6_OCT, USER_A, LiftLogTestCase


class TestToday(LiftLogTestCase):
	def test_7_oct_is_conditioning_week_1(self):
		self.make_profile()
		out = today.get("2026-10-07")
		self.assertEqual(out["week"], 1)
		self.assertEqual(out["phase"], "build")
		self.assertEqual(out["routine"]["key"], "conditioning")
		self.assertEqual(out["routine"]["name"], "Conditioning + Core")
		self.assertIsNone(out["session"])
		self.assertEqual(out["targets"], {"kcal": 2200, "protein_g": 130})
		self.assertEqual([d["date"] for d in out["week_strip"]][0], "2026-10-05")
		self.assertEqual(len(out["week_strip"]), 7)

	def test_works_before_profile_setup(self):
		frappe.set_user(USER_A)
		out = today.get("2026-10-07")
		self.assertEqual(out["routine"]["key"], "conditioning")
		self.assertEqual(out["targets"]["kcal"], 2200)

	def test_logged_day_shows_in_strip_food_and_last_session(self):
		self.make_profile()
		sessions.save(**SESSION_6_OCT)
		food.save_day(**FOOD_6_OCT)
		out = today.get("2026-10-07")
		tue = out["week_strip"][1]
		self.assertEqual(tue, {"date": "2026-10-06", "trained": True, "fed": True})
		self.assertFalse(out["week_strip"][2]["trained"])
		last = out["last_session"]
		self.assertEqual(last["date"], "2026-10-06")
		self.assertEqual(last["highlight"]["exercise"], "Barbell back squat")
		self.assertEqual([s["amount"] for s in last["highlight"]["sets"]], [8, 7, 7])

		day = today.get("2026-10-06")
		self.assertEqual(day["food"], {"kcal": 1645, "protein_g": 125, "entries": 6})
		self.assertEqual(day["session"]["routine_key"], "lower")

	def test_deload_and_sunday_and_out_of_program(self):
		self.make_profile()
		self.assertEqual(today.get("2026-10-26")["routine"]["key"], "home_deload")
		self.assertIsNone(today.get("2026-10-27")["routine"])
		self.assertEqual(today.get("2026-10-27")["phase"], "deload")
		sunday = today.get("2026-10-11")["routine"]
		self.assertTrue(sunday["rest"])
		before = today.get("2026-10-01")
		self.assertIsNone(before["week"])
		self.assertIsNone(before["routine"])

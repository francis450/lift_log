import frappe

from lift_log.api import checkins
from lift_log.tests.helpers import USER_A, USER_B, LiftLogTestCase


class TestCheckins(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.make_profile()

	def test_save_updates_profile_weight_and_targets(self):
		out = checkins.save(week=1, checkin_date="2026-10-11", weight_kg=75, sleep=3, energy=4)
		self.assertEqual(out["weight_kg"], 75)
		self.assertIsNone(out["waist_cm"])
		profile = frappe.get_doc("LL Profile", USER_A)
		self.assertEqual(profile.weight_kg, 75)
		self.assertEqual(profile.protein_target_g, 135)
		self.assertIn("weight updated", profile.targets_note)

	def test_upsert_by_week(self):
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=72)
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=71.5)
		self.assertEqual(frappe.db.count("LL Check In", {"user": USER_A}), 1)
		self.assertEqual(checkins.get(week=1)["checkin"]["weight_kg"], 71.5)

	def test_older_checkin_does_not_overwrite_profile_weight(self):
		checkins.save(week=2, checkin_date="2026-10-18", weight_kg=71)
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=73)
		self.assertEqual(frappe.db.get_value("LL Profile", USER_A, "weight_kg"), 71)

	def test_get_prefill_and_measurements_due(self):
		first = checkins.get(week=1)
		self.assertIsNone(first["checkin"])
		self.assertEqual(first["previous_weight_kg"], 72)
		self.assertEqual(first["due"], {"waist": True, "forearm": True})

		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=71.8, waist_cm=84, forearm_cm=29.5)
		week2 = checkins.get(week=2)
		self.assertEqual(week2["previous_weight_kg"], 71.8)
		self.assertEqual(week2["last_measured"], {"waist": "2026-10-11", "forearm": "2026-10-11"})
		self.assertEqual(week2["due"], {"waist": False, "forearm": False})
		self.assertEqual(checkins.get(week=3)["due"], {"waist": True, "forearm": True})

	def test_validation(self):
		with self.assertRaises(frappe.ValidationError):
			checkins.save(week=1, checkin_date="2026-10-11", weight_kg=72, sleep=6)
		with self.assertRaises(frappe.ValidationError):
			checkins.save(week=1, checkin_date="2026-10-11", weight_kg=None)
		with self.assertRaises(frappe.ValidationError):
			checkins.save(week=13, checkin_date="2026-10-11", weight_kg=72)

	def test_isolation(self):
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=72)
		frappe.set_user(USER_B)
		self.assertIsNone(checkins.get(week=1)["checkin"])

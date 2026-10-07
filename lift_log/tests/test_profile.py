import frappe

from lift_log.api import profile
from lift_log.targets import kcal_target, protein_target
from lift_log.tests.helpers import USER_A, USER_B, LiftLogTestCase


class TestTargetFormulas(LiftLogTestCase):
	def test_protein_target(self):
		self.assertEqual(protein_target(72), 130)
		self.assertEqual(protein_target(75), 135)
		self.assertIsNone(protein_target(None))

	def test_kcal_target(self):
		self.assertEqual(kcal_target(72, None, 25), 2200)
		self.assertEqual(kcal_target(72, 175, None), 2200)
		self.assertEqual(kcal_target(72, 175, 25), 2150)


class TestProfile(LiftLogTestCase):
	def test_get_before_setup_returns_defaults(self):
		frappe.set_user(USER_A)
		out = profile.get()
		self.assertFalse(out["exists"])
		self.assertEqual(out["kcal_target"], 2200)
		self.assertEqual(out["active_program"], "block-2-2026")
		self.assertEqual(out["program"]["id"], "block-2-2026")
		self.assertFalse(frappe.db.exists("LL Profile", USER_A))

	def test_no_height_gives_2200_and_130(self):
		out = self.make_profile()
		self.assertEqual((out["kcal_target"], out["protein_target_g"]), (2200, 130))
		self.assertIsNone(out["height_cm"])
		self.assertIsNone(out["targets_note"])
		self.assertEqual(out["session_time"], "18:00")
		self.assertEqual(out["reminders"], {"workout": True, "dinner": True, "checkin": True})

	def test_adding_height_recalculates_with_note(self):
		self.make_profile()
		out = profile.save(height_cm=175)
		self.assertEqual(out["kcal_target"], 2150)
		self.assertEqual(out["targets_note"], "Targets updated: 2,150 kcal, 130 g protein (height added).")
		out = profile.save(targets_note="")
		self.assertIsNone(out["targets_note"])
		self.assertEqual(out["kcal_target"], 2150)

	def test_manual_target_is_left_alone_until_switched_back(self):
		self.make_profile()
		out = profile.save(kcal_target=2000)
		self.assertTrue(out["kcal_target_manual"])
		out = profile.save(height_cm=175)
		self.assertEqual(out["kcal_target"], 2000)
		out = profile.save(kcal_target_manual=0)
		self.assertFalse(out["kcal_target_manual"])
		self.assertEqual(out["kcal_target"], 2150)
		self.assertIn("calories back to automatic", out["targets_note"])

	def test_manual_protein_target(self):
		self.make_profile()
		out = profile.save(protein_target_g=150)
		self.assertTrue(out["protein_target_manual"])
		out = profile.save(weight_kg=80)
		self.assertEqual(out["protein_target_g"], 150)

	def test_client_cannot_write_another_users_profile(self):
		self.make_profile(USER_B)
		frappe.set_user(USER_A)
		profile.save(weight_kg=70, user=USER_B)  # unknown/forbidden fields are ignored
		self.assertEqual(frappe.db.get_value("LL Profile", USER_B, "weight_kg"), 72)
		self.assertEqual(frappe.db.get_value("LL Profile", USER_A, "weight_kg"), 70)
		doc = frappe.get_doc("LL Profile", USER_B)
		self.assertFalse(doc.has_permission("read"))

	def test_invalid_values_are_rejected(self):
		self.make_profile()
		with self.assertRaises(frappe.ValidationError):
			profile.save(time_zone="Mars/Olympus")
		with self.assertRaises(frappe.ValidationError):
			profile.save(training_days="mon,funday")

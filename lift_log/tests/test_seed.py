import frappe

from lift_log.setup.seed import load
from lift_log.tests.helpers import LiftLogTestCase


class TestSeed(LiftLogTestCase):
	def test_seed_counts_and_idempotency(self):
		self.assertEqual(frappe.db.count("LL Program"), 1)
		self.assertEqual(frappe.db.count("LL Exercise"), 32)
		self.assertEqual(frappe.db.count("LL Food Item", {"is_seed": 1}), 44)
		modified = frappe.db.get_value("LL Program", "block-2-2026", "modified")
		summary = load()
		self.assertEqual(summary, {"program": {"unchanged": 1}, "exercises": {"unchanged": 32}, "foods": {"unchanged": 44}})
		self.assertEqual(frappe.db.get_value("LL Program", "block-2-2026", "modified"), modified)

	def test_seed_foods_carry_grams_per_portion(self):
		oats = frappe.db.get_value("LL Food Item", {"is_seed": 1, "food_name": "Oats, dry"}, ["kcal", "protein_g", "grams_per_portion"], as_dict=True)
		self.assertEqual((oats.kcal, oats.protein_g, oats.grams_per_portion), (152, 5.2, 40))
		stew = frappe.db.get_value("LL Food Item", {"is_seed": 1, "food_name": "Meal prep: Beef and ndengu stew"}, ["kcal", "grams_per_portion"], as_dict=True)
		self.assertEqual(stew.kcal, 436)
		self.assertFalse(stew.grams_per_portion)

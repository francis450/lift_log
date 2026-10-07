import frappe

from lift_log.setup.seed import load
from lift_log.tests.helpers import LiftLogTestCase


class TestSeed(LiftLogTestCase):
	def test_seed_counts_and_idempotency(self):
		self.assertEqual(frappe.db.count("LL Program"), 1)
		self.assertEqual(frappe.db.count("LL Exercise"), 32)
		self.assertEqual(frappe.db.count("LL Food Item", {"is_seed": 1}), 30)
		modified = frappe.db.get_value("LL Program", "block-2-2026", "modified")
		summary = load()
		self.assertEqual(summary, {"program": {"unchanged": 1}, "exercises": {"unchanged": 32}, "foods": {"unchanged": 30}})
		self.assertEqual(frappe.db.get_value("LL Program", "block-2-2026", "modified"), modified)

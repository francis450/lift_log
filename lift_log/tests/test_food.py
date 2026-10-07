import copy

import frappe

from lift_log.api import food
from lift_log.tests.helpers import FOOD_6_OCT, USER_A, USER_B, LiftLogTestCase


def payload(**changes):
	out = copy.deepcopy(FOOD_6_OCT)
	out.update(changes)
	return out


def entry(client_id, food_name="Chapati", qty=1, meal="lunch"):
	return {"client_id": client_id, "meal": meal, "food_name": food_name, "portion": "1 medium", "qty": qty, "kcal_per_portion": 180, "protein_per_portion": 4, "source": "search"}


class TestFood(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.make_profile()

	def test_save_and_get_day(self):
		out = food.save_day(**payload())
		self.assertEqual(len(out["entries"]), 6)
		self.assertEqual(out["entries"][0]["client_id"], "muwvrnngznij")
		self.assertEqual(out["entries"][0]["added_at"], "2026-10-06T16:22:25.766Z")
		self.assertEqual(food.get_day("2026-10-06"), out)
		self.assertEqual(food.get_day("2026-10-08"), {"food_date": "2026-10-08", "client_updated_at": None, "entries": []})

	def test_upsert_is_idempotent(self):
		food.save_day(**payload())
		food.save_day(**payload())
		self.assertEqual(frappe.db.count("LL Food Day", {"user": USER_A}), 1)
		self.assertEqual(len(food.get_day("2026-10-06")["entries"]), 6)

	def test_client_id_dedupe(self):
		out = food.save_day(
			food_date="2026-10-07",
			client_updated_at="2026-10-07T08:00:00Z",
			entries=[entry("a"), entry("b", "Chai with milk and sugar"), entry("a", qty=2)],
		)
		self.assertEqual([(e["client_id"], e["qty"]) for e in out["entries"]], [("a", 2), ("b", 1)])

	def test_confirmed_repeat_with_new_id_is_kept(self):
		out = food.save_day(food_date="2026-10-07", client_updated_at="2026-10-07T08:00:00Z", entries=[entry("a"), entry("a2")])
		self.assertEqual(len(out["entries"]), 2)

	def test_stale_write_gets_409(self):
		food.save_day(food_date="2026-10-07", client_updated_at="2026-10-07T09:00:00Z", entries=[entry("a"), entry("b")])
		out = food.save_day(food_date="2026-10-07", client_updated_at="2026-10-07T08:00:00Z", entries=[entry("a")])
		self.assertEqual(self.status_code(), 409)
		self.assertEqual(len(out["stored"]["entries"]), 2)
		self.assertEqual(len(food.get_day("2026-10-07")["entries"]), 2)

	def test_invalid_entries_are_rejected(self):
		for bad in ({"client_id": ""}, {"meal": "brunch"}, {"source": "telepathy"}, {"qty": 0}):
			with self.assertRaises(frappe.ValidationError):
				food.save_day(food_date="2026-10-07", entries=[{**entry("x"), **bad}])

	def test_search_cha_lists_chapati_and_chai(self):
		out = food.search("cha")
		names = [i["food_name"] for i in out["library"]]
		self.assertIn("Chapati", names)
		self.assertIn("Chai with milk and sugar", names)
		self.assertEqual(out["recent"], [])

	def test_search_recent_and_mine(self):
		frappe.set_user(USER_A)
		food.save_day(food_date=frappe.utils.today(), entries=[entry("a", "Beef Samosa")])
		food.save_item(food_name="Beef Samosa", portion="1 samosa (~50g)", kcal=150, protein_g=5)
		food.save_item(food_name="beef samosa", portion="1 samosa (~50g)", kcal=160, protein_g=5)
		out = food.search("samosa")
		self.assertEqual([i["food_name"] for i in out["recent"]], ["Beef Samosa"])
		self.assertEqual(len(out["mine"]), 1)
		self.assertEqual(out["mine"][0]["kcal"], 160)
		self.assertEqual(out["library"], [])

	def test_custom_foods_are_private(self):
		food.save_item(food_name="Beef Samosa", portion="1", kcal=150, protein_g=5)
		food.save_day(**payload())
		frappe.set_user(USER_B)
		out = food.search("")
		self.assertEqual(out["mine"], [])
		self.assertEqual(out["recent"], [])
		self.assertEqual(len(out["library"]), 20)
		self.assertEqual(food.get_day("2026-10-06")["entries"], [])
		visible = frappe.get_list("LL Food Item", pluck="food_name", limit=100)
		self.assertNotIn("Beef Samosa", visible)
		self.assertIn("Chapati", visible)
		seed = frappe.get_doc("LL Food Item", {"is_seed": 1, "food_name": "Chapati"})
		self.assertTrue(seed.has_permission("read"))
		self.assertFalse(seed.has_permission("write"))

	def test_month_totals(self):
		food.save_day(**payload())
		food.save_day(food_date="2026-10-07", entries=[entry("a"), entry("b", meal="dinner")])
		self.assertEqual(
			food.month("2026-10"),
			[
				{"date": "2026-10-06", "kcal": 1645, "protein_g": 125, "entries": 6, "meals": 3},
				{"date": "2026-10-07", "kcal": 360, "protein_g": 8, "entries": 2, "meals": 2},
			],
		)
		self.assertEqual(food.month("2026-11"), [])
		frappe.set_user(USER_B)
		self.assertEqual(food.month("2026-10"), [])

	def test_users_cannot_create_seed_items(self):
		frappe.set_user(USER_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "LL Food Item", "food_name": "Fake seed", "kcal": 1, "is_seed": 1}).insert()
		doc = frappe.get_doc({"doctype": "LL Food Item", "food_name": "Mine", "kcal": 1, "user": USER_B}).insert()
		self.assertEqual((doc.is_seed, doc.user, doc.owner), (0, USER_A, USER_A))

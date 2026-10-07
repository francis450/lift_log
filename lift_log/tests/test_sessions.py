import copy

import frappe

from lift_log.api import sessions
from lift_log.tests.helpers import SESSION_6_OCT, USER_A, USER_B, LiftLogTestCase


def payload(**changes):
	out = copy.deepcopy(SESSION_6_OCT)
	out.update(changes)
	return out


class TestSessions(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.make_profile()

	def count(self, user=USER_A):
		return frappe.db.count("LL Workout Session", {"user": user})

	def test_save_and_get(self):
		out = sessions.save(**payload())
		self.assertEqual(out["status"], "done")
		self.assertEqual(out["week"], 1)
		self.assertEqual(out["program"], "block-2-2026")
		self.assertEqual(out["started_at"], "2026-10-06T15:02:00.000Z")
		self.assertEqual(out["client_updated_at"], "2026-10-06T16:14:39.133Z")
		self.assertEqual(len(out["sets"]), 12)
		self.assertEqual(sessions.get("2026-10-06"), out)
		self.assertIsNone(sessions.get("2026-10-07"))

	def test_upsert_is_idempotent(self):
		first = sessions.save(**payload())
		second = sessions.save(**payload())
		self.assertEqual(self.count(), 1)
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(len(second["sets"]), 12)
		self.assertIsNone(self.status_code())

	def test_newer_write_replaces_sets(self):
		sessions.save(**payload())
		out = sessions.save(
			**payload(
				client_updated_at="2026-10-06T17:00:00Z",
				sets=[{"exercise": "Barbell back squat", "set_no": 1, "kg": 42.5, "amount": 6, "effort": "Hard", "done": True}],
			)
		)
		self.assertEqual(self.count(), 1)
		self.assertEqual(out["sets"], [{"exercise": "Barbell back squat", "set_no": 1, "kg": 42.5, "amount": 6, "effort": "hard", "done": True}])

	def test_stale_write_gets_409_with_stored_copy(self):
		sessions.save(**payload(client_updated_at="2026-10-06T17:00:00Z", note="newer"))
		out = sessions.save(**payload(client_updated_at="2026-10-06T16:00:00Z", note="older"))
		self.assertEqual(self.status_code(), 409)
		self.assertEqual(out["stored"]["note"], "newer")
		self.assertEqual(frappe.db.get_value("LL Workout Session", {"user": USER_A}, "note"), "newer")

	def test_rows_without_reps_are_skipped_and_blank_kg_is_null(self):
		out = sessions.save(
			**payload(
				sets=[
					{"exercise": "Plank", "kg": "", "amount": 45, "done": True},
					{"exercise": "Plank", "kg": "", "amount": None, "done": False},
					{"exercise": "Plank", "kg": None, "amount": 50, "done": True},
				]
			)
		)
		self.assertEqual([(s["set_no"], s["kg"], s["amount"]) for s in out["sets"]], [(1, None, 45), (2, None, 50)])

	def test_unknown_exercise_or_effort_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			sessions.save(**payload(sets=[{"exercise": "Leg press", "kg": 100, "amount": 10}]))
		with self.assertRaises(frappe.ValidationError):
			sessions.save(**payload(sets=[{"exercise": "Plank", "amount": 10, "effort": "brutal"}]))

	def test_permission_isolation(self):
		mine = sessions.save(**payload())
		frappe.set_user(USER_B)
		self.assertIsNone(sessions.get("2026-10-06"))
		self.assertEqual(sessions.history("Barbell back squat"), [])
		self.assertEqual(sessions.month("2026-10"), [])
		self.assertEqual(frappe.get_list("LL Workout Session", filters={"user": USER_A}), [])
		doc = frappe.get_doc("LL Workout Session", mine["name"])
		self.assertFalse(doc.has_permission("read"))
		with self.assertRaises(frappe.PermissionError):
			doc.check_permission("write")

		# B's own write for the same date is a separate record, and B can't write one as A.
		sessions.save(**payload())
		self.assertEqual(self.count(USER_B), 1)
		self.assertEqual(self.count(USER_A), 1)
		other = frappe.get_doc({"doctype": "LL Workout Session", "user": USER_A, "session_date": "2026-10-08"})
		with self.assertRaises(frappe.PermissionError):
			other.insert()

	def test_history_newest_first_with_only_that_exercise(self):
		sessions.save(**payload())
		sessions.save(
			**payload(
				session_date="2026-10-13",
				sets=[
					{"exercise": "Barbell back squat", "kg": 40, "amount": 8},
					{"exercise": "Hip thrust", "kg": 50, "amount": 10},
				],
			)
		)
		out = sessions.history("Barbell back squat", limit=6)
		self.assertEqual([h["date"] for h in out], ["2026-10-13", "2026-10-06"])
		self.assertEqual(len(out[1]["sets"]), 3)
		self.assertTrue(all(len(h["sets"]) for h in out))
		self.assertEqual(len(sessions.history("Barbell back squat", limit=1)), 1)

	def test_month(self):
		sessions.save(**payload())
		out = sessions.month("2026-10")
		self.assertEqual(out, [{"date": "2026-10-06", "routine_key": "lower", "routine_name": "Lower + Walk", "sets": 12, "status": "done"}])
		self.assertEqual(sessions.month("2026-11"), [])
		with self.assertRaises(frappe.ValidationError):
			sessions.month("October")

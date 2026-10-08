import copy
import json
from datetime import date
from unittest.mock import patch

import frappe

from lift_log.ai import client
from lift_log.api import ai, checkins, food, sessions
from lift_log.tests.helpers import FOOD_6_OCT, SESSION_6_OCT, USER_A, USER_B
from lift_log.tests.test_ai import AITestCase, reply

AFTER_WEEK_1 = date(2026, 10, 12)

CLAUDE = {
	"went_well": "Two sessions done and the squat held 40 kg for 8, 7, 7.",
	"to_change": "Protein averaged 72 g against 130 g. Three sessions were missed.",
	"changes": [
		{"change_type": "weight", "title": "Squat: +2.5 kg", "why": "Easy sets", "exercise": "Barbell back squat", "delta_kg": 2.5},
		{"change_type": "weight", "title": "Leg press: +5 kg", "why": "x", "exercise": "Leg press", "delta_kg": 5},
		{"change_type": "weight", "title": "RDL: +5 kg", "why": "x", "exercise": "Barbell Romanian deadlift", "delta_kg": 5},
		{"change_type": "weight", "title": "Squat again: +2.5 kg", "why": "x", "exercise": "Barbell back squat", "delta_kg": 2.5},
		{"change_type": "nutrition", "title": "Whey after training", "why": "+24 g protein", "exercise": "", "delta_kg": 0},
		{"change_type": "schedule", "title": "Move a missed Monday to Saturday", "why": "Keeps 5 sessions", "exercise": "", "delta_kg": 0},
		{"change_type": "other", "title": "Sleep by 11", "why": "Energy 2 of 5", "exercise": "", "delta_kg": 0},
		{"change_type": "other", "title": "A fifth valid change", "why": "Over the limit", "exercise": "", "delta_kg": 0},
	],
}


@patch("lift_log.ai.review.user_today", return_value=AFTER_WEEK_1)
class TestWeeklyReview(AITestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("LL Weekly Review", {"user": USER_A})
		session = copy.deepcopy(SESSION_6_OCT)
		for s in session["sets"]:
			if s["exercise"] == "Barbell back squat":
				s["effort"] = "easy"
		sessions.save(**session)
		sessions.save(
			session_date="2026-10-07",
			status="done",
			routine_name="Conditioning + Core",
			sets=[{"exercise": "Plank", "amount": 45, "effort": "right", "done": True}],
		)
		food.save_day(**FOOD_6_OCT)
		food.save_day(
			food_date="2026-10-07",
			entries=[
				{"client_id": "m", "meal": "breakfast", "food_name": "Mandazi", "qty": 2, "kcal_per_portion": 250, "protein_per_portion": 4},
				{"client_id": "e", "meal": "breakfast", "food_name": "Boiled egg", "qty": 1, "kcal_per_portion": 70, "protein_per_portion": 6},
				{"client_id": "s", "meal": "breakfast", "food_name": "Beef Samosa", "qty": 1, "kcal_per_portion": 150, "protein_per_portion": 5},
			],
		)
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=72, sleep=3, energy=2)

	def test_stats_are_computed_in_python(self, _today):
		stats = ai.review_stats(week=1)
		self.assertEqual(stats["period"], ["2026-10-05", "2026-10-11"])
		self.assertEqual((stats["sessions"]["planned"], stats["sessions"]["done"]), (5, 2))
		self.assertEqual(len(stats["sessions"]["missed"]), 3)
		self.assertEqual(stats["sessions"]["missed"][0], "Upper A (Mon)")
		self.assertEqual(stats["effort"], {"easy": 3, "right": 1, "hard": 0, "unrated": 9})
		self.assertEqual(
			{k: stats["food"][k] for k in ("days_logged", "avg_kcal", "avg_protein_g", "protein_days_hit")},
			{"days_logged": 2, "avg_kcal": 1183, "avg_protein_g": 72, "protein_days_hit": 0},
		)
		self.assertEqual(stats["checkin"]["weight_kg"], 72)
		self.assertIsNone(stats["checkin"]["weight_change_kg"])
		lower = stats["sessions"]["items"][0]
		squat = next(e for e in lower["exercises"] if e["name"] == "Barbell back squat")
		self.assertEqual(squat["target"], "3 x 6-8")
		self.assertEqual(squat["rule_call"], {"call": "hold", "kg": 40})
		self.assertEqual(stats["goals"], "Lose fat and get stronger; keep thighs from growing; grow forearms.")

	def test_review_stores_tiles_equal_to_server_stats_and_drops_invalid_changes(self, _today):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(CLAUDE))) as create:
			out = ai.weekly_review(week=1)
		self.assertEqual(out["stats"], ai.review_stats(week=1))
		self.assertEqual(
			[c["title"] for c in out["changes"]],
			["Squat: +2.5 kg", "Whey after training", "Move a missed Monday to Saturday", "Sleep by 11"],
		)
		squat = out["changes"][0]
		self.assertEqual((squat["exercise"], squat["delta_kg"], squat["applies_from_week"], squat["accepted"]), ("Barbell back squat", 2.5, 2, False))
		self.assertIsNone(out["changes"][1]["exercise"])
		params = create.call_args.kwargs["params"]
		self.assertEqual(params["model"], "claude-sonnet-5-5")
		self.assertEqual(params["output_config"]["effort"], "medium")
		self.assertIn('"rule_call"', params["messages"][0]["content"])
		self.assertEqual(create.call_args.kwargs["timeout"], 90)
		self.assertEqual(self.logs()[0].feature, "review")

	def test_stored_review_is_reused_until_regenerated(self, _today):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(CLAUDE))) as create:
			first = ai.weekly_review(week=1)
			again = ai.weekly_review(week=1)
			self.assertEqual(create.call_count, 1)
			self.assertEqual(first["name"], again["name"])
			ai.weekly_review(week=1, regenerate=1)
			self.assertEqual(create.call_count, 2)
		self.assertEqual(frappe.db.count("LL Weekly Review", {"user": USER_A}), 1)

	def test_apply_changes_feeds_next_week(self, _today):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(CLAUDE))):
			ai.weekly_review(week=1)
		out = ai.apply_changes(week=1, accepted=[0, 2])
		self.assertEqual([c["accepted"] for c in out["changes"]], [True, False, True, False])
		plan = ai.plan_changes(week=2)
		self.assertEqual([(p["exercise"], p["delta_kg"]) for p in plan], [("Barbell back squat", 2.5), (None, None)])
		self.assertEqual(ai.plan_changes(week=3), [])
		ai.apply_changes(week=1, accepted="[]")
		self.assertEqual(ai.plan_changes(week=2), [])
		frappe.set_user(USER_B)
		self.assertEqual(ai.plan_changes(week=2), [])

	def test_followup(self, _today):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(CLAUDE))):
			ai.weekly_review(week=1)
		with patch.object(client, "_create_message", return_value=reply("Because 8, 7, 7 at 40 kg felt easy.")) as create:
			out = ai.review_followup(week=1, question="Why move squats up?" + "x" * 900)
		self.assertEqual(out, {"answer": "Because 8, 7, 7 at 40 kg felt easy."})
		prompt = create.call_args.kwargs["params"]["messages"][0]["content"]
		self.assertIn("QUESTION: Why move squats up?", prompt)
		self.assertNotIn("x" * 500, prompt)
		self.assertIn("under 120 words", prompt)
		self.assertEqual(self.logs()[-1].feature, "review_followup")

	def test_rules(self, _today):
		with self.assertRaises(frappe.ValidationError):
			ai.review_followup(week=1, question="Before any review?")
		with self.assertRaises(frappe.ValidationError):
			ai.weekly_review(week=3)  # hasn't started on 12 Oct
		self.set_settings(anthropic_api_key="")
		with self.assertRaises(client.AINotSetUp):
			ai.weekly_review(week=1)

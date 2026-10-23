import json
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import frappe

from lift_log.ai import client
from lift_log.api import ai, food, profile
from lift_log.tests.helpers import USER_A, LiftLogTestCase

TINY_JPEG = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="


def reply(text: str, stop_reason: str = "end_turn"):
	return SimpleNamespace(
		content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
		stop_reason=stop_reason,
		usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
	)


ITEMS = {
	"items": [
		{"food_name": "Chapati", "portion": "2 medium", "kcal": 360, "protein_g": 8},
		{"food_name": "Beef stew", "portion": "1 cup", "kcal": 9000, "protein_g": 30},
		{"food_name": "", "portion": "1", "kcal": 100, "protein_g": 2},
		{"food_name": "Sukuma wiki", "portion": "1 cup", "kcal": "80", "protein_g": -1},
	]
}


class AITestCase(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("LL AI Log", {"user": USER_A})
		self.set_settings(anthropic_api_key="sk-ant-test", ai_enabled=1, daily_ai_calls_per_user=40)
		self.make_profile()
		frappe.set_user(USER_A)

	def tearDown(self):
		frappe.set_user("Administrator")
		self.set_settings(anthropic_api_key="", ai_enabled=1, daily_ai_calls_per_user=40)
		frappe.db.delete("LL AI Log", {"user": USER_A})
		frappe.db.commit()
		super().tearDown()

	@staticmethod
	def set_settings(**values):
		current = frappe.session.user
		frappe.set_user("Administrator")
		s = frappe.get_single("LL Settings")
		s.update(values)
		s.save()
		frappe.set_user(current)

	def logs(self):
		return frappe.get_all(
			"LL AI Log",
			filters={"user": USER_A},
			fields=["feature", "model", "input_tokens", "output_tokens", "ok", "error_code", "latency_ms"],
			order_by="creation asc",
		)


class TestEstimate(AITestCase):
	def test_text_estimate_uses_quick_model_and_drops_bad_items(self):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(ITEMS))) as create:
			out = ai.estimate(text="2 chapati and beef stew")
		self.assertEqual(out["items"], [{"food_name": "Chapati", "portion": "2 medium", "kcal": 360, "protein_g": 8.0}])
		self.assertEqual(out["model"], "claude-haiku-4-5-20251001")
		params = create.call_args.kwargs["params"]
		self.assertEqual(params["model"], "claude-haiku-4-5-20251001")
		self.assertEqual(params["output_config"]["format"]["type"], "json_schema")
		self.assertNotIn("effort", params["output_config"])  # Haiku 4.5 doesn't take effort
		self.assertIn("What the user ate: 2 chapati and beef stew", params["messages"][0]["content"])
		self.assertFalse(create.call_args.kwargs["fallbacks"])
		self.assertEqual(create.call_args.kwargs["timeout"], 30)
		log = self.logs()
		self.assertEqual(len(log), 1)
		self.assertEqual((log[0].feature, log[0].ok, log[0].input_tokens, log[0].output_tokens), ("estimate_text", 1, 1200, 150))

	def test_photo_estimate_uses_vision_model_low_effort_and_fallbacks(self):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(ITEMS))) as create:
			ai.estimate(text="with chai", image_base64=TINY_JPEG, image_mime="image/jpeg")
		params = create.call_args.kwargs["params"]
		self.assertEqual(params["model"], "claude-sonnet-5-5")
		self.assertEqual(params["output_config"]["effort"], "low")
		content = params["messages"][0]["content"]
		self.assertEqual(content[0]["type"], "image")
		self.assertEqual(content[0]["source"]["media_type"], "image/jpeg")
		self.assertIn("Extra details from the user: with chai", content[1]["text"])
		self.assertTrue(create.call_args.kwargs["fallbacks"])
		self.assertEqual(self.logs()[0].feature, "estimate_photo")

	def test_text_is_cut_to_1500_characters(self):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(ITEMS))) as create:
			ai.estimate(text="x" * 4000)
		prompt = create.call_args.kwargs["params"]["messages"][0]["content"]
		self.assertIn("x" * 1500, prompt)
		self.assertNotIn("x" * 1501, prompt)

	def test_unparseable_reply_is_retried_once(self):
		replies = [reply("Sure! Here you go."), reply("```json\n" + json.dumps(ITEMS) + "\n```")]
		with patch.object(client, "_create_message", side_effect=replies) as create:
			out = ai.estimate(text="ugali")
		self.assertEqual(len(out["items"]), 1)
		self.assertEqual(create.call_count, 2)
		self.assertTrue(create.call_args.kwargs["params"]["messages"][0]["content"].endswith("Reply with only the JSON."))

	def test_two_unparseable_replies_give_502(self):
		with patch.object(client, "_create_message", side_effect=[reply("no"), reply("still no")]):
			with self.assertRaises(client.AIError) as ctx:
				ai.estimate(text="ugali")
		self.assertEqual(ctx.exception.http_status_code, 502)
		self.assertIn("Couldn't read the estimate. Try again.", str(frappe.local.message_log))

	def test_refusal_and_timeout_are_logged_and_reported(self):
		with patch.object(client, "_create_message", return_value=reply("", stop_reason="refusal")):
			with self.assertRaises(client.AIError):
				ai.estimate(text="ugali")
		timeout = anthropic.APITimeoutError.__new__(anthropic.APITimeoutError)
		with patch.object(client, "_create_message", side_effect=timeout):
			with self.assertRaises(client.AITimeout) as ctx:
				ai.estimate(text="ugali")
		self.assertEqual(ctx.exception.http_status_code, 504)
		self.assertEqual([(l.ok, l.error_code) for l in self.logs()], [(0, "refusal"), (0, "timeout")])

	def test_photo_checks(self):
		with self.assertRaises(frappe.ValidationError):
			ai.estimate(image_base64=TINY_JPEG, image_mime="image/heic")
		with self.assertRaises(frappe.ValidationError):
			ai.estimate(image_base64="not base64!!")
		self.set_settings(max_image_mb=0.00001)
		with self.assertRaises(frappe.ValidationError):
			ai.estimate(image_base64=TINY_JPEG, image_mime="image/jpeg")
		self.set_settings(max_image_mb=5)
		with self.assertRaises(frappe.ValidationError):
			ai.estimate()
		self.assertEqual(self.logs(), [])


class TestLimitsAndSetup(AITestCase):
	def test_without_a_key_the_tabs_say_not_set_up(self):
		self.set_settings(anthropic_api_key="")
		self.assertEqual(profile.get()["ai"], {"ready": False, "message": "AI features aren't set up on your server"})
		with self.assertRaises(client.AINotSetUp) as ctx:
			ai.estimate(text="ugali")
		self.assertEqual(ctx.exception.http_status_code, 503)

	def test_ready_with_a_key(self):
		self.assertEqual(profile.get()["ai"], {"ready": True, "message": None})

	def test_switches_off(self):
		profile.save(ai_enabled=0)
		self.assertFalse(profile.get()["ai"]["ready"])
		with self.assertRaises(client.AIOff):
			ai.estimate(text="ugali")
		profile.save(ai_enabled=1)
		self.set_settings(ai_enabled=0)
		with self.assertRaises(client.AINotSetUp):
			ai.estimate(text="ugali")

	def test_daily_limit(self):
		self.set_settings(daily_ai_calls_per_user=2)
		with patch.object(client, "_create_message", return_value=reply(json.dumps(ITEMS))) as create:
			ai.estimate(text="a")
			ai.estimate(text="b")
			with self.assertRaises(client.AILimitReached) as ctx:
				ai.estimate(text="c")
		self.assertEqual(create.call_count, 2)
		self.assertEqual(ctx.exception.http_status_code, 429)
		self.assertIn("Daily AI limit reached. It resets at midnight.", str(frappe.local.message_log))

	def test_log_keeps_no_prompt_or_image(self):
		with patch.object(client, "_create_message", return_value=reply(json.dumps(ITEMS))):
			ai.estimate(text="secret dinner details", image_base64=TINY_JPEG, image_mime="image/jpeg")
		row = frappe.get_all("LL AI Log", filters={"user": USER_A}, fields=["*"])[0]
		dumped = json.dumps(row, default=str)
		self.assertNotIn("secret dinner", dumped)
		self.assertNotIn(TINY_JPEG[:20], dumped)
		self.assertFalse(frappe.db.exists("File", {"attached_to_doctype": "LL AI Log"}))


class TestSuggest(AITestCase):
	def test_context_and_options(self):
		food.save_day(
			food_date="2026-10-07",
			entries=[
				{"client_id": "a", "meal": "breakfast", "food_name": "Mandazi", "qty": 2, "kcal_per_portion": 250, "protein_per_portion": 4},
				{"client_id": "b", "meal": "breakfast", "food_name": "Boiled egg", "qty": 1, "kcal_per_portion": 70, "protein_per_portion": 6},
			],
		)
		options = {
			"options": [
				{"title": "Chicken stew, rice and ndengu", "why": "Closes a third of the gap.", "items": ITEMS["items"][:1]},
				{"title": "Empty", "why": "No valid foods", "items": [{"food_name": "X", "portion": "", "kcal": -5, "protein_g": 1}]},
				*[{"title": f"Option {i}", "why": "", "items": ITEMS["items"][:1]} for i in range(5)],
			]
		}
		with patch.object(client, "_create_message", return_value=reply(json.dumps(options))) as create:
			out = ai.suggest(date="2026-10-07", meal="lunch")
		prompt = create.call_args.kwargs["params"]["messages"][0]["content"]
		self.assertIn("Suggest 3 different options for his lunch", prompt)
		self.assertIn("a 72 kg man", prompt)
		self.assertIn("lifts weights 5 days a week", prompt)
		self.assertIn("Targets today: 2200 kcal and 130 g protein. Remaining: 1630 kcal and", prompt)
		self.assertIn("116 g protein. Eaten so far: breakfast: Mandazi x 2, Boiled egg x 1.", prompt)
		self.assertIn("Training today: Conditioning + Core at 18:00.", prompt)
		self.assertIn("Foods he often eats: Boiled egg, Mandazi.", prompt)
		# Lunch gets 35/75 of what's left; dinner keeps the rest.
		self.assertIn("Budget for his lunch: about 761 kcal and 54 g protein.", prompt)
		self.assertIn("The rest (869 kcal,\n62 g protein) is for dinner", prompt)
		self.assertNotIn("already seen", prompt)
		self.assertEqual(len(out["options"]), 4)
		self.assertEqual(out["options"][0]["title"], "Chicken stew, rice and ndengu")
		self.assertEqual(out["budget"], {"kcal": 761, "protein_g": 54})
		self.assertEqual(self.logs()[0].feature, "suggest")

	def test_more_ideas_name_what_was_shown(self):
		options = {"options": [{"title": "Githeri and eggs", "why": "", "items": ITEMS["items"][:1]}]}
		with patch.object(client, "_create_message", return_value=reply(json.dumps(options))) as create:
			ai.suggest(date="2026-10-07", meal="dinner", exclude=json.dumps(["Bean stew", "Ndengu and rice"]))
		prompt = create.call_args.kwargs["params"]["messages"][0]["content"]
		self.assertIn("He has already seen these, so suggest different meals: Bean stew; Ndengu and rice.", prompt)
		# Dinner is the last main meal, so it gets everything left.
		self.assertNotIn("Budget for", prompt)
		self.assertIn("Close the protein gap without going over the remaining calories.", prompt)

	def test_over_budget_options_dropped(self):
		food.save_day(
			food_date="2026-10-07",
			entries=[{"client_id": "a", "meal": "breakfast", "food_name": "Pilau", "qty": 1, "kcal_per_portion": 1100, "protein_per_portion": 25}],
		)
		big = {"food_name": "Pilau", "portion": "2 plates", "kcal": 1000, "protein_g": 40}
		small = {"food_name": "Chicken", "portion": "150 g", "kcal": 400, "protein_g": 45}
		options = {
			"options": [
				{"title": "Big", "why": "", "items": [big]},
				{"title": "Small", "why": "", "items": [small]},
			]
		}
		with patch.object(client, "_create_message", return_value=reply(json.dumps(options))):
			out = ai.suggest(date="2026-10-07", meal="lunch")
		# 1100 left: lunch gets 513, so 1000 kcal is over 120% of it.
		self.assertEqual([o["title"] for o in out["options"]], ["Small"])

		only_big = {"options": [{"title": "Big", "why": "", "items": [big]}]}
		with patch.object(client, "_create_message", return_value=reply(json.dumps(only_big))):
			out = ai.suggest(date="2026-10-07", meal="lunch")
		self.assertEqual([o["title"] for o in out["options"]], ["Big"])

	def test_meal_budget(self):
		budget = ai.meal_budget
		# The example from the phone: 1102 kcal and 105 g left after breakfast.
		self.assertEqual(
			budget("lunch", 1102, 105, 1950, 130, {"breakfast"}),
			{"kcal": 514, "protein_g": 49, "later": "dinner", "later_kcal": 588, "later_protein_g": 56},
		)
		# Nothing logged: breakfast's share of the whole day.
		b = budget("breakfast", 2000, 140, 2000, 140, set())
		self.assertEqual((b["kcal"], b["protein_g"], b["later"]), (500, 35, "lunch and dinner"))
		# Lunch with breakfast skipped: breakfast is past, so it isn't counted.
		self.assertEqual(budget("lunch", 1500, 100, 2000, 140, set())["kcal"], 700)
		# Lunch skipped: dinner gets everything left.
		d = budget("dinner", 900, 60, 2000, 140, {"breakfast"})
		self.assertEqual((d["kcal"], d["protein_g"], d["later"], d["later_kcal"]), (900, 60, "", 0))
		# Dinner already logged: lunch asked late gets everything too.
		self.assertEqual(budget("lunch", 600, 30, 2000, 140, {"dinner"})["kcal"], 600)
		# Snacks: a tenth of the day while dinner is to come, capped at what's left.
		s = budget("snacks", 1200, 80, 2000, 140, {"breakfast", "lunch"})
		self.assertEqual((s["kcal"], s["protein_g"], s["later"]), (200, 14, "dinner"))
		self.assertEqual(budget("snacks", 150, 5, 2000, 140, set())["kcal"], 150)
		# Snacks after dinner, and no meal: everything left.
		self.assertEqual(budget("snacks", 300, 20, 2000, 140, {"dinner"})["kcal"], 300)
		self.assertEqual(budget(None, 1300, 70, 2000, 140, {"breakfast"})["kcal"], 1300)

	def test_rest_day_and_usual_fallback(self):
		ctx = ai.suggest_context(USER_A, frappe.get_doc("LL Profile", USER_A), frappe.utils.getdate("2026-10-10"), None)
		self.assertEqual(ctx["training"], "rest day")
		self.assertEqual(ctx["eaten"], "nothing yet")
		self.assertEqual(ctx["usual"], "chapati, rice, beef stew, chicken, lentils, beans, eggs")
